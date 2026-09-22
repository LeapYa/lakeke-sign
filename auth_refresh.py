# -*- coding: utf-8 -*-
"""
主动刷新 token：在小程序逻辑层调 wx.login() 拿 jsCode → POST /auth/login 换新 token → 写 lakeke.env。

要点（踩过的坑）：
  1. **jsCode 必须和 mpId 配对**：辣可可与辣可可甄选同属 wuuxiang SaaS 但是两个租户
     （辣可可 mpId=gh_6****17e8，甄选 mpId=gh_08623aa177ad）。
     code 取自哪个小程序，就必须用那个小程序的 mpId 去换，否则报 invalid code。
     → 本脚本在同一上下文内同时取身份 + 取 code，逐个上下文试。
  2. 不要用 /auth/login 响应里的 openId 覆盖身份（可能是快照用户，签到会报 105）。
  3. 目标上下文以 lakeke.env 里已有的 openId 为准。

用法：python auth_refresh.py [等待秒数]
"""
import base64
import datetime
import json
import os
import ssl
import sys
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
import websocket

BASE = os.path.dirname(os.path.abspath(__file__))
ENVFILE = os.path.join(BASE, "lakeke.env")
LOGIN_URL = "https://wechat.wuuxiang.com/i5xforyou/auth/login"
APPID = "wxf8a17a14c0521576"
WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 60

ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

# 同一上下文内先取身份，再取 code
IDENT_JS = r"""
(function () {
  var out = {};
  // 最可靠的上下文识别方式
  try {
    var ai = wx.getAccountInfoSync();
    out.appId = (ai.miniProgram && ai.miniProgram.appId) || null;
  } catch (e) { out.appId = null; }
  function scan(o, d) {
    if (!o || typeof o !== 'object' || d > 4) return;
    if (Object.prototype.toString.call(o) === '[object Array]') {
      for (var i = 0; i < o.length && i < 30; i++) scan(o[i], d + 1);
      return;
    }
    for (var k in o) {
      var v = o[k], lk = String(k).toLowerCase();
      if (typeof v === 'string' || typeof v === 'number') {
        if (lk === 'mpid' && out.mpId === undefined) out.mpId = String(v);
        if (lk === 'openid' && out.openId === undefined) out.openId = String(v);
        if (lk === 'unionid' && out.unionId === undefined) out.unionId = String(v);
        if (lk === 'gcid' && out.gcId === undefined) out.gcId = String(v);
      } else scan(v, d + 1);
    }
  }
  try {
    var info = wx.getStorageInfoSync();
    info.keys.forEach(function (k) {
      try {
        var v = wx.getStorageSync(k);
        if (typeof v === 'string') { try { v = JSON.parse(v); } catch (e) {} }
        scan(v, 0);
      } catch (e) {}
    });
  } catch (e) { out.__err = e.message; }
  // 页面 data 里也可能有身份信息
  try { (getCurrentPages() || []).forEach(function (p) { scan(p.data, 0); }); } catch (e) {}
  return JSON.stringify(out);
})()
"""

LOGIN_JS = r"""
new Promise(function (resolve) {
  try {
    wx.login({
      success: function (r) { resolve(JSON.stringify({ok: true, code: r.code})); },
      fail: function (e) { resolve(JSON.stringify({ok: false, err: String(e && e.errMsg)})); }
    });
  } catch (e) { resolve(JSON.stringify({ok: false, err: String(e)})); }
})
"""

state = {"ident": {}, "code": {}, "ctx": []}


def send(ws, cid, expr, tag, await_promise=False):
    mid = 1000 * (tag + 1) + cid
    p = {"expression": expr, "returnByValue": True, "contextId": cid}
    if await_promise:
        p["awaitPromise"] = True
    try:
        ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate", "params": p}))
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
        state["ctx"].append(cid)
        send(ws, cid, IDENT_JS, 1)
    elif tag == 1:
        try:
            state["ident"][cid] = json.loads(val)
        except Exception:
            pass
        send(ws, cid, LOGIN_JS, 2, await_promise=True)
    elif tag == 2:
        try:
            state["code"][cid] = json.loads(val)
        except Exception:
            pass


def collect(seconds=12):
    state.update({"ident": {}, "code": {}, "ctx": []})
    ws = websocket.WebSocketApp("ws://127.0.0.1:62000", on_open=on_open, on_message=on_message,
                                on_error=lambda w, e: None)
    threading.Thread(target=ws.run_forever, daemon=True).start()
    time.sleep(2)
    for cid in range(1, 61):
        send(ws, cid, "(typeof wx)", 0)
        time.sleep(0.05)
    end = time.time() + seconds
    while time.time() < end and len(state["code"]) < len(state["ctx"]):
        time.sleep(0.3)
    try:
        ws.close()
    except Exception:
        pass


