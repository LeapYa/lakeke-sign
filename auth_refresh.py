# -*- coding: utf-8 -*-
"""
主动刷新凭证：在小程序逻辑层调 wx.login() 拿 jsCode → POST /auth/login 换新 token → 写 lakeke.env。

只要微信在跑、辣可可小程序开着，就能随时拿到新鲜 token，不必等人手工抓取。
全程不打印明文凭证，只打印长度 / exp 等元信息。

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
import urllib.parse
import urllib.request
import urllib.error
import websocket

BASE = os.path.dirname(os.path.abspath(__file__))
ENVFILE = os.path.join(BASE, "lakeke.env")
LOGIN_URL = "https://wechat.wuuxiang.com/i5xforyou/auth/login"
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

WAIT = int(sys.argv[1]) if len(sys.argv) > 1 else 60

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

# openId/unionId/mpId 即便 token 过期也还在 storage 里
IDENT_JS = r"""
(function () {
  var out = {};
  function scan(o, d) {
    if (!o || typeof o !== 'object' || d > 3) return;
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
  return JSON.stringify(out);
})()
"""

collected = {}


def send(ws, cid, expr, tag, await_promise=False):
    mid = 1000 * (tag + 1) + cid
    params = {"expression": expr, "returnByValue": True, "contextId": cid}
    if await_promise:
        params["awaitPromise"] = True
    try:
        ws.send(json.dumps({"id": mid, "method": "Runtime.evaluate", "params": params}))
    except Exception:
        pass


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
    if not isinstance(mid, int):
        return
    tag, cid = mid // 1000 - 1, mid % 1000
    val = msg.get("result", {}).get("result", {}).get("value")
    if tag == 0 and val == "object":
        send(ws, cid, IDENT_JS, 1)
        send(ws, cid, LOGIN_JS, 2, await_promise=True)
    elif tag == 1 and val:
        try:
            collected.setdefault("ident", {}).update(json.loads(val))
        except Exception:
            pass
    elif tag == 2 and val:
        try:
            collected["login"] = json.loads(val)
        except Exception:
            collected["login"] = {"raw": val[:80]}


def once(seconds=8):
    ws = websocket.WebSocketApp("ws://127.0.0.1:62000", on_open=on_open, on_message=on_message,
                                on_error=lambda w, e: None)
    t = threading.Thread(target=ws.run_forever, daemon=True)
    t.start()
    time.sleep(2)
    for cid in range(1, 40):
        send(ws, cid, "typeof wx", 0)
        time.sleep(0.1)
    end = time.time() + seconds
    while time.time() < end and not collected.get("login"):
        time.sleep(0.5)
    try:
        ws.close()
    except Exception:
        pass


def meta(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        d = json.loads(base64.urlsafe_b64decode(p))
        exp = d.get("exp")
        return {"len": len(token), "fields": list(d.keys()), "exp": exp}
    except Exception:
        return {"len": len(token), "fields": None, "exp": None}


def main():
    print(f"[refresh] 等待 {WAIT}s 连接小程序 ...", flush=True)
    end = time.time() + WAIT
    while time.time() < end and not collected.get("login"):
        once()
        time.sleep(2)

    ident = collected.get("ident", {})
    login = collected.get("login", {})
    print(f"[refresh] storage 身份: mpId={'有' if ident.get('mpId') else '无'} "
          f"openId={'有' if ident.get('openId') else '无'}", flush=True)
    if not login.get("ok"):
        print(f"[FAIL] wx.login 失败: {login.get('err') or login}")
        sys.exit(1)

    code = login["code"]
    print(f"[refresh] 拿到 jsCode（长度 {len(code)}，不打印）", flush=True)
    mp_id = ident.get("mpId", "")
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
            resp = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") if e.fp else ""
        print(f"[FAIL] /auth/login HTTP {e.code}: {raw[:200]}")
        sys.exit(1)
    except Exception as e:
        print(f"[FAIL] /auth/login 异常 {e}")
        sys.exit(1)

    print(f"[refresh] /auth/login status={resp.get('status')} message={resp.get('message')}", flush=True)
    result = resp.get("result")
    print(f"[refresh] result 类型={type(result).__name__} "
          f"字段={list(result.keys()) if isinstance(result, dict) else result}", flush=True)

    # 递归找 token / openId / unionId / mpId
    picked = {}

    def grab(o, d=0):
        if not isinstance(o, (dict, list)) or d > 4:
            return
        items = o.items() if isinstance(o, dict) else enumerate(o)
        for k, v in items:
            lk = str(k).lower()
            if isinstance(v, str) and v:
                if lk in ("token", "authorization", "accesstoken") and "token" not in picked:
                    picked["token"] = v
                if lk in ("openid",) and "openId" not in picked:
                    picked["openId"] = v
                if lk in ("unionid",) and "unionId" not in picked:
                    picked["unionId"] = v
                if lk in ("mpid", "mp_id") and "mpId" not in picked:
                    picked["mpId"] = v
                if lk in ("gcid",) and "gcId" not in picked:
                    picked["gcId"] = v
            else:
                grab(v, d + 1)

    grab(resp)
    token = picked.get("token", "")
    if not token:
        print("[FAIL] 响应里没有 token")
        sys.exit(1)
    m = meta(token)
    exp = m["exp"]
    if exp:
        left = (exp * 1000 - time.time() * 1000) / 60000
        exp_str = datetime.datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M:%S")
        print(f"[refresh] 新 token len={m['len']} fields={m['fields']} exp={exp_str}（{left:.0f} 分钟后）", flush=True)
    else:
        print(f"[refresh] 新 token len={m['len']}（非 JWT 或无 exp）", flush=True)

    env = {}
    if os.path.exists(ENVFILE):
        for line in open(ENVFILE, encoding="utf-8"):
            if "=" in line:
                k, v = line.strip().split("=", 1)
                env[k] = v
    # 只更新 token；身份信息一律沿用 storage（/auth/login 可能带回快照用户的 openId，
    # 用它去签到会报 105 memberId与openId不一致）
    env["LAKEKE_TOKEN"] = token
    for k, v in (("LAKEKE_MPID", mp_id), ("LAKEKE_OPENID", ident.get("openId")),
                 ("LAKEKE_UNIONID", ident.get("unionId")), ("LAKEKE_GCID", ident.get("gcId"))):
        if v:
            env[k] = v
    with open(ENVFILE, "w", encoding="utf-8") as f:
        f.write("\n".join(f"{k}={v}" for k, v in env.items() if v) + "\n")
    print(f"[save] 已更新 {ENVFILE}（字段：{sorted(env)}）", flush=True)


if __name__ == "__main__":
    main()
