#!/usr/bin/env bash
# 辣可可每日签到的无人值守入口（可挂 cron / Windows 计划任务）
#
#   cron 例子：0 8 * * *  bash /path/to/lakeke-sign/daily.sh
#   Windows 计划任务：程序 bash，参数 daily.sh 的绝对路径
#
# 做的事：docker 引擎 → 微信实例 → 旁挂 hook → 小程序是否开着（不在就自动重开）
#         → 刷新 token（没过期自动跳过）→ 签到 → 失败时告警
#
# 环境变量（可选）：
#   WOC_INSTANCE       微信实例容器名，默认 woc-wx-2ada0225ca
#   LAKEKE_PYTHON      Windows 侧 python 路径
#   LAKEKE_NOTIFY_URL  失败告警 webhook（企业微信机器人那种，POST {"msgtype":"text",...}）
set -u
export PATH="/usr/bin:/bin:$PATH"
export MSYS_NO_PATHCONV=1

WS="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WS"
INSTANCE="${WOC_INSTANCE:-woc-wx-2ada0225ca}"
HOOK="${WOC_HOOK:-woc-hook}"
PY="${LAKEKE_PYTHON:-C:/Users/tingjian/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"
NOTIFY="${LAKEKE_NOTIFY_URL:-}"
LOG="$WS/lakeke-sign/daily.log"

log()  { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
alarm(){ [ -n "$NOTIFY" ] && curl -s -m 10 -X POST -H 'Content-Type: application/json' \
         -d "{\"msgtype\":\"text\",\"text\":{\"content\":\"$1\"}}" "$NOTIFY" >/dev/null 2>&1; }
die()  { log "FAIL: $1"; alarm "辣可可签到失败：$1"; exit 1; }

cdp() { docker exec "$HOOK" sh -c "cd /work/lakeke-sign && NODE_PATH=/opt/wmpf/node_modules node cdp_eval.js \"$1\" ${2:---wait 14}" 2>&1; }

log "===== 开始 ====="

# 1. 基础设施
docker ps >/dev/null 2>&1 || die "docker 引擎未运行（Docker Desktop 没开？）"
docker ps --format '{{.Names}}' | grep -qx "$INSTANCE" || die "微信实例容器 $INSTANCE 未运行"
if ! docker ps --format '{{.Names}}' | grep -qx "$HOOK"; then
  log "hook 容器不在，重建中"
  bash hook_up.sh "$INSTANCE" >>"$LOG" 2>&1 || die "hook 重建失败"
fi
docker exec "$HOOK" grep -q "script loaded" /tmp/wmpf.log 2>/dev/null || {
  log "hook 日志里没有 script loaded，重建中"
  bash hook_up.sh "$INSTANCE" >>"$LOG" 2>&1 || die "hook 重建失败"
}
log "hook 就绪"

# 2. 小程序在不在（不在就自动重开一次）
if ! cdp '"1"' >/dev/null 2>&1; then
  log "辣可可小程序不在，尝试自动重开"
  docker cp lakeke-sign/reopen_miniapp.py "$INSTANCE":/tmp/reopen_miniapp.py >/dev/null 2>&1
  docker exec -e DISPLAY=:1 "$INSTANCE" python3 /tmp/reopen_miniapp.py >>"$LOG" 2>&1 \
    || log "重开脚本返回非 0（截图见 shots/reopen_*.png，可能是当前不在甄选首页）"
  sleep 6
  cdp '"1"' >/dev/null 2>&1 || die "小程序不在且自动重开失败（需人工打开辣可可甄选首页）"
fi
log "小程序在线"

# 3. 刷新 token（未过期会自己跳过）
docker exec "$HOOK" sh -c 'cd /work/lakeke-sign && NODE_PATH=/opt/wmpf/node_modules node auth_refresh_node.js' \
  >>"$LOG" 2>&1 || die "token 刷新失败"
log "token 就绪"

# 4. 签到（只认 lakeke_run.py 最后那行 RESULT=<code>，不能用 grep code= —— 详情那行也是 200）
OUT="$("$PY" -u lakeke-sign/lakeke_run.py 2>&1)"
echo "$OUT" >>"$LOG"
R="$(echo "$OUT" | grep -oE '^RESULT=[0-9]+' | tail -1 | cut -d= -f2)"
case "${R:-none}" in
  200)     log "签到成功（R=200）" ;;
  415)     log "今日已签到（R=415，正常）" ;;
  401|402) die "会员问题（R=$R）：不是会员或卡不可用" ;;
  208|211) die "token 被拒（R=$R）—— 检查小程序上下文是不是真在辣可可" ;;
  *)       die "签到返回异常 R=${R:-无}：$(echo "$OUT" | tail -2 | tr '\n' ' ')" ;;
esac
log "===== 结束 ====="
