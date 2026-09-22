# -*- coding: utf-8 -*-
"""
辣可可签到一键跑（Windows 本机）

因为 token 是短效的（JWT，约 20 分钟），签到必须在拿到 token 后立刻执行，
所以推荐用法就是本机一键：取参 → 签到。可用 Windows 计划任务每天触发。

前置：
  1. WMPFDebugger 已启动（`[frida] script loaded` 后）
  2. 打开辣可可小程序「可可会员签到」页（hook 之后新打开的才会被抓到）

用法：
  python sign_now.py
"""
import os
import subprocess
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
PY = sys.executable


def run(name):
    print(f"\n===== {name} =====", flush=True)
    r = subprocess.run([PY, "-u", os.path.join(BASE, name)], cwd=BASE)
    return r.returncode


def main():
    code = run("cdp_get_params.py")
    if code != 0:
        print("\n[FAIL] 取参失败：确认 WMPFDebugger 已启动、辣可可小程序是在 hook 之后重新打开的")
        sys.exit(1)
    code = run("lakeke_run.py")
    sys.exit(code)


if __name__ == "__main__":
    main()
