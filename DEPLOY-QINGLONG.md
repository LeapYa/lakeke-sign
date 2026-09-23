# 部署方案：青龙面板

适合已经在用青龙面板的人：把每日签到挂进去，用它现成的定时任务、环境变量管理、任务日志和通知，
不必自己写 cron、也不必另做一套通知配置。

**前提**：青龙与微信实例必须跑在**同一台宿主机**上（青龙要调用宿主 docker 去操作微信容器）。
本文从零写到能跑，照着做完即可。

**资源**：微信实例 1.2 GiB（跑起小程序 1.8 GiB）+ hook 0.47 GiB + 云微面板 0.12 GiB + 青龙约 0.2 GiB，
合计约 **2.5 GiB 内存**、约 **6 GB 磁盘**；建议 **2 核 4 GiB** 起步。

---

## 第一部分：把微信容器跑起来

### 1. 装 Docker

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER && newgrp docker
```

### 2. 部署微信实例（云微 WechatOnCloud）

云微是三个容器方案里唯一内置完整设备伪装的项目（对比见 [CONTAINER-OPTIONS.md](CONTAINER-OPTIONS.md)）。

```bash
mkdir -p ~/woc && cd ~/woc
curl -fsSLO https://raw.githubusercontent.com/Gloridust/WechatOnCloud/main/docker-compose.yml
```

编辑 `docker-compose.yml`：**删掉 `- /dev:/host-dev:ro`**（无摄像头时不需要，部分环境挂载会失败）。

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
# 默认软阈值 1500MiB 太低（跑起小程序实测到 1.8G），看门狗会「柔和重启」实例，
# 而重启 = 微信掉登录（要手机确认）+ hook 容器被连坐带走
WOC_INSTANCE_MEM_SOFT_MB=2800
WOC_INSTANCE_MEM_HARD_MB=4000
```

```bash
docker compose up -d
```

> **坑**：`docker compose` 若报 WSL 相关错误（Windows 上会遇到），改用等价的 `docker run`，
> 并**必须给面板和实例指定同一个自定义网络**——默认 bridge 没有容器名 DNS，而面板按容器名反代实例，
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
| 想换密码 | 改 `~/woc/.env` 的 `WOC_PASSWORD` 后重建面板；微信实例在数据卷里，不受影响 |

> 注意本方案有两个 `.env`，别搞混：**`~/woc/.env` 是云微面板的**（面板密码、内存阈值），
> **`lakeke.env` 是签到脚本的**（身份、token、通知）。青龙环境变量页里配的是后者。

校验设备伪装（应看到唯一 machine-id、像个人电脑的 hostname、`/.dockerenv` 已移除、真实 OUI 的 MAC）：

```bash
docker exec <实例容器名> sh -c 'cat /etc/machine-id; hostname; \
  [ -e /.dockerenv ] && echo "dockerenv 还在(未伪装)" || echo "dockerenv 已移除 ✓"; \
  cat /sys/class/net/eth0/address; grep PRETTY_NAME /etc/os-release'
```

### 2.5 装完先验版本（不通过就别往下走）

要能被 hook，**WMPF 版本必须落在 WMPFDebugger 的 linux 偏移配置里** —— 上游目前只有三份：
`addresses.14910.json` / `14978` / `25665`（分别对应 WMPF 1.4.9.10 / 1.4.9.78 / **2.5.6.65**）。

配置文件名 = `addresses.<WMPF 去掉点>+<build>.json`。**要看的是 WMPF 版本，不是微信版本号。**

```bash
bash check_wmpf.sh <实例容器名>
```

看到 `[OK]` 再继续。看到 `[FAIL]` 先别往下走——按它给的选项处理（最省事的是把最接近的配置
改名试挂，同一 WMPF `x.y.z` 下不同 build 的偏移可能一样）。

