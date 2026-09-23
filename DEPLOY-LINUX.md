# Linux 容器无人值守部署（首推方案）

> 这是本项目的**首选部署方式**。Windows 本机方案见 [DEPLOY.md](DEPLOY.md)（备选，机器要一直开着）。
> 本文所有步骤都是**实测跑通**的（2026-09-23，见文末「实测记录」），不是推演。

## 为什么首推 Linux 容器

| 对比项 | Linux 容器 | Windows 本机 |
|---|---|---|
| 微信会自己升级吗 | **不会**（手动装 deb，可把 WMPF 版本钉住） | 会，一升级 WMPF 偏移全失效、要重逆 |
| 无人值守 | 服务器常开即可 | 你的电脑得一直开着 |
| 环境干净 | 全在容器里，删了就干净 | 装一堆东西在本机 |
| 风控 | 住宅 IP（放家里）最稳；机房 IP 风险稍高 | 本机 IP 天然干净 |

共同前提：**签到凭证必须在微信里现取现用**（jsCode 只能由微信客户端产生；token 1~2 小时且服务端实测校验 `exp`）。

## 资源要多少（实测）

| 组件 | 内存 | 磁盘（镜像） |
|---|---|---|
| 微信实例 `woc-wx-*` | **1.23 GiB**（空闲），跑起小程序约 1.8 GiB | 4.6 GB + 数据卷 |
| hook 容器 `woc-hook` | 0.47 GiB | 0.94 GB（node + frida + WMPFDebugger） |
| 面板 `woc-panel` | 0.12 GiB | 0.49 GB |
| **合计** | **约 1.9 ~ 2.5 GiB** | **约 6 GB** |

- **机器建议 2 核 4 GiB**。2 GiB 会紧张，微信实例峰值就能吃掉 2G。
- **CPU**：实例空闲时也占 20% 左右（KasmVNC 推流 + 微信渲染），单核会卡。
- 脚本侧（python 签到 / node 取参）内存可忽略。

## 0. 载体怎么选（先决定这个）

| 载体 | 风控风险 | 成本 | 建议 |
|---|---|---|---|
| **家里旧笔记本 / 迷你主机 / NAS** | **最低**（住宅 IP + 真实硬件指纹） | 电费 ¥10~30/月 | ⭐ 首选 |
| Windows 云主机 + WSL2/Docker | 中高（机房 IP + Server 指纹） | 促销 ¥50~100/年起 | 方便，但用小号试 |
| 云手机 / 安卓容器 + RPA | 中高 | ¥30~100/月 | 最重，不推荐 |

> ⚠️ **强烈建议先用小号跑通再上主号。** 微信风控看的是 IP + 设备指纹；
> 容器本身不改变这两样，真正的风险变量是**机房 IP**。

## 1. 装 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
docker version
```

## 2. 部署微信实例（云微 WechatOnCloud）

云微是目前唯一**内置完整设备伪装**的项目（三个项目逐项对比见 [CONTAINER-OPTIONS.md](CONTAINER-OPTIONS.md)）：

```bash
mkdir -p ~/woc && cd ~/woc
curl -fsSLO https://raw.githubusercontent.com/Gloridust/WechatOnCloud/main/docker-compose.yml
```

编辑 `docker-compose.yml`：**删掉 `- /dev:/host-dev:ro`**（无摄像头时不需要，某些环境挂载会失败）。

先生成面板登录密码，**把打印出来的这串记下来**（后面登录面板要用）：

```bash
PW="woc-$(head -c 12 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 10)"
echo "面板密码: $PW"
```

建 `.env`（第一行填 `$PW` 的值）：

```dotenv
WOC_PASSWORD=<上一步打印出来的密码>
WOC_HTTP_PORT=36080
WOC_SPOOF_OS=1
# 关键：默认软阈值 1500MiB 太低（跑起小程序实测到 1.8G），看门狗会「柔和重启」实例，
#       而重启 = 微信掉登录（要手机确认）+ hook 容器被连坐带走
# 4G 机器建议 soft=2500~3000、hard=4000；soft 设成 4000 相当于把自愈关掉了
WOC_INSTANCE_MEM_SOFT_MB=2800
WOC_INSTANCE_MEM_HARD_MB=4000
```

```bash
docker compose up -d
```

> **坑 1**：若 `docker compose` 报 WSL 相关错误（Windows 上会遇到），改用等价的 `docker run` 起面板，
> 并**必须给面板和实例指定同一个自定义网络**——默认 bridge **没有容器名 DNS**，而面板是按容器名反代实例的，
> 结果就是进实例时一直「桌面长时间未就绪」：
> ```bash
> docker network create woc-net
> docker run -d --name woc-panel --network woc-net -p 36080:8080 \
>   -v ~/woc/data-panel:/data -v /var/run/docker.sock:/var/run/docker.sock \
>   -e PORT=8080 -e WOC_DOCKER_NETWORK=woc-net \
>   -e WOC_WECHAT_IMAGE=docker.io/gloridust/wechat-on-cloud:1.4.9 \
>   -e PANEL_ADMIN_USER=admin -e PANEL_ADMIN_PASSWORD=<同一个密码> \
>   -e WOC_SPOOF_OS=1 -e WOC_INSTANCE_MEM_SOFT_MB=2800 -e WOC_INSTANCE_MEM_HARD_MB=4000 \
>   -e TZ=Asia/Shanghai --restart unless-stopped gloridust/woc-panel:latest
> ```

### 登录面板

浏览器打开 `http://<机器IP>:36080`，用户名 `admin`、密码是上面生成的那串 → 新建「微信实例」→
等镜像拉完、微信自动装好 → 进实例 → 手机扫码登录。

