#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
在云微微信实例容器内运行：把辣可可签到那个小程序打开（用于刷 token / 签到前准备）。

目标小程序是 **「辣可可现炒黄牛肉i」（带结尾的 i）**。搜索会返回两个同名号：
不带 `i` 的（扫码点餐）是餐饮/商城号；带 `i` 的才是签到这个（只有它显示 `积分 / NQ=卡号`）。
所以验证一律按**窗口标题精确等于**，不靠列表顺序、不靠图标长相。

主路径（**不依赖「最近使用过的小程序」**，新号/空白号同样成立）
  A. 打开小程序面板：侧边栏顶部那组最后一个按钮（面板已开着就只置顶）
  B. 面板右上角放大镜 → 输入关键词 → **按回车** → 面板里开出「关键词_搜索」结果页
  C. 在结果卡片里逐张点：卡片位置由像素定位（一行可能有 3 张，按列切）
       · 开出标题=目标的小程序窗口 → 成功
       · 开出别的窗口               → 点微信自己的关闭按钮（标题栏最右 ◎）关掉，继续下一张
  D. 每次点击前都**重新截图定位**（实测下拉/结果页的纵向布局会漂移几十像素）

备选/兜底
  E. 主窗口搜索框 → 输入 → 进「搜一搜」结果页 → 点结果行（这版微信上实测不通，仅作后备）
  F. 搜「辣可可甄选」→ 点下拉里的小程序行 → 甄选首页 → 点签到 banner → 点「允许」

其它要点
  · 开头先把分辨率钉到 1280x1024：KasmVNC 的桌面分辨率会跟随**观看者窗口大小**变化，
    不钉死的话同一套比例坐标在没人观看时会落到别处（这个坑踩过）
  · 点击一律用比例坐标，来自 1280x1024 实测
  · **绝不能 `xdotool windowclose` 关微信的窗口**：X 窗口没了但微信内部状态不复位，
    面板/小程序会再也打不开，只能重启微信。要关就点微信自己的按钮。
  · 判断不了就**不点**，存截图返回非 0

用法（容器内）：python3 reopen_miniapp.py [--check] [--close] [--loose]
  --close  关掉小程序与面板（释放内存；daily.sh 签到后会调它）
退出码：0 已打开（--close 时为已关闭）；3 没打开（截图在 /tmp/shots）；
        4 点过候选但无法用窗口标题确认 —— `--loose` 模式下如此返回，
        交给外层用 `cdp_eval.js --probe` 按 appId 复核。

判据分两层（这层专管「点哪里」，身份确认交给 appId）
  · 本脚本的**入口定位与点击**依赖具体界面布局（见上文路径 A–F），微信改版就要跟着改；
  · 「打开的是不是辣可可」这件事，最终以 **appId** 为准：
    `node cdp_eval.js --probe wxf8a17a14c0521576`（读 `wx.getAccountInfoSync()`），
    它与窗口形态无关 —— 小程序以后不再独立开窗也照样能确认。
    加 `--loose` 时本脚本在「点了但没等到目标窗口」的情况下返回 4 而不是 3，
    就是为了让外层走这条 appId 复核，别把「界面形态变了」误判成「打开失败」。
