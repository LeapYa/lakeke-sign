#!/usr/bin/env bash
# 辣可可每日签到的无人值守入口（可挂 cron / Windows 计划任务）
#
#   cron 例子：0 8 * * *  bash /path/to/lakeke-sign/daily.sh
#   Windows 计划任务：程序 bash，参数 daily.sh 的绝对路径
#
# 做的事：docker 引擎 → 微信实例 → 旁挂 hook → 小程序是否开着（不在就自动重开）
#         → 刷新 token（没过期自动跳过）→ 签到 → 关掉小程序省内存 → 失败时告警
#
# 环境变量（可选）：
#   WOC_INSTANCE       微信实例容器名，默认 woc-wx-2ada0225ca
#   WOC_HOOK           旁挂 hook 容器名，默认 woc-hook
#   LAKEKE_PYTHON      Windows 侧 python 路径
#   LAKEKE_APPID       期望的小程序 appId（默认辣可可；改了就是给别的小程序用）
#   LAKEKE_KEEP_OPEN=1 签到后**不关**小程序（默认会关掉省内存）
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
APPID_EXPECT="${LAKEKE_APPID:-wxf8a17a14c0521576}"   # 辣可可小程序的 appId（身份判据）
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

# 当前打开的是哪个小程序 —— 打印 appId 列表（逗号分隔）。空 = 一个小程序都没开。
# 这是**与界面形态无关**的身份判据（读 wx.getAccountInfoSync），小程序将来不再独立开窗也成立。
probe_appid() { docker exec "$HOOK" sh -c 'cd /work/lakeke-sign && NODE_PATH=/opt/wmpf/node_modules node cdp_eval.js --probe' 2>/dev/null | sed -n 's/^APPID=//p' | tail -1; }

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
#    判据用 **appId**：读小程序逻辑层的 wx.getAccountInfoSync()，与窗口形态无关。
#    「窗口标题」只用于 reopen 内部点完后的即时确认，不作最终判据。
APPID="$(probe_appid)"
case "$APPID" in
  *"$APPID_EXPECT"*) log "小程序在线（appId=$APPID）" ;;
  *)
    log "目标小程序不在（当前 appId=${APPID:-无}），尝试自动重开"
    docker cp lakeke-sign/reopen_miniapp.py "$INSTANCE":/tmp/reopen_miniapp.py >/dev/null 2>&1
    docker exec -e DISPLAY=:1 "$INSTANCE" python3 /tmp/reopen_miniapp.py --loose >>"$LOG" 2>&1
    RC=$?
    # --loose 的语义：0=已打开；4=点过候选但无法用窗口标题确认（界面形态可能变了）；3=没点到
    [ "$RC" = "0" ] || log "重开脚本返回 $RC（0=已开 / 4=点过待 appId 复核 / 3=没点到）"
    sleep 6
    APPID="$(probe_appid)"
    case "$APPID" in
      *"$APPID_EXPECT"*) log "重开成功（appId=$APPID）" ;;
      *) die "自动重开失败：appId 复核未命中（当前=${APPID:-无}，重开脚本 RC=$RC）。看 shots/reopen_*.png；目标号是「辣可可现炒黄牛肉i」" ;;
    esac
    ;;
esac

# --ensure-only：只做保活（自检 + 小程序在线/重开），不签到。适合高频跑的保活任务。
if [ "${1:-}" = "--ensure-only" ]; then
  log "仅保活模式，退出（未签到）"
  exit 0
fi

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

# 5. 省内存：签到完把小程序与面板都关掉，下次签到由第 2 步自动重开。
#    实测（容器内存）：都开着 2.70 GiB → 都关掉 2.48 GiB，省 ~220 MB。
#    注意大头是微信本体与 WMPF 常驻框架（~2.4 GiB），关小程序省不掉那部分。
#    设 LAKEKE_KEEP_OPEN=1 可保持常开（如果你更在意「每次少花 1 分钟重开」）。
if [ "${LAKEKE_KEEP_OPEN:-0}" = "1" ]; then
  log "LAKEKE_KEEP_OPEN=1，保留小程序不关"
else
  docker cp lakeke-sign/reopen_miniapp.py "$INSTANCE":/tmp/reopen_miniapp.py >/dev/null 2>&1
  if docker exec -e DISPLAY=:1 "$INSTANCE" python3 /tmp/reopen_miniapp.py --close >>"$LOG" 2>&1; then
    log "已关闭小程序与面板（省内存；下次签到会自动重开）"
  else
    log "关闭小程序失败（不影响签到结果，下次签到自己会处理）"
  fi
fi

# 6. 可选：成功也汇报一条（便于确认无人值守还在正常跑）
if [ "$NOTIFY_ALWAYS" = "1" ]; then
  MINFO="$("$PY" lakeke-sign/member_info.py 2>/dev/null | tail -1)"
  notify "✅ 辣可可签到" "$RMSG
${MINFO:+$MINFO}
结果码: R=$R
时间: $(date '+%F %T')   主机: $(hostname)" ok
fi
log "===== 结束 ====="
