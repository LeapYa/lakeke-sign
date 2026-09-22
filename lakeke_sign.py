# -*- coding: utf-8 -*-
"""
辣可可小程序每日自动签到（GitHub Actions 版骨架）

逆向来源（静态拆包 wxf8a17a14c0521576，详见 逆向笔记.md）：
  签到接口：POST https://scrm.wuuxiang.com/crm7game-api/api/game/sign/signIn
  包裹体：  {mpId, openId, unionId, data:{gameId, memberId, cardId, cardNo, from, thirdShopId}}
  请求头：  Authorization: <token>；crm7-mpId: <mpId>；csl-GC-Shardingkey: <gcId 可选>

环境变量（GitHub Secrets）：
  LAKEKE_AUTH_TOKEN / LAKEKE_MP_ID / LAKEKE_OPEN_ID / LAKEKE_UNION_ID
  LAKEKE_GAME_ID / LAKEKE_MEMBER_ID / LAKEKE_CARD_ID / LAKEKE_CARD_NO
  LAKEKE_THIRD_SHOP_ID（可选） / LAKEKE_SHARDING_KEY（可选）

注意：
  - 尚未经过真机验证（需要先用 get_token_lakeke.py 抓到真实参数后联调）。
  - wuuxiang.com 是否有 WAF 拦海外 IP 未知，先直连；若 Actions 上 403/405，
    再参照 tastin-sign 的 freeproxy 回退方案补代理层。
  - token 有效期未知：小程序里有 401 后重新 /auth/login（依赖 wx.login jsCode）的
    自动刷新逻辑，脚本环境无法复现，过期只能重新抓取（同塔斯汀的邮件提醒策略）。
"""

import json
import os
import ssl
import sys
import time
import urllib.request
import urllib.error

CRM_BASE = "https://scrm.wuuxiang.com/crm7game-api"

TOKEN = os.environ.get("LAKEKE_AUTH_TOKEN", "")
MP_ID = os.environ.get("LAKEKE_MP_ID", "")
OPEN_ID = os.environ.get("LAKEKE_OPEN_ID", "")
UNION_ID = os.environ.get("LAKEKE_UNION_ID", "")
GAME_ID = os.environ.get("LAKEKE_GAME_ID", "")
MEMBER_ID = os.environ.get("LAKEKE_MEMBER_ID", "")
CARD_ID = os.environ.get("LAKEKE_CARD_ID", "")
CARD_NO = os.environ.get("LAKEKE_CARD_NO", "")
THIRD_SHOP_ID = os.environ.get("LAKEKE_THIRD_SHOP_ID", "")
SHARDING_KEY = os.environ.get("LAKEKE_SHARDING_KEY", "")

_ssl_ctx = ssl.create_default_context()
_ssl_ctx.check_hostname = False
_ssl_ctx.verify_mode = ssl.CERT_NONE

REQUIRED = ["LAKEKE_AUTH_TOKEN", "LAKEKE_MP_ID", "LAKEKE_OPEN_ID",
            "LAKEKE_GAME_ID", "LAKEKE_MEMBER_ID"]


def build_headers():
    h = {
        "Content-Type": "application/json",
        "Authorization": TOKEN,
        "crm7-mpId": MP_ID,
        # 与小程序一致的 UA（抓包确认后再校准）
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                      "(KHTML, like Gecko) Chrome/132.0.0.0 Safari/537.36 "
                      "MicroMessenger/7.0.20.1781(0x6700143B) NetType/WIFI "
                      "MiniProgramEnv/Windows WindowsWechat/WMPF XWEB/20089",
    }
    if SHARDING_KEY:
        h["csl-GC-Shardingkey"] = SHARDING_KEY
    return h


def api_post(path: str, data: dict) -> dict:
    """辣可可 CRM 接口的包裹体格式：{mpId, openId, unionId, data: {...}}"""
    body = {"mpId": MP_ID, "openId": OPEN_ID, "unionId": UNION_ID, "data": data}
    req = urllib.request.Request(
        CRM_BASE + path, data=json.dumps(body).encode(),
        headers=build_headers(), method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15, context=_ssl_ctx) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        text = e.read().decode(errors="replace") if e.fp else ""
        return {"code": e.code, "msg": f"HTTP {e.code}: {text[:200]}"}
    except Exception as e:
        return {"code": -1, "msg": str(e)}


def main():
    missing = [k for k in REQUIRED if not os.environ.get(k)]
    if missing:
        print("[ERROR] 缺少环境变量:", ", ".join(missing))
        sys.exit(1)

    # 1. 查询签到活动详情（顺带验证 token 是否有效）
    #    已验证的响应约定：code 是字符串，"200"=成功，"208"=授权码错误（token 失效）
    detail = api_post("/api/game/sign/detail", {"gameId": GAME_ID})
    print("[detail]", json.dumps(detail, ensure_ascii=False)[:500])
    code = str(detail.get("code"))
    if code == "208":
        print("[ERROR] 授权码错误：token 已失效，需重新运行 get_token_lakeke.py 抓取")
        print("::error::辣可可 token 已过期，需要手动更新！")
        sys.exit(1)
    if code != "200":
        print(f"[ERROR] 查询签到详情失败: {detail.get('msg')}")
        sys.exit(1)

    # 2. 执行签到
    #    from 字段是场景来源标记，小程序里取 getSenceSource()，回放留空即可
    sign = api_post("/api/game/sign/signIn", {
        "gameId": GAME_ID,
        "memberId": MEMBER_ID,
        "cardId": CARD_ID,
        "cardNo": CARD_NO,
        "from": "",
        "thirdShopId": THIRD_SHOP_ID,
    })
    print("[signIn]", json.dumps(sign, ensure_ascii=False)[:800])

    code = str(sign.get("code"))
    # 已验证的响应码：200 成功 / 415 今日已签到 / 208 授权码错误 / 211 授权码失效
    if code in ("208", "211"):
        print(f"[ERROR] {sign.get('msg')}：token 已失效，需重新抓取")
        print("::error::辣可可 token 已过期，需要手动更新！")
        sys.exit(1)
    if code == "415":
        print(f"[done] 今日已签到：{sign.get('msg')}")
        return
    if code == "200":
        content = sign.get("content")
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                pass
        print(f"[done] 签到成功，奖励: {json.dumps(content, ensure_ascii=False)[:300]}")
        return
    print(f"[ERROR] 签到失败: {sign.get('msg')} (code={code})")
    print("::error::辣可可签到失败，请查看日志")
    sys.exit(1)


if __name__ == "__main__":
    main()
