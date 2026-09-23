#!/usr/bin/env bash
# 给 WMPFDebugger 的 hook.js 打本地补丁（幂等，可反复跑）
#
# 为什么必须打：
#   hook.js 只在**场景号白名单**内才把 scene 改写成 1101，进而打开小程序的 devtools 通道。
#   微信 4.1.13.23 里，从「小程序面板 → 搜索 → 结果卡片」打开小程序时场景号是 **1183**，
#   不在上游白名单里（1145=搜索 / 1256=最近使用 / 1260=我的常用 …）→ 不改写 → 小程序
#   不会连 `ws://localhost:9421` → CDP 拿不到身份、刷不了 token、也就签不了到。
#   现象：hook 日志里没有 `[miniapp] miniapp client connected`；
#        用 `--debug-frida` 跑也只能看到一堆 `[inteceptor] ... OnLoadStart onEnter`。
#
# 补丁做两件事：
#   ① 白名单加 1183
#   ② 不在白名单时也把场景号打出来（以后遇到新入口，看日志就知道号是多少）
#
# 用法: bash hook_patch.sh [容器名]     默认 woc-hook
set -u
export PATH="/usr/bin:/bin:$PATH"
C="${1:-woc-hook}"

docker exec -i "$C" sh <<'INNER'
set -e
F=/opt/wmpf/frida/hook.js
if [ ! -f "$F" ]; then
  echo "[patch] 找不到 $F —— 还没装 WMPFDebugger？先按部署文档第 4 步装"
  exit 1
fi
if grep -q "1183" "$F"; then
  echo "[patch] 已打过补丁，跳过"
  exit 0
fi

cp "$F" /tmp/hook.js.orig

# ① 白名单加 1183
sed -i 's/1256, 1260, 1302, 1308,/1256, 1260, 1302, 1308, 1183,/' "$F"

# ② 不在白名单时也打印场景号（诊断用）
sed -i 's|if (!sceneNumberArray.includes(miniappScenePtr.readInt())) {|if (!sceneNumberArray.includes(miniappScenePtr.readInt())) {\n        send("[hook] scene NOT in whitelist: " + miniappScenePtr.readInt());|' "$F"

if grep -q "1183" "$F"; then
  echo "[patch] 已打补丁：白名单 +1183，并加上了场景号诊断日志"
  echo "[patch] 原文件备份在容器内 /tmp/hook.js.orig"
else
  echo "[patch] 失败：hook.js 结构可能已变，已回滚"
  cp /tmp/hook.js.orig "$F"
  exit 1
fi
INNER
