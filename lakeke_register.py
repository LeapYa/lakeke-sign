# -*- coding: utf-8 -*-
"""
把账号变成辣可可会员（签到接口需要 memberId/cardId/cardNo，只有会员才有）。

两条路，默认**API 优先**：

  A. 纯 API（推荐，零 UI、零误判）
     页面源码里注册就是这个接口：
       POST /crm7game-api/api/member/register
       body {mpId, openId, unionId, data:{mobile, gameId, thirdShopId, byInviteCode}}
     其中 mobile 是**明文手机号**（加密串只在走微信弹窗授权时才需要）。
     → 只要设了 LAKEKE_REGISTER_PHONE，就走这条路，不点任何界面。

  B. UI 兜底（不想给手机号、或想让微信授权时用）
     点「立即签到」→（隐私协议）→ 授权说明 → 微信手机号授权弹窗 → 允许
     这一步是微信原生 UI，且**每个账号只出现一次**。选哪个号码由
       LAKEKE_REGISTER_PHONE_INDEX 决定（从 1 开始）；只有 1 个号码时不用设。
     由 ui_register.py 执行（截图存 shots/reg_*.png）。

环境变量（写在 lakeke.env）：
  LAKEKE_REGISTER_PHONE        手机号（11 位）。走 API 注册用它；走 UI 时若装了 tesseract 也用它匹配。
  LAKEKE_REGISTER_PHONE_INDEX  走 UI 时选第几个号码；只有 1 个号码不用设。
  LAKEKE_REGISTER_MODE         api / ui / auto（默认 auto：有手机号走 api，否则走 ui）

用法：python lakeke_register.py
"""
import importlib.util
import json
import os
import re
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
ENVFILE = os.path.join(BASE, "lakeke.env")
SHOT_LOCAL = os.path.join(os.path.dirname(BASE), "shots")
CONTAINER = os.environ.get("WOC_INSTANCE", "woc-wx-2ada0225ca")

spec = importlib.util.spec_from_file_location("lr", os.path.join(BASE, "lakeke_run.py"))
lr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lr)


def sh(cmd, timeout=900):
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
    return (p.stdout or "") + (p.stderr or "")


def member(env):
    r = lr.api_post(env, "/api/member/single", {
        "gameId": env.get("LAKEKE_GAMEID", ""),
        "gameType": 2,
        "thirdShopId": env.get("LAKEKE_THIRDSHOPID", ""),
    })
    c = r.get("content")
    if isinstance(c, str):
        try:
            c = json.loads(c)
        except json.JSONDecodeError:
            c = None
    return str(r.get("code")), r.get("msg"), c if isinstance(c, dict) else None


def show(info):
    for k in ("id", "cardId", "cardNo", "score", "name"):
        if info and info.get(k) is not None:
            v = info[k]
            if k in ("id", "cardId", "cardNo"):
                v = f"{str(v)[:3]}***{str(v)[-3:]}"
            print(f"       {k} = {v}")


def api_register(env, mobile):
    """纯 API 注册会员（照抄页面源码 registerVip 的入参）"""
    r = lr.api_post(env, "/api/member/register", {
        "mobile": mobile,
        "gameId": env.get("LAKEKE_GAMEID", ""),
        "thirdShopId": env.get("LAKEKE_THIRDSHOPID", ""),
        "byInviteCode": "",
    })
    return str(r.get("code")), r.get("msg")


def ui_register(env, idx, phone):
    """UI 兜底：调容器里的 ui_register.py"""
    geom = sh(f'docker exec {CONTAINER} sh -c "DISPLAY=:1 xdotool getdisplaygeometry"').strip()
    try:
        _, h = (int(x) for x in geom.split()[:2])
    except ValueError:
        h = 0
    if h and h < 900:
        print(f"[ui] 当前屏高 {h} 偏矮（弹窗按钮会被切掉），切到 1280x1024")
        sh(f'docker exec {CONTAINER} sh -c "DISPLAY=:1 xrandr -s 1280x1024"')
    sh(f'docker cp "{os.path.join(BASE, "ui_register.py")}" {CONTAINER}:/tmp/ui_register.py')
    args = []
    if idx:
        args += ["--index", str(idx)]
    if phone:
        args += ["--phone", phone]
    cmd = (f'docker exec -e DISPLAY=:1 -e SHOT_DIR=/tmp/shots '
           f'-e REG_PHONE_INDEX={idx or 0} -e REG_PHONE={phone} '
           f'{CONTAINER} sh -c "rm -rf /tmp/shots; python3 /tmp/ui_register.py {" ".join(args)}"')
    print(sh(cmd).strip())
    os.makedirs(SHOT_LOCAL, exist_ok=True)
    sh(f'docker cp {CONTAINER}:/tmp/shots/. "{SHOT_LOCAL}/"')
    print(f"[ui] 截图已存 {SHOT_LOCAL}/reg_*.png")


def main():
    if not os.path.exists(ENVFILE):
        print("[ERROR] 缺少 lakeke.env")
        sys.exit(1)
    env = lr.load_env(ENVFILE)

    code, msg, info = member(env)
    print(f"[check] /api/member/single → code={code} msg={msg}")
    if code == "200":
        print("[skip] 已经是会员，无需注册（LAKEKE_REGISTER_* 不参与）")
        show(info)
        return
    if code != "401":
        print("[ERROR] 非预期返回（208=token 失效 → 先跑 auth_refresh*；其它看 lakeke_run.py）")
        sys.exit(1)

    phone = env.get("LAKEKE_REGISTER_PHONE", "").strip()
    idx = env.get("LAKEKE_REGISTER_PHONE_INDEX", "").strip()
    mode = env.get("LAKEKE_REGISTER_MODE", "auto").strip().lower()
    if mode == "auto":
        mode = "api" if phone else "ui"
    print(f"[reg] 还不是会员 → 方式={mode} PHONE={'有' if phone else '(未设)'} INDEX={idx or '(未设)'}")

    if mode == "api":
        if not re.fullmatch(r"1\d{10}", phone or ""):
            print("[ERROR] 走 API 注册需要 LAKEKE_REGISTER_PHONE=11 位手机号")
            sys.exit(1)
        c, m = api_register(env, phone)
        print(f"[api] /api/member/register → code={c} msg={m}")
        if c not in ("200", "0"):
            print("[FAIL] API 注册未成功；可改 LAKEKE_REGISTER_MODE=ui 走微信弹窗授权（一次点击）")
            sys.exit(1)
    else:
        ui_register(env, int(idx) if idx.isdigit() else 0, phone)

    code, msg, info = member(env)
    print(f"[check] 复查 /api/member/single → code={code} msg={msg}")
    if code == "200":
        print("[done] 注册成功：")
        show(info)
        print("       注：走 UI 那条路注册完页面会自动签到一次；之后每天跑 lakeke_run.py 即可")
    else:
        print("[FAIL] 注册未完成")
        sys.exit(1)


if __name__ == "__main__":
    main()
