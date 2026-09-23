# 辣可可每日自动签到

辣可可（小炒黄牛肉）微信小程序「可可会员签到」的自动签到脚本：每天 +1 积分，连续 10/20 天有加赠。

和塔斯汀那套最关键的区别：**辣可可的 token 是短效的**，`/auth/login` 每次下发的 JWT 大约 **1~2 小时**（实测一次 110 分钟，服务端决定，会变），而且只能拿 `wx.login` 的 jsCode 换，服务端没有 refresh 接口。

所以它不是「抓一次跑一个月」，而是**用之前现取 token**。好消息是这一步也能自动化：脚本可以在小程序逻辑层直接调 `wx.login()` 换新 token（`auth_refresh.py`），不需要人手工抓包。

结论：

- ⭐ **Linux 容器无人值守（首推）**：微信 Linux 4.1.13 + 云微容器 + WMPFDebugger hook，
  全链路已实测跑通（含真实签到成功）。Linux 版微信**不自动更新**，能把 WMPF 版本钉住（25665），
  恰好治了 Windows 方案「微信一升级偏移全失效」的老毛病。部署见 **[DEPLOY-LINUX.md](DEPLOY-LINUX.md)**
- ✅ **常开 Windows 无人值守**：把这套搬到一台常开的 Windows（家里旧电脑 / 云主机），
  见 [DEPLOY.md](DEPLOY.md)
- ✅ **Windows 本机跑**：完全自动（微信在跑、辣可可开着即可），适合先试水
- ❌ **GitHub Actions**：已实测否掉。同一个 token 在 09-23 02:45 还返回 `200`，
  到 13:12 变成 `208 授权码错误` —— **服务端确实校验 JWT 的 exp**，
  token 活不过当天，塞进 Secret 等于废纸

## 三分钟上手（Linux 容器）

```bash
# 0) 装 Docker，然后按 DEPLOY-LINUX.md 部署云微 + 微信实例 + 扫码登录
# 1) 挂 hook（旁挂容器，共享实例 PID/网络命名空间）
bash hook_up.sh                      # 重建 helper + 起 WMPFDebugger + 校验
# 2) 抓身份（容器内跑，Windows 连不到实例 netns 里的 62000）
docker exec woc-hook sh -c 'cd /work/lakeke-sign && \
  NODE_PATH=/opt/wmpf/node_modules node cdp_lakeke_ident.js 60'
# 3) 一键：自检 → 自愈 → 刷新 token → 签到 → 通知
bash lakeke-sign/daily.sh
```

配置项见 [`.env.example`](.env.example)（复制成 `lakeke.env`，已被 .gitignore 忽略）。

## 通知渠道

`notify.py` 多渠道 fan-out，配了哪个发哪个（搬自 Rainyun-Qiandao 那套，含它的踩坑经验）：

| 渠道 | 环境变量 | 关键坑 |
|---|---|---|
| 企业微信机器人 | `WECOM_WEBHOOK` | markdown 上限 4096B；机器人限 20 条/分钟 |
| PushPlus | `PUSHPLUS_TOKEN` | 成功码 `200`；会员 10 万字、**实名只有 2 万字**（脚本自动降级重试） |
| WXPusher | `WXPUSHER_APP_TOKEN` + UIDS/TOPIC_IDS | 成功码是 **1000**，不是 200 |
| 钉钉机器人 | `DINGTALK_ACCESS_TOKEN` +（可选）`DINGTALK_SECRET` | 判定 `errcode=0`；**开了加签必须带 timestamp+sign** |
| 邮件 | `SMTP_HOST/PORT/USER/PASS/TO` | 465 走 SSL，其它端口自动试 STARTTLS |
| 通用 webhook | `LAKEKE_NOTIFY_URL` | POST JSON `{title,text,msgtype}` |

内容按**多版本 + 降级链**准备（full → lite → summary），各渠道按自身字节上限挑第一个不超限的，
全超限则做 **UTF-8 安全截断**（不会把汉字截半）；一个渠道失败不影响其它渠道。
`LAKEKE_NOTIFY_ALWAYS=1` 可让成功也发一条。

## Linux 容器路线：已实测跑通（含真实签到成功）

不是纸上推演，是跑完的：微信 Linux 版 4.1.13（WMPF `25665`）在容器里

1. 打开辣可可甄选 → 点首页轮播图 → 跳转辣可可 → 进签到页 ✓
2. `auth_refresh_node.js` 调 `wx.login` 换新 token（110 分钟有效）✓
3. `cdp_lakeke_ident.js` 严格按 appId+mpId 抓整组身份 ✓
4. **新账号首次注册会员** → 注册完页面自动签到：界面显示
   「签到成功 · 恭喜您获得 1 积分 · 已连续签到 1 天」✓
