# -*- coding: utf-8 -*-
"""
辣可可签到一键跑（Windows 本机）

推荐入口。流程：
  1. auth_refresh.py —— 在小程序里调 wx.login() 换一个新 token（token 只有 1~2 小时）
  2. lakeke_run.py   —— 用 token + 常量参数调签到接口

只需要微信在跑 + 辣可可小程序开着（**任意页面都行，不必进签到页**），
签到所需的 gameId 是长活动常量，memberId/cardId/cardNo 缺失时会自动从接口补。

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
    return subprocess.run([PY, "-u", os.path.join(BASE, name)], cwd=BASE).returncode


def main():
    # 先刷新 token（失败则退回用现存的，可能还有效）
    if run("auth_refresh.py") != 0:
        print("\n[WARN] token 刷新失败，尝试用手头现存的 token 继续")
    code = run("lakeke_run.py")
    if code != 0:
        print("\n[FAIL] 签到未成功。排查顺序：")
        print("  1. WMPFDebugger 是否在跑（端口 62000）")
        print("  2. 辣可可小程序是否是在 hook 启动之后打开的")
        print("  3. 先手动进一次辣可可小程序再试")
    sys.exit(code)


if __name__ == "__main__":
    main()