**密码存在哪、忘了怎么找回**：

| 情况 | 做法 |
|---|---|
| 正常情况 | 就在部署目录的 `.env` 里：`grep WOC_PASSWORD ~/woc/.env` |
| `.env` 没了 | 从运行中的面板容器读：<br>`docker inspect woc-panel --format '{{range .Config.Env}}{{println .}}{{end}}' \| grep PANEL_ADMIN` |
| 当时没设 | 官方 compose 的默认值是 `WOC_PASSWORD=wechat`（用户名 `admin`）。**不要用默认值**——这个面板能操作宿主机 Docker |
| 想换密码 | 改 `~/woc/.env` 的 `WOC_PASSWORD` 后 `docker compose up -d` 重建面板；微信实例在数据卷里，不受影响 |

> 注意本方案有两个 `.env`，别搞混：**`~/woc/.env` 是云微面板的**（面板密码、内存阈值），
> **`lakeke.env` 是签到脚本的**（身份、token、通知），后者由 [.env.example](.env.example) 复制而来。

**登录后校验设备伪装**（应看到唯一 machine-id、像个人电脑的 hostname、`/.dockerenv` 已移除、真实 OUI 的 MAC）：

```bash
docker exec <实例容器名> sh -c 'cat /etc/machine-id; hostname; \
  [ -e /.dockerenv ] && echo "dockerenv 还在(未伪装)" || echo "dockerenv 已移除 ✓"; \
  cat /sys/class/net/eth0/address; grep PRETTY_NAME /etc/os-release'
```

### 2.5 装完先验版本（不通过就别往下走）

微信本体是**手动装包、不自动更新**，但要能被 hook，**WMPF 版本必须落在 WMPFDebugger 的
linux 偏移配置里** —— 上游目前只有三份：

| 上游配置 `frida/config/linux/` | 对应 WMPF | 对应微信 Linux |
|---|---|---|
| `addresses.14910.json` | 1.4.9.10 | 早期 4.0.x |
| `addresses.14978.json` | 1.4.9.78 | 4.0.x |
| `addresses.25665.json` | **2.5.6.65** | **4.1.13.23（实测可用）** |

配置文件名 = `addresses.<WMPF 去掉点>+<build>.json`。**要看的是 WMPF 版本，不是微信版本号。**

一条命令验完：

```bash
bash check_wmpf.sh <实例容器名>
```

看到 `[OK] WMPF 25665 有对应偏移配置` 再继续；看到 `[FAIL]` 先别往下走，按它给的四个选项处理。

> ⚠️ **不要点面板里的「更新微信」按钮。** 它下载的是官方**不带版本号**的直链，拿到的永远是最新版；
> 一旦新版的 WMPF 没有对应配置，hook 就挂不上。（官方 CDN 也没有带版本号的地址——实测
> `WeChatLinux_x86_64_4.1.13.23.deb`、`4.1.13.23/…`、`versions/4.1.13.23/…` 四种命名全是 404。）

