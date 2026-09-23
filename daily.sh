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
#   通知渠道（配了哪个就发哪个，全走 notify.py，按渠道限额自动降级）：
#     WECOM_WEBHOOK / PUSHPLUS_TOKEN / WXPUSHER_APP_TOKEN(+UIDS/TOPIC_IDS)
#     DINGTALK_ACCESS_TOKEN(+DINGTALK_SECRET) / SMTP_HOST,PORT,USER,PASS,TO
#     LAKEKE_NOTIFY_URL（通用 webhook）
#   LAKEKE_NOTIFY_ALWAYS=1   成功也发一条（默认只在失败时发）
set -u
export PATH="/usr/bin:/bin:$PATH"
export MSYS_NO_PATHCONV=1

WS="$(cd "$(dirname "$0")/.." && pwd)"
cd "$WS"
INSTANCE="${WOC_INSTANCE:-woc-wx-2ada0225ca}"
HOOK="${WOC_HOOK:-woc-hook}"
PY="${LAKEKE_PYTHON:-C:/Users/tingjian/.workbuddy/binaries/python/envs/default/Scripts/python.exe}"
NOTIFY_ALWAYS="${LAKEKE_NOTIFY_ALWAYS:-0}"
NOTIFY_PY="$WS/lakeke-sign/notify.py"
LOG="$WS/lakeke-sign/daily.log"

log()  { echo "[$(date '+%F %T')] $*" | tee -a "$LOG"; }
# 通知走 notify.py：多渠道 fan-out + 按各渠道字节限额降级（企业微信 4KB / 钉钉 2 万字…）
notify(){ "$PY" "$NOTIFY_PY" --title "$1" --text "$2" --status "${3:-ok}" >>"$LOG" 2>&1 \
          || log "通知发送失败（不影响签到本身）"; }
die()  { log "FAIL: $1"
         notify "❌ 辣可可签到失败" "$1
时间: $(date '+%F %T')   主机: $(hostname)" fail
         exit 1; }

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
  200)     RMSG="签到成功（+积分）" ;;
  415)     RMSG="今日已签到（正常，无需重复签）" ;;
  401|402) die "会员问题（R=$R）：不是会员或卡不可用" ;;
  208|211) die "token 被拒（R=$R）—— 检查小程序上下文是不是真在辣可可" ;;
  *)       die "签到返回异常 R=${R:-无}：$(echo "$OUT" | tail -2 | tr '\n' ' ')" ;;
esac
log "$RMSG（R=$R）"

# 5. 可选：成功也汇报一条（便于确认无人值守还在正常跑）
if [ "$NOTIFY_ALWAYS" = "1" ]; then
  MINFO="$("$PY" lakeke-sign/member_info.py 2>/dev/null | tail -1)"
  notify "✅ 辣可可签到" "$RMSG
${MINFO:+$MINFO}
结果码: R=$R
时间: $(date '+%F %T')   主机: $(hostname)" ok
fi
log "===== 结束 ====="
