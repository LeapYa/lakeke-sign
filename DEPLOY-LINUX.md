# 部署方案：Linux 服务器（无人值守）

> Windows 方案见 [DEPLOY.md](DEPLOY.md)。两种方案的共同前提是：**签到凭证必须在微信里现取现用**
> （jsCode 只能由微信客户端产生，token 只有 1~2 小时且服务端实测校验 `exp`）。
> 区别只在于「让微信一直开着」这件事放在哪个系统上做。

## 一、为什么值得认真考虑 Linux

| 点 | Windows 方案 | Linux 方案 |
|---|---|---|
| 系统成本 | 需要 Windows 授权，云主机更贵 | Linux VPS 便宜得多（可 Docker） |
| 图形会话 | RDP 断开会挂起会话，微信掉线，要额外保活 | 无头跑 Xvfb 即可，不依赖远程桌面 |
| **微信版本** | **自动更新**，一升级 WMPF 偏移全失效，得重新反汇编 | **deb/AppImage 手动装，不自动更新** → 版本可以钉住，偏移长期有效 |
| 偏移配置 | win32 有 53 个版本可选 | linux 目前只有 3 个（14910 / 14978 / 25665），版本必须落在这三个里 |
| 风控 | 数据中心 IP + Server 指纹 | 同样机房 IP，风险相当 |

**关键前提：微信 Linux 版 4.0 起完整支持 PC 小程序**（含支付），也就是说 Linux 上确实存在
WMPF 运行时，可以 hook。官方下载页：<https://linux.weixin.qq.com/>（提供 deb / rpm / AppImage，
x86_64 / arm64 / LoongArch）。

## 二、版本必须是「那三个之一」

WMPFDebugger 的 Linux 偏移配置只有三份：

```
frida/config/linux/addresses.14910.json
frida/config/linux/addresses.14978.json
frida/config/linux/addresses.25665.json
```

启动 hook 时日志会打印实际版本，例如 `[frida] script loaded, WMPF version: 25665`。

- **落在三个之一** → 直接能跑
- **不在** → 要么换一个微信 Linux 版安装包（因为它不自动更新，可以挑版本），
  要么参考项目 README 自己用 IDA 逆 `flue.so`（成本高）
- Linux 版实现会在二进制里正则提取版本号，不需要你手工查

## 三、部署步骤（Ubuntu 22.04/24.04 x86_64，2C4G 起）

### 1. 装微信

```bash
# 官方页面选对应架构的包；社区常用的直链如下（以官网为准）
wget https://dldir1v6.qq.com/weixin/Universal/Linux/WeChatLinux_x86_64.deb
sudo apt install -y ./WeChatLinux_x86_64.deb
```

无头服务器需要图形环境（微信是 GUI 程序）：

```bash
sudo apt install -y xvfb x11vnc
Xvfb :1 -screen 0 1080x1920x24 &
export DISPLAY=:1
wechat &          # 首次需要手机扫码登录：截二维码图发到手机扫
```

> 也可以直接装轻量桌面（xfce），再配 x11vnc，效果更直观。

### 2. 登录并打开一次辣可可

扫码登录后，打开辣可可小程序一次（任意页面即可）。之后保持微信常驻不退出。

### 3. 装 Node + WMPFDebugger

```bash
node --version      # 需要 >= 22
git clone https://github.com/evi0s/WMPFDebugger.git && cd WMPFDebugger
npm install --ignore-scripts --registry https://registry.npmmirror.com

# 手动放 frida 的 Linux 预编译包（版本号按 npm 实际装的 frida 版本改）
curl -L -o frida.tar.gz \
  https://github.com/frida/frida/releases/download/17.18.0/frida-v17.18.0-napi-v8-linux-x64.tar.gz
tar -xzf frida.tar.gz -C node_modules/frida/build --strip-components=1
node -e "require('frida'); console.log('frida OK')"
```

### 4. 起 hook，确认版本

```bash
npx ts-node src/index.ts     # 看日志里的 WMPF version
```

### 5. 部署签到脚本

```bash
git clone https://github.com/LeapYa/lakeke-sign.git && cd lakeke-sign
pip install websocket-client
python sign_now.py           # 会自动 wx.login 换 token → 签到
```

第一次会失败（小程序要在 hook 启动之后重新打开），重开一次辣可可再跑。

### 6. 定时任务

```bash
crontab -e
# 每天 08:00，先确保 DISPLAY 与微信在线
0 8 * * * cd /root/lakeke-sign && DISPLAY=:1 /usr/bin/python3 sign_now.py >> sign.log 2>&1
```

失败告警：`sign_now.py` 失败时退出码为 1，可在脚本后加 `|| <推送命令>`。

## 四、稳定性要点

1. **不要升级微信**。Linux 版不自动更新正是它的优势；升级包一装，WMPF 版本一变，偏移就失效。
2. **Xvfb 常驻**。写进 systemd 或 `@reboot` crontab，保证 DISPLAY 一直在。
3. **微信常驻**。掉登录要手机重扫，尽量减少退出频率。
4. **版本对不上时**先换微信安装包，别急着逆 `flue.so`。

## 五、风险提示

与 Windows 方案同源：长期挂机运行 + 机房 IP，微信《软件许可及服务协议》不欢迎这种用法，
风控可能要求重新验证甚至限制功能。**建议用小号试验，不要用主力号。**

## 六、选型建议

- 手边有闲置笔记本/台式机 → 用 **Windows（DEPLOY.md）**，住宅 IP 风险最低，成本也最低
- 想要省事、便宜、可容器化、且能钉住版本 → 用 **Linux（本文）**
- 两者取 token 的逻辑完全一样，`lakeke-sign` 的脚本跨平台通用（只用 Python 标准库 + websocket-client）
