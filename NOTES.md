# 原理与接口

## 签到入口在哪

签到页不在辣可可主小程序里，真实路径：

```
辣可可甄选 (wxb98e6393065cf180)  首页轮播图「每日积分签到」
        ↓ 点击
辣可可 (wxf8a17a14c0521576)     pages/sign/index
        ↓
立即签到
```

直接打开辣可可进不到签到页，启动参数（`gameId` 等）由甄选跳转时带过去。

自动化不需要走这条路径：`gameId` 是长活动常量（活动期到 2028-01），`memberId/cardId/cardNo`
可用 `/api/member/single` 查。日常签到只要**辣可可小程序处于打开状态（任意页面）**即可。

## 接口

| 环节 | 地址 |
|---|---|
| 登录 | `POST wechat.wuuxiang.com/i5xforyou/auth/login`（jsCode → token，form-urlencoded） |
| 解密手机号 | `POST wechat.wuuxiang.com/i5xforyou/fans/sign/decrypt/mini/wechat/phone`（`encryptedPhoneData`+`ivPhone` → 明文） |
| 注册会员 | `POST scrm.wuuxiang.com/crm7game-api/api/member/register`（`mobile` 收明文手机号） |
| 会员信息 | `POST scrm.wuuxiang.com/crm7game-api/api/member/single`（`{gameId, gameType:2, thirdShopId}`，返回 memberId/cardId/cardNo/score） |
| 签到详情 | `POST scrm.wuuxiang.com/crm7game-api/api/game/sign/detail` |
| 执行签到 | `POST scrm.wuuxiang.com/crm7game-api/api/game/sign/signIn` |
| 签到日历 | `POST scrm.wuuxiang.com/crm7game-api/api/game/sign/monthDetail` |

业务接口统一包一层 `{mpId, openId, unionId, data:{...}}`，鉴权走 `Authorization` 头 +
`crm7-mpId` 头（分片键 `csl-GC-Shardingkey` 可选）。

`signIn` 的 data 照小程序源码：

```
{ gameId, memberId, cardId, cardNo, from, thirdShopId }
```

## 响应码（实测）

| code | 含义 |
|---|---|
| `200` | 成功 |
| `415` | 今日已签到 |
| `208` | 授权码错误（token 失效或身份不匹配） |
| `211` | 授权码失效，请刷新重试 |
| `401` | 该账号还不是会员 |
| `402` | 会员卡不可用 |
| `105` | 缺少参数 / memberId 与 openId 不一致 |

## 两件容易踩的事

**两个租户**：甄选与辣可可同属 wuuxiang SaaS，mpId 不同（辣可可 `gh_6420f1a617e8`，
甄选 `gh_08623aa177ad`）。jsCode 由哪个小程序产生，就得配哪个的 mpId 去换 token，配错报
`invalid code`。脚本按 `wx.getAccountInfoSync().miniProgram.appId` 挑上下文。

**token 短效**：JWT，实测 110 分钟有效，服务端校验 `exp`（同一 token 02:45 返 `200`、
13:12 返 `208`）。所以没有任何「抓一次长期用」的做法，只能现取现用。jsonCode 只能由微信客户端
产生，也就不存在纯服务端方案。

## 参数怎么取

WMPF 25715+ 上 `Network` 域不转发事件（`Network.enable` 有回复，但收不到 `requestWillBeSent`），
所以不走抓包，改用 CDP 的 `Runtime` 域在逻辑层直接读：

1. 扫所有 execution context，挑出 `typeof wx === 'object'` 的（AppService）
2. `wx.getStorageSync` 取 token / openId / unionId / mpId / gcId
3. `getCurrentPages()` 读页面 data 取 gameId / memberId / cardId / cardNo
4. 按 `appId` + `mpId` 双重校验确定是辣可可（多个小程序同时开着时只按 appId 会误判）

两个坑：

- **context id 每次连接都重新编号**，枚举和取参必须在同一条连接里完成
- 多个小程序同时运行时，hook 代理会把一次 `Runtime.evaluate` 的结果**回两遍**（两个小程序
  都连着 debug server），脚本取第一份即可

## 为什么必须打开「辣可可」这个小程序

`wx.login()` 在**任何**小程序里都能调，但产出的 jsCode **与 appid 绑死**：哪个小程序调用的，就只能换那个小程序的会话。
实测（`probe_code_binding.js`，收到 3 个不同 code 交叉验证）：

| code 来源 | 配辣可可 mpId | 配甄选 mpId |
|---|---|---|
| 辣可可的 code | ✅ success | ❌ invalid code |
| 甄选的 code ×2 | ❌ invalid code | ✅ success |

所以想拿辣可可的 token，必须让**辣可可那个 appid 的小程序**处于打开状态。这也是历史 bug
`invalid code` 的成因：code 取自甄选上下文、却用辣可可的 mpId 去换。

另一个实测结论：`wx.navigateToMiniProgram`（从小程序里直接跳到另一个小程序）**不能自动化**——
需要真实用户点击手势，程序调用返回 `navigateToMiniProgram:fail can only be invoked by user TAP gesture`。
所以「打开辣可可」这一步只能走 UI（`reopen_miniapp.py`），两条路径都做了：

- 当前是**微信主窗口** → 点搜索框 → 输入「辣可可甄选」→ 点下拉里「最近使用过的小程序」第一条
- 当前是**甄选首页** → 点横幅左下角「点击签到」热区（1280x1024 下约 `0.191W, 0.806H`）
  → 弹「即将打开 辣可可现炒黄牛肉」→ 点允许

## 取证工具

- `capture_reqs.js`：在逻辑层给 `wx.request` 挂钩子，再 `wx.reLaunch` 触发页面重载，
  直接列出小程序真实调用的接口。比抓包省事，今天的接口清单就是这么拿到的。
- `cdp_eval.js`：通用 CDP 执行器，在指定小程序上下文里跑任意 JS（也当健康检查用）。
- `ui_register.py --analyze <png>`：离线校验弹窗识别逻辑，不连微信也能跑。
