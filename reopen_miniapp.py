#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在云微微信实例容器内运行：辣可可小程序被关掉时，自动把它重新打开。

两条路径（先试哪条由当前屏幕决定）：

  A. 当前是「辣可可甄选」首页（中段一大片红色 banner）
     → 点「每日积分签到」轮播图 → 弹「即将打开 辣可可现炒黄牛肉」→ 点允许

  B. 当前是微信主窗口（聊天列表 / 空白页）
     → 点搜索框 → 输入「辣可可甄选」→ 点下拉里「最近使用过的小程序」第一条
     → 落到甄选首页后接着走 A

识别都用像素判据，不依赖 OCR：
  · 红色 banner：画面中段 r>175 且 g,b<130 的占比
  · 绿色确认按钮：微信绿（主绿 7,193,96；隐私协议那颗偏青 102,196,170）
  · 小程序行：下拉区域里的一小块**高饱和彩色 logo**（文字行只有灰色放大镜图标）
所有坐标按屏幕尺寸取比例，来自 1280x1024 实测。任一步判断不了就**不点**、存截图、返回非 0。

用法（容器内）：python3 reopen_miniapp.py
退出码：0 已重开；3 既不是甄选首页、也没找到小程序行；4 点了但没等到该出现的弹窗
"""
import os
import subprocess
import sys
import time

DISPLAY = os.environ.get("DISPLAY", ":1")
SHOT_DIR = os.environ.get("SHOT_DIR", "/tmp/shots")
WANT_W, WANT_H = 1280, 1024

# 主窗口路径的比例坐标（1280x1024 实测：搜索框中心 ≈ (161,56)，第一条小程序 ≈ (162,135)）
R_SEARCH_BOX = (0.126, 0.055)
R_LOGO_AREA = (0.03, 0.45, 0.095, 0.26)    # x0f, x1f, y0f, y1f：下拉区域（要避开搜索框本身）
R_ROW_CLICK_X = 0.16                        # 行内点哪儿都行，取文字区
R_BANNER = (0.496, 0.517)                   # 甄选首页签到 banner 中心


def run(cmd):
    return subprocess.run(cmd, shell=True, capture_output=True, text=True).stdout


def size():
    out = run("DISPLAY=%s xdotool getdisplaygeometry" % DISPLAY).strip().split()
    return int(out[0]), int(out[1])


def grab(W, H):
    d = subprocess.run("DISPLAY=%s ffmpeg -loglevel error -f x11grab -video_size %dx%d -i %s "
                       "-frames:v 1 -f rawvideo -pix_fmt rgb24 -" % (DISPLAY, W, H, DISPLAY),
                       shell=True, capture_output=True).stdout
    if len(d) < W * H * 3:
        raise RuntimeError("截屏失败（%d 字节）" % len(d))
    return d


def png(W, H, name):
    os.makedirs(SHOT_DIR, exist_ok=True)
    p = os.path.join(SHOT_DIR, name)
    run("DISPLAY=%s ffmpeg -loglevel error -y -f x11grab -video_size %dx%d -i %s -frames:v 1 %s"
        % (DISPLAY, W, H, DISPLAY, p))
    return p


def click(x, y, wait=0.45):
    run("DISPLAY=%s xdotool mousemove %d %d; sleep %s; DISPLAY=%s xdotool click 1"
        % (DISPLAY, x, y, wait, DISPLAY))


def type_text(s):
    run('DISPLAY=%s xdotool type --delay 110 "%s"' % (DISPLAY, s))


def px(buf, W, x, y):
    i = (y * W + x) * 3
    return buf[i], buf[i + 1], buf[i + 2]


def red_ratio(buf, W, H):
    """画面中段被红色 banner 占的比重（甄选首页特征）"""
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
    """微信绿按钮的 bbox"""
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


def find_logo_row(buf, W, H):
    """下拉里「最近使用过的小程序」那一行的 y：找一块高饱和彩色 logo，按 y 分带取最上面那条"""
    x0, x1 = int(W * R_LOGO_AREA[0]), int(W * R_LOGO_AREA[1])
    y0, y1 = int(H * R_LOGO_AREA[2]), int(H * R_LOGO_AREA[3])
    hits = {}
    for y in range(y0, y1):
        base = y * W * 3
        n = 0
        for x in range(x0, x1, 2):
            i = base + x * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            if max(r, g, b) - min(r, g, b) > 60 and max(r, g, b) > 90:   # 高饱和、非灰
                n += 1
        if n >= 3:
            hits[y] = n
    if not hits:
        return None
    ys = sorted(hits)
    # 取第一条连续的带（允许 6px 间隙）
    band = [ys[0]]
    for y in ys[1:]:
        if y - band[-1] <= 6:
            band.append(y)
        else:
            break
    if len(band) < 8:          # logo 有 ~24px 高，太薄的多半是图标/分隔线
        return None
    return (band[0] + band[-1]) // 2


def do_jump_from_zx_home(W, H):
    """甄选首页：点签到 banner，等跳转弹窗，点允许。
    页面刚加载完时点下去可能没反应，所以换几个横向落点重试几次。"""
    # (0.191, 0.806) 是横幅左下角「点击签到」那个热区，实测最稳；其余是兜底落点
    spots = [(0.191, 0.806), (0.50, 0.517), (0.25, 0.517)]
    for i, (fx, fy) in enumerate(spots, 1):
        x, y = int(W * fx), int(H * fy)
        print(f"[reopen] 第{i}次点签到 banner ({x},{y})")
        click(x, y)
        for _ in range(3):                       # 每次点完最多等 6s
            time.sleep(2)
            g = find_green(grab(W, H), W, H)
            if g:
                gx, gy = (g[0] + g[2]) // 2, (g[1] + g[3]) // 2
                print(f"[reopen] 点「允许」({gx},{gy})")
                click(gx, gy)
                time.sleep(8)
                png(W, H, "reopen_done.png")
                return True
    p = png(W, H, "reopen_nodialog.png")
    print(f"[reopen] 三次都没等到跳转弹窗 → 截图 {p}")
    return False


def do_open_from_main_window(W, H):
    """微信主窗口：搜索 → 点最近使用的小程序第一条。成功返回 True"""
    sx, sy = int(W * R_SEARCH_BOX[0]), int(H * R_SEARCH_BOX[1])
    print(f"[reopen] 点搜索框 ({sx},{sy}) 并输入「辣可可甄选」")
    click(sx, sy)
    time.sleep(1.2)
    run("DISPLAY=%s xdotool key ctrl+a; sleep 0.2; DISPLAY=%s xdotool key Delete" % (DISPLAY, DISPLAY))
    time.sleep(0.4)
    type_text("辣可可甄选")
    time.sleep(4)
    buf = grab(W, H)
    png(W, H, "reopen_search.png")
    ry = find_logo_row(buf, W, H)
    if not ry:
        print("[reopen] 下拉里没找到小程序行（可能不在「最近使用过的小程序」里）")
        return False
    rx = int(W * R_ROW_CLICK_X)
    print(f"[reopen] 点最近使用的小程序 ({rx},{ry})")
    click(rx, ry)
    time.sleep(8)
    png(W, H, "reopen_after_row.png")
    return True


def main():
    W, H = size()
    if (W, H) != (WANT_W, WANT_H):
        print(f"[reopen] 屏幕 {W}x{H}，切到 {WANT_W}x{WANT_H}（坐标按此校准）")
        run("DISPLAY=%s xrandr -s %dx%d" % (DISPLAY, WANT_W, WANT_H))
        time.sleep(2)
        W, H = size()

    buf = grab(W, H)
    red = red_ratio(buf, W, H)
    print(f"[reopen] 中段红色占比 {red:.2f}")

    if red >= 0.35:
        print("[reopen] 判定：辣可可甄选首页")
        ok = do_jump_from_zx_home(W, H)
        sys.exit(0 if ok else 4)

    print("[reopen] 判定：不是甄选首页（当作微信主窗口处理）")
    if not do_open_from_main_window(W, H):
        p = png(W, H, "reopen_fail.png")
        print(f"[reopen] 没能打开甄选 → 截图 {p}（需人工打开一次辣可可甄选）")
        sys.exit(3)

    # 打开甄选后接着点 banner
    buf = grab(W, H)
    if red_ratio(buf, W, H) < 0.35:
        p = png(W, H, "reopen_notzx.png")
        print(f"[reopen] 点完那行后没看到甄选首页 → 截图 {p}")
        sys.exit(3)
    ok = do_jump_from_zx_home(W, H)
    sys.exit(0 if ok else 4)


if __name__ == "__main__":
    main()