> ⚠️ **别点面板里的「更新微信」。** 它下的是官方不带版本号的直链，永远拿最新版；新版 WMPF
> 一旦没有对应配置，hook 就挂不上。官方 CDN 也没有带版本号的地址（四种命名实测全 404）。
>
> 万一漂了，三条路（成本从低到高）：
>
> 1. 把最接近的配置复制成新的号试挂（同一 WMPF `x.y.z` 下不同 build，偏移可能一样）
> 2. `bash auto_offsets.sh <实例容器名>` —— 本项目自带离线反解工具，自己算出偏移并装进
>    WMPFDebugger（已在 WMPF 25665 与 14978 上逐字段验证）
> 3. `bash fetch_wechat_deb.sh 4.1.13.23 ./wechat-cdn` —— 从归档仓库按版本下载并校验 sha256，
>    把该目录挂到静态服务，启动实例时加
>    `-e WECHAT_CDN=https://<你的镜像>/weixin/Universal/Linux`（`wechat-ctl.sh` 原生支持）
>
> 已知可用：微信 Linux **4.1.13.23** / WMPF **2.5.6.25665** / deb 231,359,624 字节 /
> sha256 `b7d0f8d53e9f648bc2c77a6096a04100d008f2d9f0d3988a2a4859b5992aca0a`。
> 实测微信小版本升级不一定换 WMPF：官方 deb 包里 4.1.13.9 与 4.1.13.23 的 `WeChatAppEx`
> 字节完全相同（都是 WMPF 25665）。

### 3. 打开小程序（脚本全自动，不需要先人工走一遍）

`reopen_miniapp.py` 自己就能打开：**小程序面板**（侧边栏顶部那组**最后一个**按钮）→ 面板右上角**放大镜**
→ 输入 **辣可可现炒黄牛肉** → **按回车** → 在结果卡片里点 **辣可可现炒黄牛肉i**。

> ⚠️ 搜「辣可可现炒黄牛肉」会出来**两个同名号**：不带 `i` 的（扫码点餐）是餐饮/商城号；
> 签到要的是 **`辣可可现炒黄牛肉i`**（只有它显示 `积分 / NQ=卡号`，那个卡号要和 `lakeke.env`
> 里的 `LAKEKE_CARDNO` 对得上）。脚本按**窗口标题精确等于**判定，开错了会关掉再试下一张卡片。
> 这条路走的是商店搜索，**不依赖账号历史** —— 新号同样能搜到，所以不需要「首次人工打开一次」。

| 小程序面板里的搜索结果（两条同名，选带 i 的那条） | 手动签到入口（甄选首页横幅，自动化用不到） |
|---|---|
| ![搜索打开小程序](docs/images/01-open-in-wechat.png) | ![轮播图与跳转确认](docs/images/02-banner-jump.jpg) |

`wx.login` 的 jsCode 与 appid 绑定，只有辣可可那个小程序在运行，才能换到它的 token。
签到完 `daily.sh` 会**主动把它关掉**（省内存，见下节），下次签到再自动打开 —— 不用你管。

### 4. 把脚本放到青龙的脚本目录

先定好一个宿主机目录作为「脚本目录」，后面青龙和 hook 容器都指到它：

```bash
SCRIPTS=/root/ql/data/scripts        # 与青龙的数据卷同盘，方便它读取
mkdir -p $SCRIPTS
git clone --depth 1 https://github.com/LeapYa/lakeke-sign.git /tmp/ls
cp -r /tmp/ls/lakeke-sign $SCRIPTS/  # 保持 lakeke-sign/ 这一层
```

### 5. 挂 hook 容器（旁挂，不动云微的实例）

云微建的实例没有 `CAP_SYS_PTRACE`，frida attach 不了，所以旁挂一个共享命名空间的 helper：

```bash
WX=<实例容器名>                      # 例 woc-wx-2ada0225ca
VOL=woc-data-${WX#woc-wx-}           # 云微的数据卷名

docker run -d --name woc-hook \
  --pid=container:$WX \
  --network=container:$WX \
  --cap-add=SYS_PTRACE --security-opt seccomp=unconfined \
  -v $SCRIPTS:/work \
  -v $VOL:/config:ro \
  node:22-slim sleep infinity
```

> `-v $SCRIPTS:/work` 必须指向**上面那份脚本目录**。取参脚本会把 `lakeke.env` 写到
> `/work/lakeke-sign/`，青龙执行任务时读的是同一个文件，两边路径不一致就会出现
> 「`lakeke.env` 一直不更新」。
>
> 两个 `--pid` / `--network` **都必须是 `container:`**。只共享 PID 不共享网络的话，
> 小程序连不上 `ws://localhost:9421`（那是实例自己 netns 里的地址），hook 日志不会出现 `[miniapp] connected`。

装 WMPFDebugger 与 Linux 版 frida：

