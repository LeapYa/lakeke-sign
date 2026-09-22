# -*- coding: utf-8 -*-
"""
只打印 token 的「元信息」（长度 / exp / 剩余分钟），不打印任何明文凭证。
用来判断辣可可到底用的是短效 token 还是长效 token。

用法：python check_token_exp.py [等待秒数]
"""
import datetime
import json
import sys
import time
import threading
import websocket

WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 180

JS = r"""
(function () {
  function meta(t) {
    t = String(t || '');
    var o = {len: t.length, kind: 'opaque'};
    var parts = t.split('.');
    if (parts.length === 3) {
      try {
        var p = parts[1];
        p += '='.repeat((4 - p.length % 4) % 4);
        var d = JSON.parse(atob(p.replace(/-/g, '+').replace(/_/g, '/')));
        o.kind = 'jwt';
        o.fields = Object.keys(d);
        o.exp = d.exp || null;
        o.iat = d.iat || null;
      } catch (e) { o.kind = 'jwt-undecodable'; }
    }
    return o;
  }
  var out = {now: Date.now()};
  try {
    var a = wx.getStorageSync('wxscAuth') || {};
    out.wxscAuth_token = meta(a.token);
    out.wxscAuth_exp = a.exp || null;
    out.wxscAuth_exceedTime = a.exceedTime || null;
  } catch (e) { out.e1 = e.message; }
  try { out.AuthorizationwxscAuth = meta(wx.getStorageSync('AuthorizationwxscAuth')); }
  catch (e) { out.e2 = e.message; }
  try {
    var ad = wx.getStorageSync('authDatawxscAuth') || {};
    out.authData_exp = ad.exp || null;
    out.authData_loginTime = ad.loginTime || null;
  } catch (e) {}
  try {
    var pages = getCurrentPages() || [];
    out.pages = pages.map(function (p) { return p.route || ''; });
  } catch (e) {}
  return JSON.stringify(out);
})()
"""

res = {}
pending = {}


def send(ws, cid, expr, tag):
    mid = 1000 * (tag + 1) + cid
    pending[mid] = (cid, tag)
    try:
        ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate",
                            "params": {"expression": expr, "returnByValue": True, "contextId": cid}}))
    except Exception:
        pending.pop(mid, None)


def once(seconds=9):
    """建一次连接，扫一遍上下文，返回结果（可能为空）"""
    res.clear()
    ws = websocket.WebSocketApp("ws://127.0.0.1:62000", on_open=on_open,
                                on_message=on_message, on_error=lambda w, e: None)
    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()
    time.sleep(2)
    for cid in range(1, 40):
        send(ws, cid, "typeof wx", 0)
        time.sleep(0.1)
    end = time.time() + seconds
    while time.time() < end and not res:
        time.sleep(0.5)
    try:
        ws.close()
    except Exception:
        pass
    return dict(res)


def on_open(ws):
    ws.send(json.dumps({"id": 1, "method": "Runtime.enable", "params": {}}))


def on_message(ws, data):
    try:
        msg = json.loads(data)
    except json.JSONDecodeError:
        return
    if msg.get("method") == "Runtime.executionContextCreated":
        cid = msg.get("params", {}).get("context", {}).get("id")
        send(ws, cid, "typeof wx", 0)
        return
    mid = msg.get("id")
    if mid in pending:
        cid, tag = pending.pop(mid)
        val = msg.get("result", {}).get("result", {}).get("value")
        if tag == 0 and val == "object":
            send(ws, cid, JS, 1)
        elif tag == 1 and val:
            res[cid] = val


def fmt_ms(ms):
    return datetime.datetime.fromtimestamp(ms / 1000).strftime("%Y-%m-%d %H:%M:%S") if ms else None


def fmt_s(s):
    return datetime.datetime.fromtimestamp(s).strftime("%Y-%m-%d %H:%M:%S") if s else None


def main():
    ws = websocket.WebSocketApp("ws://127.0.0.1:62000", on_open=on_open,
                                on_message=on_message, on_error=lambda w, e: print("[err]", e))
    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()
    print(f"[check] 等待 {WAIT}s —— 请打开辣可可小程序", flush=True)
    end = time.time() + WAIT
    got = {}
    while time.time() < end:
        got = once()
        if got:
            break
        time.sleep(3)
    res.update(got)

    if not res:
        print("[END] 没连上 AppService（小程序要在 hook 之后重新打开）")
        sys.exit(1)

    for cid, raw in res.items():
        d = json.loads(raw)
        now = d.get("now")
        print(f"\n===== ctx {cid}  页面={d.get('pages')} =====")
        print(f"  现在: {fmt_ms(now)}")
        for k in ("wxscAuth_token", "AuthorizationwxscAuth"):
            o = d.get(k)
            if not o:
                continue
            print(f"  {k}: len={o.get('len')} kind={o.get('kind')} fields={o.get('fields')}")
            if o.get("exp"):
                print(f"      exp = {fmt_s(o['exp'])}  ({(o['exp'] * 1000 - now) / 60000:.1f} 分钟后)")
            if o.get("iat"):
                print(f"      iat = {fmt_s(o['iat'])}")
        for k in ("wxscAuth_exp", "wxscAuth_exceedTime", "authData_exp", "authData_loginTime"):
            if d.get(k):
                v = d[k]
                ts = v if v > 1e12 else v * 1000
                print(f"  {k} = {fmt_ms(ts)}  ({(ts - now) / 60000:.1f} 分钟后)")


if __name__ == "__main__":
    main()
