# 辣可可每日自动签到

辣可可（小炒黄牛肉）微信小程序「可可会员签到」的自动签到脚本：每天 +1 积分，连续 10/20 天有加赠。

和塔斯汀那套最关键的区别：**辣可可的 token 是短效的**，`/auth/login` 每次下发的 JWT 大约 **1~2 小时**（实测一次 110 分钟，服务端决定，会变），而且只能拿 `wx.login` 的 jsCode 换，服务端没有 refresh 接口。

所以它不是「抓一次跑一个月」，而是**用之前现取 token**。好消息是这一步也能自动化：脚本可以在小程序逻辑层直接调 `wx.login()` 换新 token（`auth_refresh.py`），不需要人手工抓包。

结论：

- ✅ **Windows 本机跑**：完全自动（微信在跑、辣可可开着即可），推荐挂计划任务
- ✅ **常开 Windows 无人值守**：把这套搬到一台常开的机器上（家里旧电脑 / Windows 云主机），
  见 [DEPLOY.md](DEPLOY.md)
- ❌ **GitHub Actions**：已实测否掉。同一个 token 在 09-23 02:45 还返回 `200`，
  到 13:12 变成 `208 授权码错误` —— **服务端确实校验 JWT 的 exp**，
  token 活不过当天，塞进 Secret 等于废纸

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