```bash
git clone --depth 1 https://github.com/evi0s/WMPFDebugger.git /tmp/wmpfd
docker exec woc-hook sh -c '
  mkdir -p /opt/wmpf && cd /tmp/wmpfd 2>/dev/null
  cp -r /tmp/wmpfd/src /tmp/wmpfd/package.json /tmp/wmpfd/tsconfig.json /tmp/wmpfd/frida /opt/wmpf/
  cd /opt/wmpf
  npm i --ignore-scripts --registry=https://registry.npmmirror.com --no-audit --no-fund
  mkdir -p node_modules/frida/build
  curl -fsSL -o /tmp/f.tar.gz https://github.com/frida/frida/releases/download/17.18.0/frida-v17.18.0-napi-v8-linux-x64.tar.gz
  tar -xzf /tmp/f.tar.gz -C node_modules/frida/build --strip-components=1
  node -e "console.log(require(\"frida\").version)"
'
```

> `npm i --ignore-scripts` 会跳过 frida 的 install 脚本，JS 包装层不会被生成。
> 需要从一份在 Windows 上正常装过的 clone 里，把 `node_modules/frida/build/src` 拷过来补上
> （Linux 的 `.node` 用上面下载的那份）。
>
> **WMPF 版本必须落在 `frida/config/linux/` 的配置里**（当前 14910 / 14978 / 25665）。
> 微信 Linux 4.1.13 实测是 **25665**。

```bash
bash hook_patch.sh woc-hook           # 必要！见下面「两个补丁」那段
docker commit woc-hook woc-hook:1     # 固化，之后重建不必重装（补丁也一起固化了）
docker exec -d woc-hook sh -c 'cd /opt/wmpf && node node_modules/ts-node/dist/bin.js src/index.ts > /tmp/wmpf.log 2>&1'
docker exec woc-hook tail -5 /tmp/wmpf.log   # 期望：[frida] script loaded, WMPF version: 25665
```

> **为什么必须打 `hook_patch.sh`** —— 它给 WMPFDebugger 打两个补丁：
>
> **① 场景号白名单**：`frida/hook.js` 只在**场景号白名单**内才把 scene 改写成 1101，从而打开小程序的
> devtools 通道。而**从「小程序面板 → 搜索 → 结果卡片」打开小程序时场景号是 `1183`**
> （实测 4.1.13.23 / 4.1.1.8 / 4.1.1.4 / 4.0.0.30 上都是这个号），不在上游白名单里 →
> 小程序**不会连 `ws://localhost:9421`** → CDP 拿不到身份、刷不了 token、签不了到。
> 现象：日志里没有 `[miniapp] miniapp client connected`。补丁除了加 1183，还加了诊断日志，
> 以后换版本/换入口时用 `--debug-frida` 就能看到 `[hook] scene NOT in whitelist: N`，把 N 加进白名单即可。
>
> **② 老版本的版本号探测回退**：上游只用 `wmpf_release/<tag>_<x.y.z>` 串取版本号（4.1.x 才有），
> 4.0.x 及更早没有这个串 → 会直接抛 `[frida] error in find wmpf version` 起不来。补丁加了回退正则，
> 对新版本无影响。

### 6. 抓身份写入 lakeke.env

```bash
docker exec woc-hook sh -c 'cd /work/lakeke-sign && \
  NODE_PATH=/opt/wmpf/node_modules node cdp_lakeke_ident.js 60'
cat $SCRIPTS/lakeke-sign/lakeke.env      # 脱敏看字段是否齐全
```

它会按 `appId=wxf8a17a14c0521576` + `mpId=gh_6420f1a617e8` 双重校验挑上下文，写入整组身份。

> 别跨账号复用同一个 `lakeke.env`：token 换成 B 账号、openId 还是 A 的，接口会返 `208 授权码错误`。
> 判断方法：JWT 的 `sub` 就是该账号在辣可可下的 openId，与 env 里的 openId 一比就知道串没串。

---

## 第二部分：用青龙来调度

### 7. 装青龙

```bash
mkdir -p ~/ql && cd ~/ql

docker run -d --name qinglong \
  -p 5700:5700 \
  -v ~/ql/data:/ql/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(which docker):/usr/bin/docker \
  --restart unless-stopped \
  whyour/qinglong:latest
```

访问 `http://<机器IP>:5700` 完成初始化。

> **两处挂载不能省**：`daily.sh` 靠 `docker exec` / `docker cp` 操作微信实例与 hook 容器，
> 青龙必须拿到宿主 docker。`$(which docker)` 是宿主 docker 二进制，也可以进容器
> `apt-get install -y docker.io` 装一个客户端。
>
> 青龙的数据卷要包含上面那个 `$SCRIPTS` 目录（本文用 `~/ql/data/scripts`），
> 这样青龙读到的脚本和 hook 的 `/work` 是同一份。