### 2.6 万一版本漂了怎么办

| | 办法 | 说明 |
|---|---|---|
| 1 | **偏移配置改名试挂** | 若新微信的 WMPF 只是同一个 `x.y.z` 下的不同 build，偏移**可能一模一样**。把 `addresses.25665.json` 复制成新的号试挂，1 分钟见分晓 |
| 2 | **用旧版 deb 重装** | 微信是 `dpkg-deb -x` 解压到数据卷、**不走 apt**，所以换包即可。把 deb 放自己的静态服务/对象存储，启动实例时加 `-e WECHAT_CDN=https://<你的镜像>/weixin/Universal/Linux`（`wechat-ctl.sh` 原生支持这个变量） |
| 3 | **自己算偏移** | 要逆向能力；或等上游社区补配置 |
| 4 | **转 Windows 方案** | 上游 `frida/config/win32/` 有 **53 份**配置，linux 只有 3 份 —— Windows 抗漂移能力强得多。→ [DEPLOY.md](DEPLOY.md) |

**已知可用安装包**（留个记录，方便核对；项目本体不托管腾讯的安装包）：

```
微信 Linux   4.1.13.23
WMPF         2.5.6.25665
deb 文件名   WeChatLinux_x86_64.deb
deb 大小     231,359,624 字节
sha256       b7d0f8d53e9f648bc2c77a6096a04100d008f2d9f0d3988a2a4859b5992aca0a
```

> **为什么项目里不放这个 deb**：231 MB 超过 GitHub 单文件 100 MiB 的硬上限（git 和 LFS 都放不下，
> LFS 免费额度只有 1 GB 存储 + 1 GB/月流量），而且再分发腾讯的商业安装包有被 takedown 的风险，
> 牵连仓库本体不值得。自己留一份在网盘/对象存储，用上面的 `WECHAT_CDN` 指过去即可。

## 3. 打开小程序（首次人工一次，之后由脚本自动）

`reopen_miniapp.py` 能自动完成这一步（停在微信主窗口就从搜索框找，停在甄选首页就点签到横幅），
但**首次建议人工走一遍确认路径可用**：

微信窗口里：搜索 **辣可可甄选** → 打开 → 点首页横幅左下角 **「点击签到」**
→ 弹「即将打开 辣可可现炒黄牛肉」→ 允许 → 落到辣可可签到页。

| 微信里搜索入口 | 首页横幅与跳转确认 |
|---|---|
| ![搜索打开小程序](docs/images/01-open-in-wechat.png) | ![轮播图与跳转确认](docs/images/02-banner-jump.jpg) |

必须打开过：`wx.login` 的 jsCode 与 appid 绑定（实测甄选产的 code 配辣可可 mpId 一律 `invalid code`），
只有辣可可那个小程序在运行，才能换到它的 token。

## 4. 挂 hook（旁挂容器，不动云微的实例）

云微建的实例**没有 `CAP_SYS_PTRACE`**，frida attach 不了。所以旁挂 helper 容器与实例共享命名空间：

```bash
WX=<实例容器名>                # 例 woc-wx-2ada0225ca
VOL=woc-data-${WX#woc-wx-}     # 云微的数据卷名

docker run -d --name woc-hook \
  --pid=container:$WX \
  --network=container:$WX \
  --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v ~/lakeke:/work -v $VOL:/config:ro \
  node:22-slim sleep infinity
```

> 两个 `--pid` / `--network` **都必须是 `container:`**。
> 只共享 PID 不共享网络的话，小程序连不上 `ws://localhost:9421`（那是实例自己 netns 里的地址），
> hook 日志永远不会出现 `[miniapp] connected`。

装 WMPFDebugger + Linux 版 frida：