5. 再跑 `lakeke_run.py` → `415 今日已签到` ✓

### 注册会员：API 优先，不弹窗

签到接口要 `memberId/cardId/cardNo`，这些只有**会员**才有。新账号要么走微信手机号授权弹窗，
要么直接调注册接口——**后者是纯 API，零 UI**：

```
POST /crm7game-api/api/member/register
body { mpId, openId, unionId, data:{ mobile, gameId, thirdShopId, byInviteCode } }
```

`mobile` 是**明文手机号**（加密串只在走微信弹窗那条路才需要，用
`POST /fans/sign/decrypt/mini/wechat/phone` 解密）。所以：

> 别把「包解密」和「手机号解密」搞混：`.wxapkg` 的 V1MMWX 密钥能从 AppID 推出来（所以我们
> 能拆包）；而手机号 `encryptedData` 是用 **session_key** 加密的，session_key 只能拿
> **AppSecret** 去 `code2Session` 换 —— AppSecret 在 wuuxiang 服务端。整个小程序包里搜不到
> 任何 `secret`，客户端从不碰 `code2Session`/`session_key`，只把自己拿到的
> `encryptedData`+`iv` 转交给服务端解。**所以我们不需要自己解密，也用不着 AppSecret。**

| 环境变量 | 作用 |
|---|---|
| `LAKEKE_REGISTER_MODE` | `api`（默认，有手机号时）/ `ui` / `auto` |
| `LAKEKE_REGISTER_PHONE` | 手机号，走 API 注册用它 |
| `LAKEKE_REGISTER_PHONE_INDEX` | 只在走 UI 弹窗兜底时用：选第几个号码（从 1 开始）。只有一个号码时不用设 |

```powershell
python lakeke_register.py      # 已是会员则跳过；不是则按上面配置注册
```

走 UI 兜底时会调 `ui_register.py`（在容器内执行，用 `xdotool` + `ffmpeg` 截屏判位，
不依赖 OCR）：

- 弹窗识别靠**白卡宽度区间**——签到页白底是通栏（≈0.98 屏宽），弹窗白卡只有 0.3~0.95
- 手机号列表用**已勾选旁边那颗绿色 ✓** 当锚点，按行距往上数，得出有几个号码
- 每一步都截图到 `shots/reg_*.png`；识别不了就**报错退出，不瞎点**
- 屏幕太矮会把弹窗按钮切掉，脚本会自动 `xrandr -s 1280x1024`

> 另一个取证手段：`capture_reqs.js` 在逻辑层给 `wx.request` 挂钩子 + `wx.reLaunch` 触发页面重载，
> 直接列出小程序真实调用的接口（比抓包省事）。

## 无人值守：`daily.sh`

一条命令跑完「自检 → 补自愈 → 刷新 token → 签到 → 失败告警」，可挂 cron：

```bash
# Linux 常开机器
0 8 * * * bash /path/to/lakeke-sign/daily.sh
```

```powershell
# Windows 计划任务：程序用 bash，参数是 daily.sh 绝对路径
```

它会依次检查（任一步失败就告警退出，不会装作成功）：

| 步骤 | 失败时 |
|---|---|
| Docker 引擎 / 微信实例容器在跑 | 告警退出 |
| 旁挂 hook 容器在跑，且日志有 `script loaded` | 自动 `hook_up.sh` 重建 |
| 辣可可小程序在线（CDP 查上下文） | 调 `reopen_miniapp.py` 自动重开一次 |
| 刷新 token（未过期会自己跳过） | 告警退出 |
| 签到 | 按 `RESULT=<code>` 判定：`200` 成功 / `415` 今日已签 / `402` 卡不可用 / `208·211` token 被拒 |

可选环境变量：

```
WOC_INSTANCE=woc-wx-2ada0225ca        微信实例容器名
LAKEKE_PYTHON=<python 绝对路径>        Windows 侧 python
LAKEKE_NOTIFY_URL=<企业微信机器人 webhook>   失败时 POST 文本告警
```

> ⚠️ `daily.sh` 只认 `lakeke_run.py` 最后那行 `RESULT=<code>`。**别用 `grep code=` 判断成功**——
> 「查询签到详情」那行也是 `code=200`，今天就是这么误报过一次「签到成功」而实际是 415。

自动重开的边界（`reopen_miniapp.py`）：已校准的是「当前画面为**辣可可甄选首页**（能看到红色
`每日积分签到` 轮播图）→ 点 banner → 弹跳转窗 → 点允许」这条路径，并带护栏：中段红色占比不到
35% 就**不点**、存截图退出。如果微信停在别的界面（比如主窗口），它会明确报错让你人工切到甄选首页，
而不是瞎点。


## 签到入口的位置（容易踩）

签到**不在辣可可主小程序里**。真实路径是：