### 8. 青龙里配环境变量

「环境变量」页添加，任务运行时自动注入：

```
LAKEKE_PYTHON=/usr/bin/python3
WOC_INSTANCE=woc-wx-2ada0225ca
WOC_HOOK=woc-hook
LAKEKE_NOTIFY_ALWAYS=1
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
```

> 青龙的环境变量是**全局注入**的。`WOC_INSTANCE` 这类名字很少冲突，但 `SMTP_*`、`PUSHPLUS_TOKEN`
> 若你别的任务也用到，会一起被注入，按需取舍。

### 9. 定时任务

| 名称 | 命令 | 定时规则 |
|---|---|---|
| 辣可可签到 | `bash /ql/data/scripts/lakeke-sign/daily.sh` | `5 8 * * *` |
| 辣可可保活（可选） | `bash /ql/data/scripts/lakeke-sign/daily.sh --ensure-only` | `0 */2 * * *` |

签到任务跑完会**关掉小程序与面板**（省内存，实测省 ~220 MB，峰值只在签到那 1~2 分钟出现），
下次签到自己重开，多花约 1 分钟。如果你更在意这点时间，设 `LAKEKE_KEEP_OPEN=1` 让它常开。

保活任务是**可选**的：它只做自检与「小程序在线/重开」，不签到。挂了它小程序就基本常驻在线
（内存一直高位，但与上面的省内存目标相反，二选一）。两条都先「运行一次」验证，再看任务日志。

### 10. 依赖

**不需要 pip 装任何东西。** `lakeke_run.py`、`member_info.py`、`notify.py` 只用 Python 标准库；
JS 侧（`cdp_*.js`）跑在 woc-hook 里，用那边装好的 node 与 frida。青龙镜像自带 python3。

### 11. 通知

两条路：

1. **用项目自带的 `notify.py`（推荐）**：渠道多（企业微信 / PushPlus / WXPusher / 钉钉 / 邮件 /
   通用 webhook），会按各渠道字节上限自动降级。在上面的环境变量里配好对应变量即可。
2. 用青龙自带的「通知设置」：把结果交给青龙推送。不过「签到成功 / 今日已签 / 失败」的判定在
   `daily.sh` 里做，青龙只是搬运。

---

## 排查

| 现象 | 原因 |
|---|---|
| 任务日志报 `docker: not found` | 青龙容器没挂 docker 二进制，或没挂 docker.sock |
| 报 `Cannot connect to the Docker daemon` | 同上，检查 `-v /var/run/docker.sock:...` |
| 「微信实例容器未运行」 | 云微实例没起，或 `WOC_INSTANCE` 名字写错 |
| 一直提示小程序不在 | 微信没登录，或面板搜索没打开成功（看 `shots/reopen_*.png`；认准带 `i` 的那个号） |
| `lakeke.env` 不更新 | hook 容器的 `/work` 与青龙脚本目录不是同一份（见第 5 步的说明） |
| 实例「桌面长时间未就绪」 | 面板与实例不在同一自定义网络（见第 2 步的坑） |
| 微信突然要重新登录 | 实例被看门狗重启（内存超软阈值），调高 `WOC_INSTANCE_MEM_SOFT_MB` |
| `RESULT=208 / 211` | token 失效或身份串了 → 重跑 `cdp_lakeke_ident.js` |
| `RESULT=401` | 该账号还不是会员 → 跑 `lakeke_register.py`（配 `LAKEKE_REGISTER_PHONE`） |
| `RESULT=402` | 会员卡不可用，去小程序看卡状态 |

## 和直接 cron 的取舍

| | 青龙面板 | 直接 cron |
|---|---|---|
| 界面看日志、改定时 | 有 | 自己看文件 |
| 环境变量集中管理 | 有 | 写在 `.env` / crontab |
| 通知 | 自带，也可用 `notify.py` | 用 `notify.py` |
| 机器上多一个容器 | 是（约 200 MB 内存） | 无 |
| 额外要求 | 必须能访问宿主 docker，且与微信实例同机 | 无 |

只跑这一个签到的话，直接 cron 更省事（见 [DEPLOY-LINUX.md](DEPLOY-LINUX.md) 第六节）；
已经在用青龙、或者还要跑别的签到脚本，走青龙顺手。