"""
import os
import re
import subprocess
import sys
import time

DISPLAY = os.environ.get("DISPLAY", ":1")
SHOT_DIR = os.environ.get("SHOT_DIR", "/tmp/shots")

# 宽松模式：点过候选卡片、但没能用窗口标题确认时，返回 4（而不是 3）让外层按 appId 复核。
# 用途：万一微信改成「小程序不独立开窗」（Windows 新版已经是窗口内右侧栏），
# 窗口标题这条判据会失效，但打开动作其实可能已经成功 —— 此时不该硬判失败。
LOOSE = "--loose" in sys.argv
TOUCHED = [False]        # 是否点过候选卡片（用单元素列表，省去到处 global 声明）
WANT_W, WANT_H = 1280, 1024

# 目标小程序：打开后窗口标题里会出现这个名字。
# ⚠️ 一定要带结尾的 `i`：搜索结果里有两个同名号 ——
#    `辣可可现炒黄牛肉`（扫码点餐，是**餐饮/商城**那个，首页是五常米海报）
#    `辣可可现炒黄牛肉i`（为顾客提供便捷的点餐服务，**只有它显示 积分/NQ=卡号**，
#     与 lakeke.env 的 LAKEKE_CARDNO 对得上）—— 签到要的是后者。
# 用子串匹配会两个都命中，所以这里按**窗口标题精确等于**来判。
TARGET = os.environ.get("LAKEKE_MINIAPP", "辣可可现炒黄牛肉i")
KEYWORD = os.environ.get("LAKEKE_KEYWORD", "辣可可现炒黄牛肉")
FALLBACK_KEYWORD = "辣可可甄选"

# 比例坐标（1280x1024 实测）
R_SEARCH_BOX = (0.111, 0.037)       # 主窗口左上角搜索框（备选路径 E 用）
SCAN_X = 0.28                       # 扫候选行时点行内名称文字区的横坐标

# ── 小程序面板路径（主路径）的比例坐标，1280x1024 实测 ──
R_RAIL_COL = (14, 52)               # 侧边栏图标列的像素范围（找按钮用）
R_PANEL_MAGNIFIER = (0.974, 0.0625)  # 面板右上角搜索（放大镜）
R_CLOSE_BTN = (0.978, 0.041)        # 自绘标题栏（小程序窗口）最右的关闭按钮 ◎
R_CLOSE_BTN_VARIANTS = [(0.978, 0.041), (0.978, 0.020)]   # 依次尝试：小程序窗口 / 面板窗口（标准标题栏）

# 兜底路径用到的比例坐标
R_SEARCH_BOX_OLD = (0.126, 0.055)
R_LOGO_AREA = (0.03, 0.45, 0.095, 0.26)    # x0f, x1f, y0f, y1f：下拉里的小程序 logo 区域
R_ROW_CLICK_X = 0.16
R_BANNER = (0.496, 0.517)


# ───────────────────────── 基础工具 ─────────────────────────

def run(cmd, timeout=25):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=timeout).stdout
    except Exception:
        return ""


def size():
    out = run("DISPLAY=%s xdotool getdisplaygeometry" % DISPLAY).strip().split()
    return (int(out[0]), int(out[1])) if len(out) == 2 else (1280, 1024)


def grab(W, H):
    """整个屏幕的原始 RGB 帧（纯标准库解析，容器里没有 numpy/PIL）"""
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


def click(x, y, wait=0.7):
    run("DISPLAY=%s xdotool mousemove %d %d; sleep 0.35; DISPLAY=%s xdotool click 1"
        % (DISPLAY, int(x), int(y), DISPLAY))
    time.sleep(wait)


def key(k, wait=0.6):
    run("DISPLAY=%s xdotool key %s" % (DISPLAY, k))
    time.sleep(wait)


def type_text(s):
    run('DISPLAY=%s xdotool type --delay 130 "%s"' % (DISPLAY, s))
    time.sleep(1.5)


def px(buf, W, x, y):
    i = (y * W + x) * 3
    return buf[i], buf[i + 1], buf[i + 2]


# ───────────────────── 窗口：查找 / 验证 / 清理 ─────────────────────

def windows():
    """可见窗口 [(id, 标题)]"""
    out = []
    for wid in run("DISPLAY=%s xdotool search --onlyvisible --name '.+' 2>/dev/null"
                   % DISPLAY).split():
        out.append((wid, run("DISPLAY=%s xdotool getwindowname %s 2>/dev/null"
                             % (DISPLAY, wid)).strip()))
    return out


def find_target_window():
    """目标小程序已经开着？（窗口标题就是小程序名，按**精确相等**匹配 ——
    同名号里 `辣可可现炒黄牛肉` 和 `辣可可现炒黄牛肉i` 是两个不同的小程序）"""
    for wid, title in windows():
        if title.strip() == TARGET:
            return wid, title
    return None, None


def close_window(wid):
    """关掉一个微信窗口（小程序窗口 / 面板窗口）。⚠️ 必须走微信**自己的**关闭按钮，
    不能用 `xdotool windowclose`：后者销毁了 X 窗口但微信内部状态不复位，
    之后这个小程序（面板则是整个面板）就再也点不开了，只能重启微信。
    `···` 菜单里没有「关闭小程序」，所以只能点标题栏最右那个按钮。
    两种标题栏位置不同，依次试：小程序窗口是自绘的（✕ 约 0.041H）、
    面板窗口是标准标题栏（✕ 约 0.020H）。"""
    run("DISPLAY=%s xdotool windowactivate %s" % (DISPLAY, wid))
    time.sleep(1.0)
    geo = run("DISPLAY=%s xdotool getwindowgeometry --shell %s" % (DISPLAY, wid))
    w = h = None
    for line in geo.splitlines():
        if line.startswith("WIDTH="):
            w = int(line.split("=")[1])
        elif line.startswith("HEIGHT="):
            h = int(line.split("=")[1])
    if not (w and h):
        return False
    for fx, fy in R_CLOSE_BTN_VARIANTS:
        run("DISPLAY=%s xdotool mousemove %d %d; sleep 0.5; DISPLAY=%s xdotool click 1"
            % (DISPLAY, int(w * fx), int(h * fy), DISPLAY))
        time.sleep(3.5)
        if str(wid) not in dict(windows()):
            print("[reopen] 已关闭 %s（点在 %.3fW, %.3fH 的关闭按钮）" % (wid, fx, fy))
            return True
    print("[reopen] ⚠️ 没关掉 %s（不硬杀，避免微信状态卡死）" % wid)
    return False


# ───────────────────────── 像素判据（兜底路径用） ─────────────────────────

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
    """下拉里小程序那一行的 y：找一块高饱和彩色 logo，取最上面那条连续带"""
    x0, x1 = int(W * R_LOGO_AREA[0]), int(W * R_LOGO_AREA[1])
    y0, y1 = int(H * R_LOGO_AREA[2]), int(H * R_LOGO_AREA[3])
    hits = {}
    for y in range(y0, y1):
        base = y * W * 3
        n = 0
        for x in range(x0, x1, 2):
            i = base + x * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            if max(r, g, b) - min(r, g, b) > 60 and max(r, g, b) > 90:
                n += 1
        if n >= 3:
            hits[y] = n
    if not hits:
        return None
    ys = sorted(hits)
    band = [ys[0]]
    for y in ys[1:]:
        if y - band[-1] <= 6:
            band.append(y)
        else:
            break
    if len(band) < 8:
        return None
    return (band[0] + band[-1]) // 2


# ───────────────── 侧边栏 / 小程序面板（主路径） ─────────────────

def find_rail_buttons(W, H):
    """侧边栏按钮的 y 中心：图标列里"与底色不同"的行聚成带。
    返回全部按钮中心（含顶部头像与底部两个固定图标），按 y 升序。"""
    x0, x1 = R_RAIL_COL
    buf = grab(W, H)

    # 底色取该列的中位数（逐通道），采样即可
    samples = [[], [], []]
    for y in range(0, H, 3):
        base = y * W * 3
        for x in range(x0, x1, 3):
            i = base + x * 3
            for c in range(3):
                samples[c].append(buf[i + c])
    bg = [sorted(s)[len(s) // 2] for s in samples]

    rows = []
    for y in range(0, H):
        base = y * W * 3
        n = 0
        for x in range(x0, x1):
            i = base + x * 3
            if (abs(buf[i] - bg[0]) + abs(buf[i + 1] - bg[1]) + abs(buf[i + 2] - bg[2])) > 55:
                n += 1
        if n >= 3:
            rows.append(y)

    bands, cur = [], []
    for y in rows:
        if cur and y - cur[-1] <= 5:
            cur.append(y)
        else:
            if cur:
                bands.append(cur)
            cur = [y]
    if cur:
        bands.append(cur)
    return [(b[0] + b[-1]) // 2 for b in bands if len(b) >= 8]


def open_panel(W, H):
    """把小程序面板调到最前；面板不存在时点侧边栏最后一个（顶部那组的）按钮开一个。

    ⚠️ 两个坑（都实测踩过）：
    ① 面板窗口**本来就开着**时，点侧边栏按钮只是置顶、不新建窗口
       → 判据必须是「面板窗口出现了」**或**「活动窗口不是主窗口」；
    ② **绝不能用 `xdotool windowclose` 去关面板窗口**：X 窗口没了，但微信内部
       “面板是否打开”的状态没复位，之后点半边栏按钮就变成“切换关闭”，
       **再也召不回来**（只能重启微信）。要关也走微信自己的关闭按钮。"""
    panel = find_panel_window()
    if panel:
        run("DISPLAY=%s xdotool windowactivate %s" % (DISPLAY, panel))
        time.sleep(2)
        print("[reopen] 面板窗口已存在，直接置顶")
        return True

    activate_main(W, H)
    buttons = find_rail_buttons(W, H)
    top = [y for y in buttons if y < H * 0.6]      # 顶部那组（排除底部固定的图标）
    if not top:
        print("[reopen] 侧边栏一个按钮都没找到")
        return False
    main_id = find_main_window()
    before = {wid for wid, _ in windows()}
    last = top[-1]
    print("[reopen] 点侧边栏最后一个按钮 y=%d" % last)
    click(int(W * 0.025), last)
    for _ in range(8):
        time.sleep(1.5)
        if find_panel_window():
            print("[reopen] 面板窗口已出现")
            time.sleep(3)
            return True
        act = run("DISPLAY=%s xdotool getactivewindow" % DISPLAY).strip()
        if act and main_id and act != str(main_id) and win_class(act) == "":
            print("[reopen] 面板已置顶（active=%s）" % act)
            time.sleep(2)
            return True
        del before
    print("[reopen] 点了没反应（这一版可能是「发现」浮层，需要在浮层里再点小程序）")
    return False


def panel_search_once(W, H):
    """在面板里：放大镜 → 输入 → **回车**（用户确认：回车就会进搜索页）→
    搜索结果页里逐张卡片点，用窗口标题验证；**开错了就关掉继续试下一张**。
    成功返回 True。"""
    mx, my = int(W * R_PANEL_MAGNIFIER[0]), int(H * R_PANEL_MAGNIFIER[1])
    click(mx, my, 1.5)
    type_text(KEYWORD)
    print("[reopen] 面板搜索框回车")
    key("Return", 6.0)                      # 面板搜索：回车进「关键词_搜索」结果页
    time.sleep(2)
    png(W, H, "reopen_panel_search.png")

    baseline = {wid for wid, _ in windows()}
    tried = []                               # 已经试过的卡片位置，避免重复点

    for attempt in (1, 2, 3, 4):
        buf = grab(W, H)                     # 每次重新定位：布局会随标签栏/滚动变化
        cards = find_cards(buf, W, H)
        print("[reopen] 第%d次定位：找到 %d 张卡片 %s" % (attempt, len(cards), cards))
        progress = False
        for cx, cy in cards:
            if any(abs(cx - px) < 30 and abs(cy - py) < 30 for px, py in tried):
                continue                     # 这张已经试过
            tried.append((cx, cy))
            progress = True
            print("[reopen] 点卡片 (%d,%d)" % (cx, cy))
            TOUCHED[0] = True
            click(cx, cy, 4.0)
            wid, title = find_target_window()
            if wid:
                print("[reopen] 打开成功：%s" % title)
                png(W, H, "reopen_done.png")
                return True
            wrong = [(w, t) for w, t in windows()
                     if w not in baseline and t.strip() != TARGET]
            for wid_, title_ in wrong:
                print("[reopen] 开错了（%s），关掉" % title_)
                if not close_window(wid_):
                    return False             # 关不掉说明状态异常，交给外层重来
                break                        # 关掉后重新截图定位再继续
        if not progress:
            break                            # 所有卡片都试过了
        time.sleep(3)
    return False


def find_cards(buf, W, H):
    """在搜索结果页里定位**所有**结果卡片：卡片左侧有一块方形 logo（彩色/深色）。
    返回可点中心 [(x, y)]，按阅读顺序（先上后左）。
    注意一**行里有多张卡**（实测一行 3 张），必须按列切开，不能只取最左那张。"""
    x0, x1 = int(W * 0.17), int(W * 0.75)      # 整行都扫，覆盖到第 2、3 列
    rows = {}
    for y in range(int(H * 0.08), int(H * 0.80)):
        base = y * W * 3
        n = 0
        for x in range(x0, x1, 2):
            i = base + x * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            if max(r, g, b) - min(r, g, b) > 45 or max(r, g, b) < 190:
                n += 1
        if n >= 4:
            rows[y] = n
    if not rows:
        return []
    ys = sorted(rows)
    bands, cur = [], [ys[0]]
    for y in ys[1:]:
        if y - cur[-1] <= 10:
            cur.append(y)
        else:
            bands.append(cur); cur = [y]
    bands.append(cur)

    out = []
    for band in bands:
        if len(band) < 24:                     # logo 方块约 55~70px
            continue
        yc = (band[0] + band[-1]) // 2
        xs = set()
        for y in band[::3]:
            base = y * W * 3
            for x in range(x0, x1, 2):
                i = base + x * 3
                r, g, b = buf[i], buf[i + 1], buf[i + 2]
                if max(r, g, b) - min(r, g, b) > 45 or max(r, g, b) < 190:
                    xs.add(x)
        if not xs:
            continue
        xs = sorted(xs)
        # 按列切开：同一张卡的 logo 是连续区间，列间会有明显空隙
        cols, start, prev = [], xs[0], xs[0]
        for x in xs[1:]:
            if x - prev > int(W * 0.04):
                cols.append((start, prev)); start = x
            prev = x
        cols.append((start, prev))
        for lo, hi in cols:
            if hi - lo < 8:                    # 太窄，是图标碎片
                continue
            out.append((lo + int(W * 0.02), yc))
    return out


def open_via_panel(W, H):
    """主路径：小程序面板 → 搜索 → 点第一条（精确匹配）→ 用窗口标题验证。带自愈重试。"""
    for round_no in (1, 2):
        print("[reopen] 第%d轮：走小程序面板搜索" % round_no)
        if not open_panel(W, H):
            return False
        if panel_search_once(W, H):
            return True
    return False


# ───────────────────────── 备选：主窗口搜索 → 结果页 ─────────────────────────

def win_class(wid):
    """取窗口的 WM_CLASS（主窗口是 wechat；小程序面板窗口没有这个属性）"""
    out = run("DISPLAY=%s xprop -id %s WM_CLASS 2>/dev/null" % (DISPLAY, wid))
    if "not found" in out or "=" not in out:
        return ""
    return out.split("=", 1)[1].strip().strip('"')


def find_main_window():
    """微信主窗口 = 标题「微信」且 WM_CLASS 含 wechat 的那个。
    ⚠️ 不能用「id 最小」来猜：小程序面板窗口的 id 可能比主窗口还小（实测过）。"""
    for wid, title in windows():
        if title.strip() == "微信" and "wechat" in win_class(wid).lower():
            return wid
    return None


def find_panel_window():
    """已存在的小程序面板窗口 = 标题「微信」但没有 WM_CLASS 的那个"""
    for wid, title in windows():
        if title.strip() == "微信" and not win_class(wid):
            return wid
    return None


def activate_main(W, H):
    """把微信主窗口提到最前"""
    main = find_main_window()
    if not main:
        return False
    run("DISPLAY=%s xdotool windowactivate %s" % (DISPLAY, main))
    time.sleep(1.2)
    return True


def find_netsearch_row(buf, W, H):
    """找搜索下拉里「搜索网络结果」那一行的 y。
    判据用**图标宽度**：它是窄的 ✳（只占 x≈89..98，约 9px），
    而小程序行的 logo 占 x≈76..98（约 22px）—— 颜色不可靠（logo 里也有浅粉像素），
    宽度可靠。（🔍 建议行的放大镜是灰色，不参与。）"""
    x0, x1 = int(W * 0.054), int(W * 0.086)      # 69..110
    rows = {}
    for y in range(int(H * 0.05), int(H * 0.65)):
        base = y * W * 3
        xs = []
        for x in range(x0, x1):
            i = base + x * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            if max(r, g, b) - min(r, g, b) > 45:          # 彩色像素（排除灰色图标/文字）
                xs.append(x)
        if xs:
            rows[y] = (min(xs), max(xs))
    if not rows:
        return None
    ys = sorted(rows)
    bands, cur = [], [ys[0]]
    for y in ys[1:]:
        if y - cur[-1] <= 6:
            cur.append(y)
        else:
            bands.append(cur); cur = [y]
    bands.append(cur)
    thin = max(int(W * 0.012), 12)                        # 窄于 ~15px 视为 ✳
    for band in bands:
        if len(band) < 8:                                 # 太薄，不是图标
            continue
        lo = min(rows[y][0] for y in band)
        hi = max(rows[y][1] for y in band)
        if hi - lo <= thin:
            return (band[0] + band[-1]) // 2
    return None


def do_search(W, H):
    """主窗口搜索框 → 输入 → 点下拉里的「搜索网络结果」→ 落到搜一搜结果页"""
    sx, sy = int(W * R_SEARCH_BOX[0]), int(H * R_SEARCH_BOX[1])
    print("[reopen] 搜索框 (%d,%d) 输入「%s」" % (sx, sy, KEYWORD))
    click(sx, sy)
    key("ctrl+a"); key("Delete")
    type_text(KEYWORD)
    time.sleep(2.0)
    buf = grab(W, H)
    png(W, H, "reopen_search_dropdown.png")
    ny = find_netsearch_row(buf, W, H)
    if ny:
        print("[reopen] 点「搜索网络结果」y=%d" % ny)
        click(int(W * 0.12), ny, 4.0)
    else:
        print("[reopen] 没定位到「搜索网络结果」行，退回 Down+回车")
        key("Down", 0.8); key("Return", 4.0)
    png(W, H, "reopen_search_page.png")


def find_rows(buf, W, H):
    """找结果行的 y 中心：结果行左侧有一块方形 logo（高饱和或深色），
    按 y 扫描 logo 列，聚成连续带即为一行。返回行中心 y 列表。"""
    x0, x1 = int(W * 0.17), int(W * 0.24)
    scores = {}
    for y in range(int(H * 0.10), int(H * 0.97)):
        base = y * W * 3
        n = 0
        for x in range(x0, x1, 2):
            i = base + x * 3
            r, g, b = buf[i], buf[i + 1], buf[i + 2]
            if max(r, g, b) - min(r, g, b) > 45 or max(r, g, b) < 200:   # 彩色 或 深色
                n += 1
        if n >= 4:
            scores[y] = n
    if not scores:
        return []
    ys = sorted(scores)
    bands, cur = [], [ys[0]]
    for y in ys[1:]:
        if y - cur[-1] <= 8:
            cur.append(y)
        else:
            bands.append(cur); cur = [y]
    bands.append(cur)
    # logo 方块大约 40~60px 高；太薄的带是文字/分隔线，丢掉
    return [(b[0] + b[-1]) // 2 for b in bands if len(b) >= 24]


def open_via_search(W, H):
    """主窗口搜索 → 结果页逐行点并验证。每轮失败重做一次搜索（自愈）。"""
    for round_no in (1, 2):
        if not activate_main(W, H):
            print("[reopen] 找不到微信主窗口")
            return False
        do_search(W, H)
        rows = find_rows(grab(W, H), W, H)
        print("[reopen] 第%d轮：结果页找到 %d 行：%s" % (round_no, len(rows), rows))
        if not rows:
            continue
        baseline = {wid for wid, _ in windows()}
        for i, y in enumerate(rows[:6], 1):
            print("[reopen] 第%d轮 试第 %d 行 y=%d" % (round_no, i, y))
            TOUCHED[0] = True
            click(int(W * 0.28), y, 3.0)
            wid, title = find_target_window()
            if wid:
                print("[reopen] 打开成功：%s" % title)
                png(W, H, "reopen_done.png")
                return True
            for wid_, title_ in windows():        # 开错了就关掉，别越堆越多
                if wid_ not in baseline and TARGET not in title_:
                    print("[reopen] 开错了（%s），关掉" % title_)
                    close_window(wid_)
            activate_main(W, H)                   # 页面可能被带走了，拉回主窗口
    print("[reopen] 两轮都扫完还没打开")
    return False


# ───────────────────────── 兜底：甄选 → banner 跳转 ─────────────────────────

def do_jump_from_zx_home(W, H):
    """甄选首页：点签到 banner，等跳转弹窗，点允许"""
    spots = [(0.191, 0.806), (0.50, 0.517), (0.25, 0.517)]
    for i, (fx, fy) in enumerate(spots, 1):
        x, y = int(W * fx), int(H * fy)
        print("[reopen] 第%d次点签到 banner (%d,%d)" % (i, x, y))
        click(x, y)
        for _ in range(3):
            time.sleep(2)
            g = find_green(grab(W, H), W, H)
            if g:
                gx, gy = (g[0] + g[2]) // 2, (g[1] + g[3]) // 2
                print("[reopen] 点「允许」(%d,%d)" % (gx, gy))
                click(gx, gy)
                time.sleep(8)
                png(W, H, "reopen_done.png")
                return True
    p = png(W, H, "reopen_nodialog.png")
    print("[reopen] 三次都没等到跳转弹窗 → 截图 %s" % p)
    return False


def open_via_zhenxuan(W, H):
    """旧路线：搜「辣可可甄选」→ 点下拉里的小程序行 → 甄选首页 → banner"""
    sx, sy = int(W * R_SEARCH_BOX_OLD[0]), int(H * R_SEARCH_BOX_OLD[1])
    print("[reopen] 兜底：点搜索框 (%d,%d) 输入「%s」" % (sx, sy, FALLBACK_KEYWORD))
    click(sx, sy)
    time.sleep(1.2)
    key("ctrl+a"); key("Delete")
    type_text(FALLBACK_KEYWORD)
    time.sleep(4)
    buf = grab(W, H)
    png(W, H, "reopen_search.png")
    ry = find_logo_row(buf, W, H)
    if not ry:
        print("[reopen] 下拉里没找到小程序行")
        return False
    click(int(W * R_ROW_CLICK_X), ry)
    time.sleep(8)
    png(W, H, "reopen_after_row.png")
    if red_ratio(grab(W, H), W, H) < 0.35:
        print("[reopen] 点完那行后没看到甄选首页")
        return False
    return do_jump_from_zx_home(W, H)


# ───────────────────────────── main ─────────────────────────────

def main():
    if "--close" in sys.argv:
        # 签到完把小程序与面板都关掉，释放运行时内存（下次签到会自动重开）。
        # 都走微信自己的关闭按钮 —— 绝不用 xdotool windowclose（会把微信状态搞坏）。
        names = []
        wid, t = find_target_window()
        if wid and close_window(str(wid)):
            names.append(t)
        pw = find_panel_window()
        if pw and close_window(str(pw)):
            names.append("小程序面板")
        print("[reopen] 已关闭：%s" % ("、".join(names) if names else "（本来就没开着）"))
        return 0

    if "--check" in sys.argv:
        wid, t = find_target_window()
        print("[reopen] 目标窗口：%s" % (t or "（未打开）"))
        return 0 if wid else 3

    wid, t = find_target_window()
    if wid:
        print("[reopen] 已经打开：%s" % t)
        return 0

    W, H = size()
    if (W, H) != (WANT_W, WANT_H):
        print("[reopen] 屏幕 %dx%d → 钉到 %dx%d（坐标按此校准）" % (W, H, WANT_W, WANT_H))
        run("DISPLAY=%s xrandr -s %dx%d" % (DISPLAY, WANT_W, WANT_H))
        time.sleep(2)
        W, H = size()

    print("[reopen] 主路径：主窗口搜索 → 搜一搜结果页")
    if open_via_search(W, H):
        return 0

    print("[reopen] 搜索路径失败，改走小程序面板")
    if open_via_panel(W, H):
        return 0

    print("[reopen] 面板路径也失败，改走甄选兜底")
    if open_via_zhenxuan(W, H):
        return 0

    p = png(W, H, "reopen_fail.png")
    if LOOSE and TOUCHED[0]:
        print("[reopen] 点过候选卡片但没等到目标窗口（界面形态可能变了）→ 返回 4，"
              "请用 `node cdp_eval.js --probe` 按 appId 复核，截图 %s" % p)
        return 4
    print("[reopen] 没能打开 → 截图 %s（需人工打开一次）" % p)
    return 3


if __name__ == "__main__":
    sys.exit(main())