```bash
git clone --depth 1 https://github.com/evi0s/WMPFDebugger.git
docker exec woc-hook sh -c '
  mkdir -p /opt/wmpf && cd /work/WMPFDebugger
  cp -r src package.json tsconfig.json frida /opt/wmpf/
  cd /opt/wmpf
  npm i --ignore-scripts --registry=https://registry.npmmirror.com --no-audit --no-fund
  mkdir -p node_modules/frida/build
  curl -fsSL -o /tmp/f.tar.gz https://github.com/frida/frida/releases/download/17.18.0/frida-v17.18.0-napi-v8-linux-x64.tar.gz
  tar -xzf /tmp/f.tar.gz -C node_modules/frida/build --strip-components=1
  cp -r /work/WMPFDebugger/node_modules/frida/build/src node_modules/frida/build/   # 见下方说明
  node -e "console.log(require(\"frida\").version)"
'
docker commit woc-hook woc-hook:1   # 固化，之后重建不必重装
docker exec -d woc-hook sh -c 'cd /opt/wmpf && node node_modules/ts-node/dist/bin.js src/index.ts > /tmp/wmpf.log 2>&1'
docker exec woc-hook tail -5 /tmp/wmpf.log   # 期望：[frida] script loaded, WMPF version: 25665
```

> `npm i --ignore-scripts` 会跳过 frida 的 install 脚本，**JS 包装层不会被生成**，
> 所以要把 Windows 那份 clone 里现成的 `node_modules/frida/build/src` 拷过去补上（Linux 的 `.node` 用下载的）。
>
> **WMPF 版本必须落在 `frida/config/linux/` 的配置里**（当前 14910 / 14978 / 25665）。
> 微信 Linux 4.1.13 实测是 **25665**。版本不对就换微信 deb 版本，或等上游加配置。

## 5. 落地脚本 + 配置

脚本放在上面 `-v ~/lakeke:/work` 对应的目录里，**保持 `lakeke-sign/` 这一层**
（取参脚本把 `lakeke.env` 写到 `/work/lakeke-sign/`）：

```bash
git clone --depth 1 https://github.com/LeapYa/lakeke-sign.git /tmp/ls
mkdir -p ~/lakeke/lakeke-sign
cp -r /tmp/ls/. ~/lakeke/lakeke-sign/

cd ~/lakeke/lakeke-sign
cp .env.example lakeke.env      # 按需填：LAKEKE_REGISTER_PHONE、通知渠道等
```

抓身份写入 `lakeke.env`：

```bash
docker exec woc-hook sh -c 'cd /work/lakeke-sign && NODE_PATH=/opt/wmpf/node_modules node cdp_lakeke_ident.js 60'
cat ~/lakeke/lakeke-sign/lakeke.env      # 脱敏看字段是否齐全
```

它会严格按 `appId=wxf8a17a14c0521576` + `mpId=gh_6420f1a617e8` 双重校验挑上下文，
把整组身份（token/openId/unionId/gcId/gameId）写进 `lakeke.env`。

> ⚠️ **别跨账号复用同一个 `lakeke.env`**：token 换成 B 账号、openId 还是 A 的，接口会返 `208 授权码错误`。
> 判断方法：JWT 的 `sub` 就是该账号在辣可可下的 openId，与 env 里的 openId 一比就知道串没串。

新账号（从没在辣可可注册过会员）先注册一次，填好 `LAKEKE_REGISTER_PHONE` 后：

```bash
python3 lakeke_register.py      # 已经是会员会直接跳过
```

## 6. 定时（cron）

```bash
chmod +x lakeke-sign/daily.sh
crontab -e
5 8 * * * LAKEKE_PYTHON=/usr/bin/python3 LAKEKE_NOTIFY_ALWAYS=1 bash ~/lakeke-sign/daily.sh
```

`daily.sh` 每次会：检查 docker / 实例容器 / hook 容器（缺 hook 自动重建）→ 检查辣可可小程序上下文
（不在就调 `reopen_miniapp.py` 自动重开一次）→ 刷新 token（未过期自动跳过）→ 签到 →
按 `RESULT=<code>` 判定 → 通知。

## 7. 通知渠道

`notify.py` 多渠道 fan-out（配了哪个发哪个）。几个实测坑：

| 渠道 | 环境变量 | 关键坑 |
|---|---|---|
| 企业微信机器人 | `WECOM_WEBHOOK` | markdown 上限 4096B；机器人限 20 条/分钟 |
| PushPlus | `PUSHPLUS_TOKEN` | 成功码 `200`；会员 10 万字、**实名只有 2 万字**（脚本自动降级重试） |
| WXPusher | `WXPUSHER_APP_TOKEN` + UIDS/TOPIC_IDS | 成功码是 **1000**，不是 200 |
| 钉钉机器人 | `DINGTALK_ACCESS_TOKEN` +（可选）`DINGTALK_SECRET` | 判定 `errcode=0`；**开了加签必须带 timestamp+sign**，否则 310000 |
| 邮件 | `SMTP_HOST/PORT/USER/PASS/TO` | 465 走 SSL，其它端口自动试 STARTTLS |
| 通用 webhook | `LAKEKE_NOTIFY_URL` | POST JSON `{title, text, msgtype}` |