```
辣可可甄选（wxb98e6393065cf180）首页轮播图
        ↓ 点击
辣可可（wxf8a17a14c0521576）pages/sign/index
        ↓
立即签到
```

直接打开辣可可进不到签到页——启动参数（gameId 等）是甄选那边跳转带过来的。

对自动化来说这反而无所谓：`gameId` 是长活动常量（活动期到 2028-01），`memberId/cardId/cardNo` 可以用 `/api/member/single` 直接查，所以**日常签到不需要进签到页，只要辣可可小程序开着（任意页面）即可**。

## 原理

| 环节 | 地址 |
|---|---|
| 登录 | `wechat.wuuxiang.com/i5xforyou/auth/login`（jsCode → token，form-urlencoded） |
| 会员信息 | `scrm.wuuxiang.com/crm7game-api/api/member/single`（空 data 即可，返回 memberId/cardId/cardNo） |
| 签到 | `scrm.wuuxiang.com/crm7game-api/api/game/sign/signIn` |

请求统一包一层：`{mpId, openId, unionId, data:{...}}`，鉴权走 `Authorization` 头 + `crm7-mpId` 头（可选 `csl-GC-Shardingkey`）。

> ⚠️ 甄选和辣可可**同属 wuuxiang SaaS 但是两个租户**（辣可可 mpId `gh_6****17e8`，甄选 mpId `gh_08623aa177ad`）。jsCode 由哪个小程序产生，就必须配哪个的 mpId 去换 token，否则 `invalid code`。`auth_refresh.py` 已按 `wx.getAccountInfoSync().miniProgram.appId` 挑上下文。

响应码（实测）：

| code | 含义 |
|---|---|
| `200` | 成功 |
| `415` | 今日已签到 |
| `208` | 授权码错误 |
| `211` | 授权码失效，请刷新重试 |

海外 IP **没有 WAF 拦截**（实测境外出口照样返回业务 JSON），这一点比塔斯汀省心。

## 用法

### 1. 环境（只需一次）

WMPFDebugger（Frida hook 微信小程序运行时）：

```powershell
git clone https://github.com/evi0s/WMPFDebugger.git
cd WMPFDebugger
npm install --ignore-scripts --registry https://registry.npmmirror.com
# 手动下载 frida prebuild 放到 node_modules\frida\build\
# frida/config/win32/ 下需要有你 WMPF 版本对应的 addresses.<version>.json
npx ts-node src/index.ts
```

Python 侧：

```powershell
pip install websocket-client cryptography
```

### 2. 一键签到

先启动 WMPFDebugger，再打开辣可可小程序（**任意页面即可，不用走甄选轮播图**），然后：

```powershell
python sign_now.py
```

脚本会先 `wx.login` 换一个新 token，再用 token 调签到接口。全程不需要手工抓包、不需要点任何按钮。

### 3. 挂计划任务（可选）

Windows 任务计划程序里新建任务，`python <路径>\sign_now.py`，每天一个时间触发。前提是那时微信在跑、辣可可小程序已打开。

想看 token 还剩多久：`python check_token_exp.py`（只打印长度和过期时间，不打印明文）。

## 参数怎么取的

WMPF 25715 上 **Network 域不转发事件**（`Network.enable` 有回复，但收不到 `requestWillBeSent`），所以不走抓包，改用 CDP 的 Runtime 域：

1. 扫所有 execution context，找到 `typeof wx === 'object'` 的那些（AppService）
2. `wx.getStorageSync` 取 token / openId / unionId / mpId / gcId
3. `getCurrentPages()` 读页面 data 取 gameId / memberId / cardId / cardNo（所以要进签到页）
4. 取字段最多的那个上下文即为辣可可

两个坑：

- **context id 每次连接都会重新编号**，枚举和取参必须在同一条连接里完成（见 `cdp_get_params.py`）
- 微信多开时会有多个 AppService 上下文，且部分上下文的 `wxscAuth` 没有 appId 字段，不能用 appId 一刀切过滤，否则会把辣可可误杀

详见 `cdp_get_params.py`。

## 文件

| 文件 | 用途 |
|---|---|
| `sign_now.py` | 一键：取参 + 签到（推荐入口） |
| `cdp_get_params.py` | 从小程序取参数，写入 `lakeke.env`（不打印明文） |
| `lakeke_run.py` | 读 `lakeke.env` 跑签到，只打印接口 code/msg |
| `lakeke_sign.py` | 环境变量版，给 CI / Actions 用 |

## 注意

- `lakeke.env` 里有你的真实 token，**不要提交**（`.gitignore` 已忽略）
- token 约 20 分钟失效，取完立刻用
- 小程序没有手机号/短信登录，token 只能在微信里拿，无法服务端自举

> 仅供学习交流，请勿用于商业用途或违反平台规则。
