# 容器方案选型：风控对抗对比

> 背景：微信 Linux 端会采集**设备指纹**。容器方案最大的风险不是"虚拟化"，而是
> **指纹不像一台独立真实设备**——最典型的是"所有实例共用镜像里烤死的同一个 `machine-id`"，
> 会被判定为设备农场，表现为**登录后立即被以安全原因踢下线、反复循环**。

## 一、结论先行

| 方案 | 风控对抗 | 适合 |
|---|---|---|
| **云微 WechatOnCloud** | ⭐⭐⭐⭐⭐ 唯一内置完整设备伪装 | 要长期挂、在乎风控 → 首选 |
| wechat-selkies + 自加身份钩子 | ⭐⭐⭐ 需自己补 4 项伪装（约 20 行） | 想要单容器轻量 |
| wechat-selkies 原样 | ⭐⭐ 仅数据持久化 | 短期试验 |
| ricwang/docker-wechat | ⭐ 无可查的设备伪装实现 | 只建议小号短测（镜像小、微信版本新） |

## 二、逐项证据（代码/文档级）

| 对抗手段 | 云微 | wechat-selkies | ricwang |
|---|---|---|---|
| 唯一且持久的 `machine-id` | ✅ 首启生成、存数据卷，重启/升级/重建不变 | ❌ 代码中无 `machine-id` 处理 | ❌ 无 |
| 真实 hostname（如 `lenovo-pc-372`） | ✅ 每实例不同且稳定 | ⚠️ 仅支持通过环境变量配 hostname | ❌ 无 |
| 移除 `/.dockerenv` | ✅ | ❌ 无 `dockerenv` 处理 | ❌ 无 |
| 真实网卡 MAC（Intel/Realtek OUI 派生） | ✅ 替代容器默认的 `02/26/ee…`（本地管理位 = 明显非真实硬件） | ❌ | ❌ |
| `os-release` 伪装 deepin 23 | ✅ 可开关 `WOC_SPOOF_OS` | ❌ 无 `os-release` 处理 | ❌ 无 |
| 数据持久化 | ✅ 数据卷 | ✅ `/config` 卷 | ✅ 挂载 `~/.xwechat` |
| 「重置设备 ID」（给已被标记的号换新身份） | ✅ 面板一键：安全 → 重置设备 ID 并重启 | ❌ | ❌ |

证据来源：
- 云微：README 指向 `doc/设备伪装.md`，实现位于 `docker/woc-identity.sh`（启动钩子
  `/custom-cont-init.d/00-woc-identity`，root 身份、在微信启动前执行）
- 另两个仓库：以 `machine-id` / `dockerenv` / `os-release` 做代码搜索，命中数均为 0

## 三、云微自己写的局限（照抄，别当保证）

- **这是"尽力而为"，不是保证。** 风控是持续对抗，腾讯会不断增加新检测维度：
  **X server 厂商串、无 GPU 软渲染、SMBIOS 缺失、行为特征**等，项目只能覆盖已知且可控的部分。
- 已被标记的账号有**冷却期**，换设备 ID 后不一定立刻恢复。
- 有封号风险：在非官方环境运行微信本身违反其使用条款；**强烈建议不要用主力账号**。
- 若伪装后仍被频繁踢，可试 `WOC_SPOOF_OS=0`（排除 os 伪装反而被交叉校验的可能）。

## 四、我们这套签到脚本的特殊要求

选容器方案时，除了风控还要满足两点（否则签到跑不起来）：

1. **要能挂 frida**：容器需要
   `--cap-add=SYS_PTRACE --security-opt seccomp=unconfined`
   （云微的面板建容器时默认不带这两个，需要自己改它的建容器参数；wegchat-selkies 是 `docker run`
   自己写，加参数就行）
2. **WMPF 版本必须落在 WMPFDebugger 的 linux 配置里**：目前只有 `14910 / 14978 / 25665`
   三份。装好微信后启动 hook，看日志 `[frida] script loaded, WMPF version: xxxx`，
   不在三个之一就没法 hook，得换微信安装包版本。

## 五、建议路线

1. **首选**：云微（WechatOnCloud）——设备伪装开箱即有，且支持"重置设备 ID"这个后悔药。
   代价是部署多一层面板，且要自己把 `SYS_PTRACE` 等参数加到实例上。
2. **次选**：wechat-selkies + 在 `/custom-cont-init.d/` 里补一个身份钩子（machine-id / hostname /
   `/.dockerenv` / MAC）。它基于 linuxserver.io 镜像，插件机制现成，20 行脚本能补齐主要短板。
3. **不建议长期挂机**：ricwang/docker-wechat（990★，镜像小、微信版本最新 4.1.13.23），
   但没有可查的设备伪装，属于"能跑但不防风控"。

> 无论选哪个：先用**小号**验证一到两周，确认不掉线、不被踢，再考虑迁主号。
