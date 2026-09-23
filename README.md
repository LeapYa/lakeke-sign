# lakeke-sign

辣可可（小炒黄牛肉）微信小程序「可可会员签到」的自动签到：每天 +1 积分，连续 10/20 天有加赠。
脚本在小程序逻辑层直接调 `wx.login()` 续 token，不用手工抓包，也不用点界面。**已实测跑通，包含一次真实签到成功。**

## 走哪条路

|  | 方案 | 说明 |
|---|---|---|
| ⭐ | **Linux 容器**（首推） | 微信 Linux 版不自动升级，WMPF 版本能钉住（25665），绕开「微信一升级偏移全失效」的老问题。→ [DEPLOY-LINUX.md](DEPLOY-LINUX.md) |
| ✅ | **青龙面板** | 已在用青龙的话顺手：用它现成的定时任务、环境变量、日志、通知。→ [DEPLOY-QINGLONG.md](DEPLOY-QINGLONG.md) |
| ✅ | **Windows**（常开机器或本机） | 家里旧电脑 / Windows 云主机，或先在本机试水。→ [DEPLOY.md](DEPLOY.md) |
| ❌ | GitHub Actions | 不可行，原因见下 |

不确定选哪个的话：先用 Windows 本机方案跑一次（约 20 分钟），确认账号和链路可用，再决定放哪台机器上长期跑。

**为什么 GitHub Actions 不可行**：token 是短效 JWT，实测 110 分钟（有效期由服务端下发时决定，会变），
且服务端确实校验 `exp`——同一个 token 在 09-23 02:45 还返回 `200`，到 13:12 就成了 `208 授权码错误`。
而 jsCode 只能由微信客户端产生、服务端没有 refresh 接口，所以必须有个微信环境现取现用。

**资源占用**（实测）：内存约 **1.9 GiB**（微信实例 1.2 G 空闲 / 1.8 G 跑起小程序，hook 0.47 G，面板 0.12 G），
磁盘约 **6 GB**；建议 **2 核 4 GiB** 起步，单核会卡。

> 三篇部署文档**互相独立**，选一篇从头看到尾即可，不需要来回跳。里面有重复内容是刻意的。

## 文档

| 文档 | 什么时候看 |
|---|---|
| [DEPLOY-LINUX.md](DEPLOY-LINUX.md) | 部署（首推）：Linux 容器 + cron，含载体选型、资源占用、故障对照表 |
| [DEPLOY-QINGLONG.md](DEPLOY-QINGLONG.md) | 部署：青龙面板调度，含容器装配与定时任务 |
| [DEPLOY.md](DEPLOY.md) | 部署：Windows（常开机器 / 本机），含成本参考 |
| [CONTAINER-OPTIONS.md](CONTAINER-OPTIONS.md) | 选容器项目时看：三个项目的设备伪装能力逐项对比 |
| [NOTES.md](NOTES.md) | 接口、响应码、签到入口位置、参数怎么取 |
| [.env.example](.env.example) | 所有配置项，复制成 `lakeke.env` 用 |

## 配置

```bash
cp .env.example lakeke.env     # 每篇部署文档里也有对应的配置步骤
```

最常要填的两个：

- `LAKEKE_REGISTER_PHONE`：账号还不是会员时，注册用哪个手机号（走 API，不弹窗）
- 通知渠道：`WECOM_WEBHOOK` / `PUSHPLUS_TOKEN` / `DINGTALK_ACCESS_TOKEN` / `SMTP_*` 任一

## 脚本清单

**取参 / 续凭证**（Linux 方案里跑在 hook 容器内，需 `NODE_PATH=/opt/wmpf/node_modules`）

| 文件 | 用途 |
|---|---|
| `cdp_lakeke_ident.js` | 抓整组身份写入 `lakeke.env`（按 appId+mpId 双重校验上下文） |
| `auth_refresh_node.js` | 调 `wx.login` 换新 token（未过期自动跳过） |
| `cdp_eval.js` | 通用 CDP 执行器，在指定小程序上下文里跑 JS；也当健康检查 |
| `capture_reqs.js` | 给 `wx.request` 挂钩子，列出小程序真实调用的接口 |
| `cdp_get_params_node.js` | 早期取参脚本（从页面 data 取 memberId 等，已被 ident 版取代） |

**签到**

| 文件 | 用途 |
|---|---|
| `lakeke_run.py` | 读 `lakeke.env` 签到，只打印 code/msg，末行输出 `RESULT=<code>` |
| `lakeke_sign.py` | 环境变量版，供 CI 用 |
| `member_info.py` | 打印脱敏会员摘要（积分 / 卡号） |

**注册会员**（账号还不是会员时，每个账号一次）

| 文件 | 用途 |
|---|---|
| `lakeke_register.py` | 注册入口。默认走 API（给明文手机号），也可切 UI 兜底 |
| `ui_register.py` | UI 兜底：驱动微信原生授权弹窗（选号按 `LAKEKE_REGISTER_PHONE_INDEX`） |

**无人值守**

| 文件 | 用途 |
|---|---|
| `daily.sh` | 每日入口：自检 → 自愈 → 刷新 → 签到 → 通知；`--ensure-only` 只保活不签到 |
| `hook_up.sh` | 重建旁挂 hook 容器并起 WMPFDebugger |
| `reopen_miniapp.py` | 小程序被关掉时自动重开（从甄选首页轮播图进） |
| `notify.py` | 多渠道通知，按各渠道字节上限自动降级 |

**Windows 本机方案**

| 文件 | 用途 |
|---|---|
| `sign_now.py` | 一键：取参 + 签到（本机入口） |
| `cdp_get_params.py` | 从 AppService 取参写入 `lakeke.env` |
| `auth_refresh.py` | Windows 侧 token 刷新 |
| `check_token_exp.py` | 看 token 还剩多久（不打印明文） |

## 已知限制

- token 1~2 小时过期（服务端校验 `exp`），jsCode 只能由微信客户端产生，所以纯云端跑不了，
  必须有微信环境现取现用。
- 辣可可小程序没做 PC 横屏适配，界面被拉伸；功能可用，屏幕切到 1280x1024 时排版正常。
- 首次注册会员要过一次手机号授权。若提供明文手机号可直接调注册接口，不必点界面。
- 只在微信 Linux 4.1.13（WMPF 25665）容器 与 Windows 桌面版上实测过。

> 仅供学习交流，请勿用于商业用途或违反平台规则。
