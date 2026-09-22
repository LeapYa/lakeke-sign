# -*- coding: utf-8 -*-
"""
用 lakeke.env 里的凭证跑一次真实签到，只打印接口返回的 code/msg（不打印凭证）。

用法：python lakeke_run.py
"""
import json
import os
import ssl
import sys
import urllib.request
import urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
CRM = "https://scrm.wuuxiang.com/crm7game-api"
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE


def load_env(path):
    env = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def api_post(env, path, data):
    body = {"mpId": env.get("LAKEKE_MPID", ""),
            "openId": env.get("LAKEKE_OPENID", ""),
            "unionId": env.get("LAKEKE_UNIONID", ""),
            "data": data}
    headers = {
        "Content-Type": "application/json",
        "Authorization": env.get("LAKEKE_TOKEN", ""),
        "crm7-mpId": env.get("LAKEKE_MPID", ""),
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
                      "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                      "MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/25715",
    }
    if env.get("LAKEKE_GCID"):
        headers["csl-GC-Shardingkey"] = env["LAKEKE_GCID"]
    req = urllib.request.Request(CRM + path, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15, context=ctx) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace") if e.fp else ""
        return {"code": str(e.code), "msg": raw[:200]}
    except Exception as e:
        return {"code": "-1", "msg": str(e)}


def main():
    env_file = os.path.join(BASE, "lakeke.env")
    if not os.path.exists(env_file):
        print("[ERROR] 缺少 lakeke.env，先跑 cdp_get_params.py")
        sys.exit(1)
    env = load_env(env_file)

    game_id = env.get("LAKEKE_GAMEID", "")

    # 会员三件套缺失时，用 /api/member/single 自动补全（不必进签到页）
    if not (env.get("LAKEKE_MEMBERID") and env.get("LAKEKE_CARDID")):
        print("[0/2] 补全会员信息（/api/member/single）...")
        single = api_post(env, "/api/member/single", {})
        content = single.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = None
        if isinstance(content, dict):
            env["LAKEKE_MEMBERID"] = content.get("id", "") or env.get("LAKEKE_MEMBERID", "")
            env["LAKEKE_CARDID"] = content.get("cardId", "") or env.get("LAKEKE_CARDID", "")
            env["LAKEKE_CARDNO"] = content.get("cardNo", "") or env.get("LAKEKE_CARDNO", "")
            with open(env_file, "w", encoding="utf-8") as f:
                f.write("\n".join(f"{k}={v}" for k, v in env.items() if v) + "\n")
            print(f"      会员信息已补全: memberId={'有' if env.get('LAKEKE_MEMBERID') else '无'} "
                  f"cardId={'有' if env.get('LAKEKE_CARDID') else '无'}")

    print("[1/2] 查询签到详情 ...")
    detail = api_post(env, "/api/game/sign/detail", {"gameId": game_id})
    code = str(detail.get("code"))
    print(f"      code={code} msg={detail.get('msg')}")
    if code == "208":
        print("[ERROR] 授权码错误 → token 失效，需重跑 cdp_get_params.py")
        sys.exit(1)
    if code != "200":
        print("[ERROR] 详情查询失败")
        sys.exit(1)

    print("[2/2] 执行签到 ...")
    sign = api_post(env, "/api/game/sign/signIn", {
        "gameId": game_id,
        "memberId": env.get("LAKEKE_MEMBERID", ""),
        "cardId": env.get("LAKEKE_CARDID", ""),
        "cardNo": env.get("LAKEKE_CARDNO", ""),
        "from": "",
        "thirdShopId": env.get("LAKEKE_THIRDSHOPID", ""),
    })
    code = str(sign.get("code"))
    print(f"      code={code} msg={sign.get('msg')}")
    content = sign.get("content")
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            pass
    print(f"      content={json.dumps(content, ensure_ascii=False)[:300]}")
    print("\n[DONE]", "签到链路可用" if code == "200" else f"返回 {code}，需人工看 msg")


if __name__ == "__main__":
    main()
