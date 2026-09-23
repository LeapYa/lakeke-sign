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

echo "== 3. 启动 WMPFDebugger =="
docker exec -d woc-hook sh -c 'cd /opt/wmpf && node node_modules/ts-node/dist/bin.js src/index.ts > /tmp/wmpf.log 2>&1'
for i in $(seq 1 10); do
  sleep 4
  if docker exec woc-hook grep -q "script loaded" /tmp/wmpf.log 2>/dev/null; then break; fi
done

echo "== 4. 结果 =="
docker exec woc-hook cat /tmp/wmpf.log 2>&1 | head -8
echo "-- 小程序接入次数 --"
docker exec woc-hook grep -c "miniapp" /tmp/wmpf.log 2>/dev/null || echo 0
