#!/usr/bin/env bash
# 重新拉起云微实例旁的 WMPFDebugger hook 容器
# 用法: bash hook_up.sh [实例名]   默认 woc-wx-2ada0225ca
set -u
export PATH="/usr/bin:/bin:$PATH"
export MSYS_NO_PATHCONV=1

WX="${1:-woc-wx-2ada0225ca}"
WORK="C:/Users/tingjian/WorkBuddy/2026-09-23-00-19-36"
VOL="woc-data-${WX#woc-wx-}"

echo "== 1. 目标实例状态 =="
docker inspect "$WX" --format 'State={{.State.Status}} Pid={{.State.Pid}}' 2>/dev/null || {
  echo "实例 $WX 不存在"; exit 1; }

echo "== 2. 重建 helper（共享 PID + 网络命名空间） =="
docker rm -f woc-hook >/dev/null 2>&1
docker run -d --name woc-hook \
  --pid=container:"$WX" --network container:"$WX" \
  --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v "$WORK:/work" -v "$VOL:/config:ro" \
  woc-hook:1 sleep infinity >/dev/null 2>&1
sleep 4

echo "== 3. 给 hook.js 打场景号补丁（不加 1183 的话小程序不会连 9421） =="
bash "$(dirname "$0")/hook_patch.sh" woc-hook \
  || echo "⚠️ 补丁没打上：hook 能起，但小程序可能不接 9421（见 hook_patch.sh 顶部说明）"

echo "== 4. 启动 WMPFDebugger =="
docker exec -d woc-hook sh -c 'cd /opt/wmpf && node node_modules/ts-node/dist/bin.js src/index.ts > /tmp/wmpf.log 2>&1'
for i in $(seq 1 10); do
  sleep 4
  if docker exec woc-hook grep -q "script loaded" /tmp/wmpf.log 2>/dev/null; then break; fi
done

echo "== 5. 结果 =="
docker exec woc-hook cat /tmp/wmpf.log 2>&1 | head -8
echo "-- 小程序接入次数（>0 才算 hook 真接管了） --"
docker exec woc-hook grep -c "miniapp client connected" /tmp/wmpf.log 2>/dev/null || :
echo "   若为 0：小程序还没开（正常）或场景号没打补丁（见 hook_patch.sh 顶部说明）"
