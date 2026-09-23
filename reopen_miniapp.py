#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在云微微信实例容器内运行：当辣可可小程序被关掉时，自动把它重新打开。

已校准路径（屏幕 1280x1024，实测通过）：
  辣可可甄选首页 → 点「每日积分签到」大轮播图（中线偏下）
      → 弹「即将打开「辣可可现炒黄牛肉」小程序」→ 点「允许」
      → 落到 辣可可 pages/sign/index
安全护栏：只有确认当前画面是甄选首页那张**红色大 banner** 才点，避免在别处乱点。
自己开不了就存截图并返回非 0 —— 不瞎试。

用法（容器内）：python3 reopen_miniapp.py
退出码：0 已重开；3 没找到可点的 banner；4 点了但没等到跳转弹窗
"""
import os
import subprocess
import sys
import time

DISPLAY = os.environ.get("DISPLAY", ":1")
SHOT_DIR = os.environ.get("SHOT_DIR", "/tmp/shots")
WANT_W, WANT_H = 1280, 1024


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def size():
    out = run("DISPLAY=%s xdotool getdisplaygeometry" % DISPLAY).strip().split()
    return int(out[0]), int(out[1])


def grab(W, H):
    d = subprocess.run("DISPLAY=%s ffmpeg -loglevel error -f x11grab -video_size %dx%d -i %s "
                       "-frames:v 1 -f rawvideo -pix_fmt rgb24 -" % (DISPLAY, W, H, DISPLAY),
                       shell=True, capture_output=True).stdout
    return d


def png(W, H, name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    p = os.path.join(SHOT_DIR, name)
    run("DISPLAY=%s ffmpeg -loglevel error -y -f x11grab -video_size %dx%d -i %s -frames:v 1 %s"
        % (DISPLAY, W, H, DISPLAY, p))
    return p


def click(x, y):
    run("DISPLAY=%s xdotool mousemove %d %d; sleep 0.4; DISPLAY=%s xdotool click 1" % (DISPLAY, x, y, DISPLAY))


def ratio_red_banner(buf, W, H):
    """画面中段是不是被红色 banner 占着（甄选首页特征）"""
    hit = tot = 0
    for y in range(int(H * 0.25), int(H * 0.75), 6):
        base = y * W * 3
        for x in range(int(W * 0.05), int(W * 0.95), 6):
            i = base + x * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            tot += 1
            if r > 175 and g < 130 and b < 130:
                hit += 1
    return hit / max(1, tot)


def find_green(buf, W, H):
    ys = {}
    for y in range(0, H, 2):
        base = y * W * 3
        n = 0
        for x in range(0, W, 2):
            i = base + x * 3
            c = (buf[i], buf[i + 1], buf[i + 2])
            if c[1] >= 140 and c[1] - c[0] >= 40 and c[1] - c[2] >= 15:
                n += 1
        if n > 3:
            ys[y] = n
    if not ys:
        return None
    peak = max(ys, key=ys.get)
    band = [y for y in ys if abs(y - peak) <= 40]
    y0, y1 = min(band), max(band)
    xs = []
    for y in range(y0, y1 + 1, 2):
        base = y * W * 3
        for x in range(0, W, 2):
            i = base + x * 3
            c = (buf[i], buf[i + 1], buf[i + 2])
            if c[1] >= 140 and c[1] - c[0] >= 40 and c[1] - c[2] >= 15:
                xs.append(x)
    return (min(xs), y0, max(xs), y1) if xs else None


def main():
    W, H = size()
    if (W, H) != (WANT_W, WANT_H):
        print(f"[reopen] 屏幕 {W}x{H}，切到 {WANT_W}x{WANT_H}（坐标按此校准）")
        run("DISPLAY=%s xrandr -s %dx%d" % (DISPLAY, WANT_W, WANT_H))
        time.sleep(2)
        W, H = size()

    buf = grab(W, H)
    red = ratio_red_banner(buf, W, H)
    print(f"[reopen] 中段红色占比 {red:.2f}")
    if red < 0.35:
        p = png(W, H, "reopen_nobanner.png")
        print(f"[reopen] 当前不是甄选首页（看不到红色签到 banner）→ 退出，截图 {p}")
        print("          需人工/agent 先把微信切到「辣可可甄选」首页")
        sys.exit(3)

    x, y = int(W * 0.496), int(H * 0.517)
    print(f"[reopen] 点签到 banner ({x},{y})")
    click(x, y)
    time.sleep(4)

    buf = grab(W, H)
    g = find_green(buf, W, H)
    if not g:
        p = png(W, H, "reopen_nodialog.png")
        print(f"[reopen] 没等到跳转弹窗 → 退出，截图 {p}")
        sys.exit(4)
    gx, gy = (g[0] + g[2]) // 2, (g[1] + g[3]) // 2
    print(f"[reopen] 点「允许」({gx},{gy})")
    click(gx, gy)
    time.sleep(8)
    png(W, H, "reopen_done.png")
    print("[reopen] 完成（跳转结果请用 CDP 复查 pages/sign/index）")


if __name__ == "__main__":
    main()
