#!/usr/bin/env bash
# 在云微实例里切换微信 Linux 版本（秒切 + 可回滚），用于「钉版 / 回滚 / 多版本测试」
#
# 做法：把 /config/wechat 变成符号链接，各版本解包到 /config/wechat.v<版本号>。
#   切换 = 改符号链接 + 重启微信进程（autostart 会自己把微信拉起来）。
#   ⚠️ 重启微信会让登录态回到「点一下登录」的界面（账号还在，通常不需要手机确认）；
#      但**切换版本本身不丢登录数据**（登录态在 /config/.xwechat，不在程序目录里）。
#
# 用法：
#   bash switch_wechat_version.sh list                     # 列出已解包的版本
#   bash switch_wechat_version.sh cur                      # 当前指向哪个版本
#   bash switch_wechat_version.sh init                     # 首次：把现有 wechat/ 纳入符号链接管理
#   bash switch_wechat_version.sh install <deb> <版本号>    # 解包一个 deb 到 /config/wechat.v<版本号>
#   bash switch_wechat_version.sh use <版本号>              # 切到该版本并重启微信
#
# 环境变量：WOC_INSTANCE 指定实例容器名，默认自动挑第一个 woc-wx-* 容器。
set -u
export PATH="/usr/bin:/bin:$PATH"
W="${WOC_INSTANCE:-$(docker ps --format '{{.Names}}' | grep -E '^woc-wx-' | head -1)}"
if [ -z "${W:-}" ]; then
  echo "没找到实例容器（woc-wx-*）。用 WOC_INSTANCE=<容器名> 指定。" >&2
  exit 1
fi

kill_wechat() {
  # 实例容器的 procfs 对其它进程的 cmdline 受限，用 ps 拿 pid 更稳
  docker exec "$W" sh -c 'ps -eo pid,comm 2>/dev/null | awk "\$2==\"wechat\"||\$2==\"WeChatAppEx\"||\$2==\"crashpad_handler\"{print \$1}" | while read p; do kill -9 "$p" 2>/dev/null && echo "  kill $p"; done'
}

case "${1:-}" in
  list)
    docker exec "$W" sh -c 'ls -d /config/wechat.v* 2>/dev/null | while read d; do v=$(cat "$d/.woc-version" 2>/dev/null); sz=$(stat -c %s "$d/opt/wechat/RadiumWMPF/runtime/WeChatAppEx" 2>/dev/null); printf "  %-12s WeChatAppEx=%s\n" "${v:-?}" "${sz:-缺}"; done'
    ;;
  cur)
    docker exec "$W" sh -c '
      echo "指向: $(readlink -f /config/wechat)"
      echo "版本: $(cat /config/wechat/.woc-version 2>/dev/null)"
      ls -la /config/wechat/opt/wechat/RadiumWMPF/runtime/WeChatAppEx | awk "{print \"运行时大小:\", \$5}"
      grep -aoE "wmpf_release/[A-Za-z0-9_.]+" /config/wechat/opt/wechat/RadiumWMPF/runtime/WeChatAppEx 2>/dev/null | head -1 | sed "s/^/release: /"
    '
    ;;
  init)
    docker exec "$W" sh -c '
      set -e
      cd /config
      if [ -L wechat ]; then echo "已经是符号链接：$(readlink wechat)"; exit 0; fi
      v=$(cat wechat/.woc-version 2>/dev/null || echo unknown)
      mv wechat "wechat.v$v"
      ln -s "wechat.v$v" wechat
      echo "已纳入管理：/config/wechat -> wechat.v$v"
    '
    ;;
  install)
    deb="${2:?用法: install <deb 路径> <版本号>}"
    ver="${3:?用法: install <deb 路径> <版本号>}"
    [ -f "$deb" ] || { echo "找不到 $deb" >&2; exit 1; }
    docker exec "$W" mkdir -p /config/dlx
    docker cp "$deb" "$W:/config/dlx/wechat-$ver.deb" >/dev/null
    docker exec "$W" sh -c "
      set -e
      t=/config/wechat.v$ver
      rm -rf \"\$t\"; mkdir -p \"\$t\"
      dpkg-deb -x /config/dlx/wechat-$ver.deb \"\$t\"
      echo $ver > \"\$t/.woc-version\"
      ls -la \"\$t/opt/wechat/RadiumWMPF/runtime/WeChatAppEx\" | awk '{print \"  已装 WeChatAppEx\", \$5, \"字节\"}'
    "
    ;;
  use)
    ver="${2:?用法: use <版本号>}"
    docker exec "$W" sh -c '[ -d "/config/wechat.v'"$ver"'" ] || { echo "没装过 $ver，先 install"; exit 1; }'
    docker exec "$W" sh -c "ln -sfn wechat.v$ver /config/wechat && echo 已切到 $ver"
    echo "重启微信进程（autostart 约 2 秒后拉起新版本）…"
    kill_wechat
    echo "等待 50 秒让微信起来…"
    sleep 50
    echo "现在："
    "$0" cur
    echo "（若界面停在登录页，点一下「登录」，必要时手机确认）"
    ;;
  *)
    sed -n '2,20p' "$0"
    ;;
esac
