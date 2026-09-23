# -*- coding: utf-8 -*-
"""
打印当前账号的会员摘要（脱敏），供通知正文使用。
用法：python member_info.py            # 例：积分 1 · memberId 329***245 · 卡 125***655
      python member_info.py --json     # 原样 JSON（含字段名，不含 token）
"""
import importlib.util
import json
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("lr", os.path.join(BASE, "lakeke_run.py"))
lr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lr)


def mask(v):
    s = str(v)
    return f"{s[:3]}***{s[-3:]}" if len(s) > 8 else s


def main():
    env = lr.load_env(os.path.join(BASE, "lakeke.env"))
    r = lr.api_post(env, "/api/member/single", {
        "gameId": env.get("LAKEKE_GAMEID", ""),
        "gameType": 2,
        "thirdShopId": env.get("LAKEKE_THIRDSTHOPID", ""),
    })
    c = r.get("content")
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except json.JSONDecodeError:
            c = None
    if not isinstance(c, dict):
        print(f"会员信息查询失败 code={r.get('code')} msg={r.get('msg')}")
        sys.exit(1)
    if "--json" in sys.argv:
        print(json.dumps({k: c.get(k) for k in ("id", "cardId", "cardNo", "score", "name", "cardTypeName")},
                         ensure_ascii=False))
        return
    parts = []
    if c.get("score") is not None:
        parts.append(f"积分 {c['score']}")
    if c.get("id"):
        parts.append(f"memberId {mask(c['id'])}")
    if c.get("cardNo"):
        parts.append(f"卡 {mask(c['cardNo'])}")
    if c.get("cardTypeName"):
        parts.append(str(c["cardTypeName"]))
    print(" · ".join(parts))


if __name__ == "__main__":
    main()
