# -*- coding: utf-8 -*-
"""
从辣可可小程序（AppService 上下文）读取签到所需参数，直接写入 lakeke.env。

关键点：CDP 的 execution context id 每次连接都会重新编号，所以必须在
**同一条连接内** 完成「枚举 → 逐个尝试 → 取字段最多的那个」，不能分两次连。

安全约定：
  - 只提取需要的字段，不在终端打印原始值（一律脱敏）
  - 结果只落盘 lakeke.env，不写进任何笔记或仓库

用法：python cdp_get_params.py [等待秒数]
"""
import json
import os
import sys
import time
import threading
import websocket

BASE = os.path.dirname(os.path.abspath(__file__))
OUTFILE = os.path.join(BASE, "lakeke.env")
APPID = "wxf8a17a14c0521576"
WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 40
NEED = ["token", "mpId", "openId", "unionId", "gameId",
        "memberId", "cardId", "cardNo", "thirdShopId", "gcId"]

FULL_JS = r"""
(function () {
  var need = %s;
  var out = {};
  function put(k, v) {
    if (v === undefined || v === null || v === '') return;
    if (out[k] === undefined) out[k] = String(v);
  }
  function coerce(v) {
    if (typeof v === 'string') {
      var t = v.trim();
      if ((t.charAt(0) === '{' && t.charAt(t.length - 1) === '}') ||
          (t.charAt(0) === '[' && t.charAt(t.length - 1) === ']')) {
        try { return JSON.parse(t); } catch (e) { return v; }
      }
    }
    return v;
  }
  function scan(o, depth) {
    if (!o || typeof o !== 'object' || depth > 4) return;
    if (Object.prototype.toString.call(o) === '[object Array]') {
      for (var i = 0; i < o.length && i < 50; i++) scan(o[i], depth + 1);
      return;
    }
    for (var k in o) {
      var v = o[k], lk = String(k).toLowerCase();
      if (typeof v === 'string' || typeof v === 'number') {
        for (var n = 0; n < need.length; n++) {
          if (lk === need[n].toLowerCase()) put(need[n], v);
        }
      } else scan(v, depth + 1);
    }
  }
  try {
    var info = wx.getStorageInfoSync();
    info.keys.forEach(function (k) {
      try {
        var raw = wx.getStorageSync(k), lk = String(k).toLowerCase();
        for (var n = 0; n < need.length; n++) {
          if (lk === need[n].toLowerCase() && (typeof raw === 'string' || typeof raw === 'number')) put(need[n], raw);
        }
        scan(coerce(raw), 0);
      } catch (e) {}
    });
  } catch (e) { out.__err = e.message; }
  try { var app = getApp(); if (app) scan(app.globalData, 0); } catch (e) {}
  try {
    (getCurrentPages() || []).forEach(function (p) {
      var d = p.data || {};
      if (d.gameId !== undefined) put('gameId', d.gameId);
      scan(d, 0);
      var mi = d.memberInfo || d.member || {};
      if (mi.id !== undefined) put('memberId', mi.id);
      if (mi.cardId !== undefined) put('cardId', mi.cardId);
      if (mi.cardNo !== undefined) put('cardNo', mi.cardNo);
      if (mi.mcId !== undefined) put('thirdShopId', mi.mcId);
      var bi = d.baseInfo || {};
      if (bi.mcId !== undefined) put('thirdShopId', bi.mcId);
      if (bi.gameId !== undefined) put('gameId', bi.gameId);
      if (bi.mpId !== undefined) put('mpId', bi.mpId);
      scan(mi, 0); scan(bi, 0);
    });
  } catch (e) {}
  return JSON.stringify(out);
})()
""" % json.dumps(NEED)

TEST_JS = "(typeof wx)"

state = {"wx_ctx": [], "found": {}, "done": False}


def send(ws, cid, expr, tag):
    mid = 1000 * (tag + 1) + cid
    try:
        ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "returnByValue": True, "contextId": cid}}))
    except Exception:
        pass


def on_open(ws):
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))


def on_message(ws, data):
    try:
        msg = json.loads(data)
    except json.JSONDecodeError:
        return
    mid = msg.get("id")
    if not isinstance(mid, int) or mid < 1000:
        return
    tag, cid = mid // 1000 - 1, mid % 1000
    val = msg.get("result", {}).get("result", {}).get("value")
    if not val:
        return
    if tag == 0 and val == "object":
        state["wx_ctx"].append(cid)
    elif tag == 1:
        try:
            fields = {k: v for k, v in json.loads(val).items() if not k.startswith("__")}
        except Exception:
            return
        if len(fields) > len(state["found"]):
            state["found"] = fields
        if len(fields) >= 8:
            state["done"] = True


def mask(v):
    s = str(v)
    return f"{s[:4]}{'*' * max(0, len(s) - 8)}{s[-4:]} ({len(s)})" if len(s) > 8 else "*" * len(s)


def attempt(seconds=14):
    state.update({"wx_ctx": [], "found": {}, "done": False})
    ws = websocket.WebSocketApp("ws://127.0.0.1:62000", on_open=on_open, on_message=on_message,
                                on_error=lambda w, e: None)
    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()
    time.sleep(2)
    for cid in range(1, 81):
        send(ws, cid, TEST_JS, 0)
        time.sleep(0.05)
    time.sleep(3)
    print(f"[enum] 有 wx 的上下文: {sorted(set(state['wx_ctx']))}", flush=True)
    best = {}
    for cid in sorted(set(state["wx_ctx"])):
        send(ws, cid, FULL_JS, 1)
        end = time.time() + 3
        while time.time() < end and not state["done"]:
            time.sleep(0.2)
        if state["found"]:
            print(f"[try] ctx {cid}: 累计命中 {sorted(state['found'])}", flush=True)
        if state["done"]:
            best = dict(state["found"])
            break
        best = dict(state["found"])
    try:
        ws.close()
    except Exception:
        pass
    return best or None


def main():
    print(f"[get] 等待 {WAIT}s（小程序需保持打开并在签到页）", flush=True)
    end = time.time() + WAIT
    got = None
    while time.time() < end:
        got = attempt()
        if got and len(got) >= 8:
            break
        time.sleep(3)

    if not got:
        print("[END] 未取到参数：小程序要在 WMPFDebugger 启动之后重新打开，并进到签到页", flush=True)
        sys.exit(1)

    with open(OUTFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(f"LAKEKE_{k.upper()}={v}" for k, v in got.items()) + "\n")
    print(f"\n[save] 已写入 {OUTFILE}（{len(got)} 个字段，勿提交 git）", flush=True)
    print("==== 脱敏摘要 ====", flush=True)
    for k, v in got.items():
        print(f"  LAKEKE_{k.upper()} = {mask(v)}", flush=True)


if __name__ == "__main__":
    main()