- 内容按**多版本 + 降级链**准备（full → lite → summary），各渠道按自身字节上限挑第一个不超限的；
  全超限则做 **UTF-8 安全截断**（不会把汉字截半）。
- 一个渠道失败不影响其它渠道。
- `LAKEKE_NOTIFY_ALWAYS=1` 让**成功也发一条**（推荐，否则无法确认它还在跑）。

## 8. 故障对照表

| 现象 | 原因 | 处理 |
|---|---|---|
| `RESULT=208 / 211` | token 失效或身份串了 | 跑 `auth_refresh_node.js` 强制刷新；确认 env 的 openId 与 JWT `sub` 一致 |
| `RESULT=401` | 该账号还不是会员 | 跑 `lakeke_register.py`（API 优先，见 README） |
| `RESULT=402` | 会员卡不可用 | 去小程序看卡状态 |
| `RESULT=105` | 缺参数 / openId 与 memberId 不一致 | 清掉 `lakeke.env` 身份字段重抓（`cdp_lakeke_ident.js`） |
| 实例「桌面长时间未就绪」 | 面板与实例不在同一自定义网络 | 见 §2 坑 1 |
| 微信突然要重新登录 | 实例被看门狗重启（内存超软阈值） | 调高 `WOC_INSTANCE_MEM_SOFT_MB`；重启导致的掉登录无法避免 |
| hook 反复被杀 | 实例重启 → 共享 PID 的 helper 被连坐 | `bash hook_up.sh` 重建；或依赖 `daily.sh` 自愈 |
| 没有 `[frida] script loaded` | WMPF 版本无对应偏移配置 | 核对微信版本与 `frida/config/linux/addresses.*.json` |
| 小程序上下文查不到 | 小程序被关掉了 | `daily.sh` 会自动重开；不在甄选首页时会明确报错（不瞎点） |

## 9. 维护

- **别手动重启实例容器**（会掉登录，要手机确认）。改配置后先看 `docker logs <面板>` 里的
  `[watchdog] 已启用 · soft=... hard=...` 是否符合预期。
- 微信 Linux 版不自动更新，但**别点面板里的「更新微信」**，也别随便升级；升级前先确认新版本
  WMPF 有偏移配置（`bash check_wmpf.sh <实例>`）。漂了怎么办见上面的 2.6。
- 想长期钉住版本：把已知可用的 deb 放自己的静态服务，用 `-e WECHAT_CDN=...` 指向它。
- 日志 `lakeke-sign/daily.log`（追加式），截图 `shots/`。
- 备份 `lakeke.env` 与云微数据卷（`woc-data-*`），换机可直接恢复登录态。

## 附：实测记录（2026-09-23）

- 云微面板 v1.4.9 + `wechat-on-cloud:1.4.9`（微信 Linux 4.1.13.23，WMPF **2.5.6.25665**）
- 设备伪装逐项实测：machine-id `f95c8dbc…`（唯一）、hostname `lenovo-pc-841`、
  `/.dockerenv` 已移除、MAC `00:21:cc:cd:fe:03`（真实 OUI）、os-release `deepin 23`
- hook：`[frida] script loaded, WMPF version: 25665` → `[miniapp] miniapp client connected`
- 两个小程序 appid 包落地，签到页 `pages/sign/index` 可读；`wx.login` 换到 110 分钟有效 token
- **真实签到成功**（小号，新注册会员）：界面「签到成功 · 获得 1 积分 · 已连续签到 1 天」，
  `member/single` 401 → 200，重跑得 `415 今日已签到`
- 无人值守：`daily.sh` 全流程通过（hook 就绪 → 小程序在线 → token 就绪 → R=415）
- 已知缺陷：该小程序**没做 PC 横屏适配**（界面被拉伸），但功能可用；
  屏幕切到 1280x1024 时竖版排版正常（`xrandr -s 1280x1024`）