def meta(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        d = json.loads(base64.urlsafe_b64decode(p))
        return d.get("exp")
    except Exception:
        return None


def try_login(code, mp_id):
    body = urllib.parse.urlencode({"code": code, "mpid": mp_id}).encode()
    req = urllib.request.Request(LOGIN_URL, data=body, method="POST", headers={
        "Content-Type": "application/x-www-form-urlencoded",
        "apiCaller": "wxxcx",
        "X-Requested-With": "XMLHttpRequest",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
                      "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                      "MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/25715",
    })
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            return json.loads(r.read().decode())
    except Exception as e:
        return {"status": -1, "message": str(e)}


def load_env():
    env = {}
    if os.path.exists(ENVFILE):
        for line in open(ENVFILE, encoding="utf-8"):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                env[k] = v
    return env


def mask(v):
    s = str(v)
    return f"{s[:4]}{'*' * max(0, len(s) - 8)}{s[-4:]} ({len(s)})" if len(s) > 8 else "*" * len(s)


def main():
    env = load_env()
    target_open = env.get("LAKEKE_OPENID", "")

    # 现存的 token 还有效就先不登录（小程序也是这个策略：token 没过期就复用）
    if not (len(sys.argv) > 2 and sys.argv[2] == "force"):
        token = env.get("LAKEKE_TOKEN", "")
        exp = meta(token) if token else None
        if exp and exp - time.time() > 120:
            left = (exp - time.time()) / 60
            print(f"[refresh] 现有 token 仍有效（还剩 {left:.0f} 分钟），跳过登录", flush=True)
            return

    print(f"[refresh] 等待 {WAIT}s；目标 openId={mask(target_open) if target_open else '(未指定)'}", flush=True)

    end = time.time() + WAIT
    got = None
    while time.time() < end and not got:
        collect()
        pairs = [(c, state["ident"].get(c, {}), state["code"].get(c, {})) for c in state["ctx"]]
        for cid, ident, codeinfo in pairs:
            if not codeinfo.get("ok"):
                continue
            app_id = ident.get("appId")
            # 只认辣可可小程序的上下文（甄选是同一个 SaaS 的另一个租户）
            if app_id and app_id != APPID:
                print(f"[try] ctx {cid}: appId={app_id} 跳过（不是辣可可）", flush=True)
                continue
            mp = ident.get("mpId") or env.get("LAKEKE_MPID", "")
            print(f"[try] ctx {cid}: appId={app_id} mpId={mask(mp)} openId={mask(ident.get('openId', ''))}", flush=True)
            if target_open and ident.get("openId") and ident["openId"] != target_open:
                print("      跳过（不是目标账号）", flush=True)
                continue
            if not mp:
                print("      跳过（拿不到 mpId）", flush=True)
                continue
            resp = try_login(codeinfo["code"], mp)
            status = resp.get("status")
            ok = status == 0 and isinstance(resp.get("result"), dict)
            print(f"      /auth/login status={status} {'' if ok else resp.get('message')}", flush=True)
            if ok:
                got = (ident, resp["result"])
                break
        if not got:
            time.sleep(3)

    if not got:
        print("[FAIL] 未能换到 token：确认目标账号的辣可可小程序是开着的", flush=True)
        sys.exit(1)

    ident, result = got
    token = result.get("token", "")
    exp = meta(token)
    if exp:
        left = (exp * 1000 - time.time() * 1000) / 60000
        print(f"[refresh] 新 token len={len(token)} exp="
              f"{datetime.datetime.fromtimestamp(exp):%Y-%m-%d %H:%M:%S}（{left:.0f} 分钟后）", flush=True)

    # 只更新 token；身份沿用 storage（响应里的 openId 可能是快照用户）
    env["LAKEKE_TOKEN"] = token
    for k, v in (("LAKEKE_MPID", ident.get("mpId")), ("LAKEKE_OPENID", ident.get("openId")),
                 ("LAKEKE_UNIONID", ident.get("unionId")), ("LAKEKE_GCID", ident.get("gcId"))):
        if v:
            env[k] = str(v)
    with open(ENVFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(f"{k}={v}" for k, v in env.items() if v) + "\n")
    print(f"[save] 已更新 {ENVFILE}", flush=True)


if __name__ == "__main__":
    main()
