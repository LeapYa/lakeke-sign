# -*- coding: utf-8 -*-
"""
过期校验探针：用一个「已过 exp」的 token 打接口，判断服务端是否真的校验 JWT 过期。

用法：python expiry_probe.py <env 文件>
只打印接口返回的 code/msg，不打印凭证。
"""
import base64
import datetime
import json
import os
import ssl
import sys
import time
import urllib.error
import urllib.request

CRM = "https://scrm.wuuxiang.com/crm7game-api"
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def load_env(path):
    env = {}
    for line in open(path, encoding="utf-8"):
        if "=" in line:
            k, v = line.strip().split("=", 1)
            env[k] = v
    return env


def exp_of(token):
    try:
        p = token.split(".")[1]
        p += "=" * (-len(p) % 4)
        return json.loads(base64.urlsafe_b64decode(p)).get("exp")
    except Exception:
        return None


def post(env, path, data):
    body = {"mpId": env.get("LAKEKE_MPID", ""), "openId": env.get("LAKEKE_OPENID", ""),
            "unionId": env.get("LAKEKE_UNIONID", ""), "data": data}
    h = {"Content-Type": "application/json", "Authorization": env.get("LAKEKE_TOKEN", ""),
         "crm7-mpId": env.get("LAKEKE_MPID", ""),
         "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/132.0.0.0 Safari/537.36 "
                       "MicroMessenger/7.0.20.1781 NetType/WIFI MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/25715"}
    if env.get("LAKEKE_GCID"):
        h["csl-GC-Shardingkey"] = env["LAKEKE_GCID"]
    req = urllib.request.Request(CRM + path, data=json.dumps(body).encode(), headers=h, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        return {"code": str(e.code), "msg": "http err"}
    except Exception as e:
        return {"code": "-1", "msg": str(e)}


def main():
    path = sys.argv[1]
    env = load_env(path)
    exp = exp_of(env.get("LAKEKE_TOKEN", ""))
    now = time.time()
    if exp:
        print(f"[probe] token exp = {datetime.datetime.fromtimestamp(exp):%Y-%m-%d %H:%M:%S}"
              f"，现在 {datetime.datetime.fromtimestamp(now):%Y-%m-%d %H:%M:%S}"
              f"（已过期 {(now - exp) / 60:.0f} 分钟）", flush=True)
    r = post(env, "/api/game/sign/detail", {"gameId": env.get("LAKEKE_GAMEID", "")})
    print(f"[probe] detail → code={r.get('code')} msg={r.get('msg')}", flush=True)
    if str(r.get("code")) == "200":
        print("[结论] 服务端**不校验** exp → token 可长期复用，塔斯汀那套（塞 Secret + Actions）可行", flush=True)
    else:
        print("[结论] 服务端**校验** exp → 必须每次现取 token，只能本机跑", flush=True)


if __name__ == "__main__":
    main()
