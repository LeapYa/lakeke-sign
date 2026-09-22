# 部署方案：常开 Windows（无人值守）

> 为什么需要一台常开的 Windows：辣可可的 token 是短效 JWT（1~2 小时），而换 token 必须调
> `wx.login()`，这个 API 只能在微信客户端里执行。所以签到任务必须跑在一台**开着微信**的
> Windows 上。GitHub Actions 上做不到（Linux 没有微信运行时）。

## 一、先选载体（按推荐度排序）

| 载体 | 风控风险 | 成本 | 说明 |
|---|---|---|---|
| **家里旧电脑 / 迷你主机** | **最低** | 电费约 ¥10~30/月 | 住宅 IP + 真实硬件指纹，微信眼里就是台正常电脑。**首选** |
| Windows 云主机 | 中高 | 促销价约 ¥50~100/年起，正常价几十元/月 | 数据中心 IP + Server 系统指纹，微信风控会注意。**不建议用主力微信号** |
| 云电脑 / 云桌面（Win10/11 桌面） | 中 | 约 ¥20~50/月 | 比 Server 镜像像样些，但仍是机房 IP |
| 云手机 + RPA 点击 | 中高 | 约 ¥30~100/月 | 最重、最麻烦，还要模拟点击；本方案不需要 |

> ⚠️ **务必知道的合规与风控风险**：微信《软件许可及服务协议》不欢迎在服务器/虚拟机里长期挂机运行，
> 且风控会依据「数据中心 IP、Server 系统指纹、异常登录地点」判断。轻则要求重新扫码验证，
> 重则限制功能。**强烈建议用小号试，不要拿主力号冒这个险。**
> 家里旧电脑之所以排第一，就是因为它在这些维度上都不异常。

## 二、部署步骤（以云主机/旧机通用）

### 0. 前置

- Windows 10/11 或 Windows Server（**必须带桌面 GUI**，Server Core 跑不了图形程序）
- 内存 ≥ 4GB（微信 + WMPFDebugger + Node 一起跑，2GB 会卡）
- 有图形会话保持在线（见下文「会话保活」）

### 1. 装微信 PC 版

官网下载安装，用**手机扫码登录**（截图二维码发到手机扫，或直接对着屏幕扫）。
登录后**保持登录，不要频繁退出**——反复扫码最容易触发风控。

登录成功后打开一次辣可可小程序（任意页面），确保它能正常运行。

### 2. 装 Node.js（≥ 22 LTS）与 WMPFDebugger

```powershell
node --version   # 需要 >= 22
```

```powershell
git clone https://github.com/evi0s/WMPFDebugger.git
cd WMPFDebugger
npm install --ignore-scripts --registry https://registry.npmmirror.com
```

frida 的 prebuild 二进制要手动放（国内直连 GitHub Release 会很慢，**有代理就挂代理**）：

```powershell
# 先看装的是哪个 frida 版本
node -p "require('./node_modules/frida/package.json').version"
# 对应下载（示例 17.18.0；有代理加 -x http://127.0.0.1:端口）
curl.exe -L -o frida.tar.gz "https://github.com/frida/frida/releases/download/17.18.0/frida-v17.18.0-napi-v8-win32-x64.tar.gz"
tar -xzf frida.tar.gz -C node_modules\frida\build --strip-components=1
node -e "require('frida'); console.log('frida OK')"
```

**关键：偏移配置要与你的 WMPF 版本一致。** 查看版本：任务管理器 → `WeChatAppEx.exe` → 打开文件位置，
路径里 `RadiumWMPF\` 后面那串数字就是（例：`25715`）。确认 `frida\config\win32\addresses.<版本>.json` 存在；
没有就去 [WMPFDebugger PRs](https://github.com/evi0s/WMPFDebugger/pulls) 找，或参考项目 README 自己逆。

### 3. 装 Python 依赖并部署脚本

```powershell
pip install websocket-client
git clone https://github.com/LeapYa/lakeke-sign.git
cd lakeke-sign
```

### 4. 跑通一次

```powershell
# 终端 1：先起 hook，保持不关
cd WMPFDebugger
npx ts-node src/index.ts

# 终端 2：签到（会自动登录 + 签到）
cd lakeke-sign
python sign_now.py
```

看到 `[1/2] detail code=200` + `[2/2] signIn code=200 或 415` 就算通了（415 = 今天已签）。

### 5. 配成无人值守

**a) 开机自启两个常驻进程**（任务计划程序，触发器 `登录时`）：

| 任务 | 命令 | 起始目录 |
|---|---|---|
| WMPFDebugger | `npx ts-node src/index.ts` | `WMPFDebugger` |
| 每日签到 | `python sign_now.py` | `lakeke-sign` |

签到任务用「触发器 → 每天 08:00」，并勾选「如果错过计划，尽快启动」。
WMPFDebugger 用「触发器 → 登录时」，勾选「不管用户是否登录都要运行」会拿不到图形会话，**别勾**。

**b) 会话保活（云主机必做）**

远程桌面**不要用「注销」，用直接关窗口（断开连接）**；注销会杀掉图形会话，微信随之退出。
更省心的做法是配自动登录 + 用 ToDesk / 向日葵之类的常驻远控，保持桌面会话一直存在。

**c) 失败告警**（可选但强烈建议）

云主机上没人看着，失败必须让你知道。最省事的是在脚本外面套一层，失败时发邮件/推送到手机：

```powershell
python sign_now.py; if ($LASTEXITCODE -ne 0) { <发通知> }
```

（`sign_now.py` 失败时退出码为 1，且日志会打印 `::error::` 字样，便于采集。）

## 三、日常维护

| 情况 | 处理 |
|---|---|
| 微信自动升级后 WMPFDebugger 报 `version config not found` | WMPF 版本变了，补 `frida\config\win32\addresses.<新版本>.json`；找不到就先用旧版微信 |
| 微信掉登录 | 手机扫码重登，然后重跑 `sign_now.py` |
| 报 `211 / 208` | token 失效 → `python auth_refresh.py 60 force` 强制重登一次 |
| 报 `105 memberId与openId不一致` | 身份取错（多开微信/多小程序）→ 删掉 `lakeke.env` 重跑 |
| 小程序被微信回收 | 重新打开一次辣可可（任意页面即可） |

## 四、成本参考

- **家里旧电脑**：一次性 0 元（有闲置机器的话），电费约 ¥10~30/月
- **Windows 云主机**：促销价常见 ¥50~100/年（新用户），正常续费约 ¥30~80/月，以官网实时价格为准
- 建议配置：2 核 4GB 起，国内节点（海外节点微信登录更容易触发风控）

## 五、如果「服务端不校验 JWT exp」被证实

那这套部署可以直接省掉：本机登录一次 → 把 token 塞进 GitHub Secret → Actions 定时签到，
就不需要常开机器了。（该结论待验证：见 `expiry_probe.py`。）
