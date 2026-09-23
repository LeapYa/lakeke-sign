# 部署方案：青龙面板

适合已经在用青龙面板的人：把每日签到挂进去，用它现成的定时任务、环境变量管理、任务日志和通知，
不必自己写 cron、也不必另做一个通知配置。

青龙接管的是**调度和通知**这两层。微信那边仍然要按 [DEPLOY-LINUX.md](DEPLOY-LINUX.md)
把「云微实例 + 旁挂 hook」跑起来（步骤 1~5）。**青龙和微信实例必须在同一台宿主机上。**

## 一、装青龙

```bash
mkdir -p ~/ql && cd ~/ql

docker run -d --name qinglong \
  -p 5700:5700 \
  -v $PWD/data:/ql/data \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v $(which docker):/usr/bin/docker \
  --restart unless-stopped \
  whyour/qinglong:latest
```

访问 `http://<机器IP>:5700` 完成初始化。

> **两处挂载不能省**：`daily.sh` 靠 `docker exec` / `docker cp` 操作微信实例和 hook 容器，
> 所以青龙容器必须拿到宿主 docker。`$(which docker)` 是宿主 docker 二进制；
> 也可以进容器 `apt-get install -y docker.io` 装一个客户端。

## 二、把脚本放进青龙

**方式 A（可更新，推荐）**：青龙「订阅管理」添加本仓库地址，脚本会拉到
`/ql/data/repo/<owner>_<repo>/`。之后可以再建一个 `git pull` 任务定期更新。

**方式 B（直接拷）**：

```bash
docker exec qinglong mkdir -p /ql/data/scripts
docker cp lakeke-sign qinglong:/ql/data/scripts/lakeke-sign
```

> ⚠️ **路径要和 hook 容器的挂载对齐**：`cdp_lakeke_ident.js` 等取参脚本会把 `lakeke.env`
> 写到 `/work/lakeke-sign/`，而 `/work` 是 woc-hook 的挂载点。所以 woc-hook 启动时
> `-v` 要指向**同一份脚本目录**，并且保留 `lakeke-sign/` 这一层：
> ```bash
> -v /root/ql/data/scripts:/work
> ```
> 否则会出现「取参写进了 A 目录、签到读的是 B 目录」，表现为 `lakeke.env` 一直不更新。

## 三、环境变量

青龙「环境变量」页添加，任务运行时自动注入：

```
LAKEKE_PYTHON=/usr/bin/python3
WOC_INSTANCE=woc-wx-2ada0225ca
WOC_HOOK=woc-hook
LAKEKE_NOTIFY_ALWAYS=1
WECOM_WEBHOOK=https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxxx
```

> 注意青龙的环境变量是**全局注入**的。`WOC_INSTANCE` 这种名字很少冲突，但如果你别的脚本也用
> `SMTP_*`、`PUSHPLUS_TOKEN`，会一起被注入到那些任务里，按需取舍。

## 四、定时任务

青龙「定时任务」新建：

| 项 | 值 |
|---|---|
| 名称 | 辣可可签到 |
| 命令 | `bash /ql/data/scripts/lakeke-sign/daily.sh` |
| 定时规则 | `5 8 * * *` |

保存后先「运行一次」验证，再看任务日志。

建议再加一条高频的保活任务（小程序被关时提前补开，别等到早上才发现）：

```
名称：辣可可小程序保活
命令：bash /ql/data/scripts/lakeke-sign/daily.sh --ensure-only
定时：0 */2 * * *
```

`--ensure-only` 只做自检与「小程序在线/重开」，不签到，所以可以随便高频跑。
保活跑得勤，早上那次签到基本不会遇到小程序被关的情况。

## 五、依赖

**不需要 pip 装任何东西。** `lakeke_run.py`、`member_info.py`、`notify.py` 全部只用 Python 标准库；
JS 侧（`cdp_*.js`）跑在 woc-hook 容器里，用的是那边装好的 node 与 frida。
青龙镜像自带 python3。

## 六、通知

两条路都行：

1. **用项目自带的 `notify.py`（推荐）**：渠道多（企业微信 / PushPlus / WXPusher / 钉钉 / 邮件 /
   通用 webhook），且会按各渠道字节上限自动降级。只要在青龙环境变量里配好对应变量即可。
2. 用青龙自带的「通知设置」：把结果交给青龙推送。不过「签到成功 / 今日已签 / 失败」的判定仍在
   `daily.sh` 里做，青龙只是搬运，收益不大。

## 七、排查

| 现象 | 原因 |
|---|---|
| 任务日志报 `docker: not found` | 青龙容器没挂 docker 二进制，或没挂 docker.sock |
| 日志报 `Cannot connect to the Docker daemon` | 同上，检查 `-v /var/run/docker.sock:...` |
| 日志报「微信实例容器未运行」 | 云微实例没起，或 `WOC_INSTANCE` 名字写错 |
| 一直提示小程序不在 | 微信没登录、或没打开过辣可可甄选首页 |
| `lakeke.env` 不更新 | hook 容器的 `/work` 与青龙脚本目录不是同一份（见第二节的警告） |

## 八、和直接 cron 的取舍

| | 青龙面板 | 直接 cron |
|---|---|---|
| 界面看日志、改定时 | 有 | 自己看文件 |
| 环境变量集中管理 | 有 | 写在 `.env` / crontab |
| 通知 | 自带，也可用 `notify.py` | 用 `notify.py` |
| 机器上多一个容器 | 是（约 100~200 MB 内存） | 无 |
| 额外要求 | 必须能访问宿主 docker，且与微信实例同机 | 无 |

如果你只是跑这一个签到，直接 cron 更省事；已经在用青龙、或者还要跑别的签到脚本，走青龙顺手。
