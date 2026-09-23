# -*- coding: utf-8 -*-
"""
签到结果通知：多渠道 fan-out + 按渠道限额自动降级。

设计是从 Rainyun-Qiandao 那套搬过来的（它踩过的坑这里都保留了）：
  1. **每个渠道的成功码不一样**：PushPlus=200、WXPusher=1000、钉钉 errcode=0、企业微信 errcode=0。
     只看 HTTP 200 会误判成功。
  2. **每个渠道有内容字节上限**，超了直接报错/丢内容：
     企业微信 markdown 4096B（且机器人限 20 条/分钟）、钉钉 markdown ~2万B、
     WXPusher 4万B、PushPlus 会员 10万字但**实名只有 2万字**（所以要有降级重试）。
  3. 内容按 **多版本 + 降级链** 准备，Provider 自己挑第一个不超限的；全超限则**UTF-8 安全截断**
     （不能把多字节汉字截一半）。
  4. 钉钉机器人**开了加签就必须带 timestamp+sign**，否则报 310000。
  5. 一个渠道失败不影响其它渠道。

渠道（按需配环境变量，配了才启用）：
  WECOM_WEBHOOK           企业微信机器人 webhook 完整地址
  PUSHPLUS_TOKEN          PushPlus token
  WXPUSHER_APP_TOKEN      WXPusher appToken（配合 WXPUSHER_UIDS / WXPUSHER_TOPIC_IDS）
  WXPUSHER_UIDS           逗号分隔
  WXPUSHER_TOPIC_IDS      逗号分隔
  DINGTALK_ACCESS_TOKEN   钉钉机器人 access_token
  DINGTALK_SECRET         钉钉机器人加签密钥（可空）
  SMTP_HOST/SMTP_PORT/SMTP_USER/SMTP_PASS/SMTP_TO   邮件
  LAKEKE_NOTIFY_URL       通用 webhook（企业微信/飞书/自建都行，POST JSON）

用法（命令行）：
  python notify.py --title "辣可可签到" --body-file body.md [--status ok|fail]
  python notify.py --title "辣可可签到失败" --text "208 授权码错误" --status fail
  echo "..." | python notify.py --title "辣可可签到" --stdin
作为模块：
  from notify import NotificationManager, build_context
  NotificationManager().send_all("标题", build_context(full_md, short_text))
"""
import argparse
import base64
import hashlib
import hmac
import json
import os
import smtplib
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

LOG_PREFIX = "[notify]"


def log(msg):
    print(f"{LOG_PREFIX} {msg}", flush=True)


# ───────────────────────── 内容版本与降级 ─────────────────────────
def build_context(full_md, short_text=None, title=""):
    """准备多级内容，供各渠道按自身限额挑选"""
    short = short_text or full_md
    md_lite = "\n".join(full_md.splitlines()[:12])
    return {
        "markdown_full": full_md,
        "markdown_lite": md_lite,
        "text_short": short,
        "html_full": md_to_html(full_md, title),
        "html_lite": md_to_html(md_lite, title),
    }


def md_to_html(md, title=""):
    """给只支持 HTML 的渠道（PushPlus/WXPusher）用的极简转换"""
    body = (md.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))
    for a, b in (("**", ""), ("#### ", ""), ("### ", ""), ("## ", ""), ("# ", "")):
        body = body.replace(a, b)
    lines = "".join(f"<p>{ln or '&nbsp;'}</p>" for ln in body.splitlines())
    return (f'<div style="font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'
            f'font-size:14px;line-height:1.6;"><h3>{title}</h3>{lines}</div>')


class Provider:
    """渠道基类：NAME / 成功判定 / 内容限额 / 降级顺序"""
    NAME = "base"
    LIMIT = 0                      # 0 = 不限
    KEYS = ["text_short"]

    def enabled(self):
        return False

    def send(self, title, content, context=None):
        raise NotImplementedError

    def pick(self, context, limit=None):
        lim = self.LIMIT if limit is None else limit
        for k in self.KEYS:
            c = context.get(k) or ""
            if not c:
                continue
            if lim == 0 or len(c.encode("utf-8")) <= lim:
                if k != self.KEYS[0]:
                    log(f"{self.NAME}: 内容降级到 {k}")
                return c
        last = context.get(self.KEYS[-1]) or ""
        if last and lim:
            log(f"{self.NAME}: 所有版本都超限，安全截断到 {lim}B")
            return safe_truncate(last, lim)
        return last

    def post_json(self, url, payload, timeout=15, headers=None, params=None):
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(url, data=body, method="POST", headers={
            "Content-Type": "application/json", **(headers or {})})
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        try:
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                raw = r.read().decode("utf-8", "replace")
            return True, raw
        except urllib.error.HTTPError as e:
            return False, f"HTTP {e.code} {e.read().decode('utf-8', 'replace')[:200]}"
        except Exception as e:
            return False, str(e)


def safe_truncate(content, max_bytes):
    """按字节截断但不能把 UTF-8 汉字截半（Rainyun 那套的坑之一）"""
    data = content.encode("utf-8")
    if len(data) <= max_bytes:
        return content
    suffix = "\n\n...[已截断]"
    keep = max_bytes - len(suffix.encode("utf-8"))
    return data[:keep].decode("utf-8", errors="ignore") + suffix


# ───────────────────────── 各渠道 ─────────────────────────
class WeComProvider(Provider):
    """企业微信机器人：markdown 上限 4096B，机器人限 20 条/分钟"""
    NAME = "企业微信"
    LIMIT = 4000                      # 4096 留余量
    KEYS = ["markdown_full", "markdown_lite", "text_short"]

    def __init__(self, webhook):
        self.webhook = webhook

    def enabled(self):
        return bool(self.webhook)

    def send(self, title, content, context=None):
        payload = {"msgtype": "markdown", "markdown": {"content": f"**{title}**\n{content}"}}
        ok, raw = self.post_json(self.webhook, payload)
        try:
            d = json.loads(raw)
            return (d.get("errcode") == 0), raw
        except Exception:
            return ok, raw


class PushPlusProvider(Provider):
    """PushPlus：成功码 200；会员 10 万字，实名只有 2 万字 → 失败后降级重试"""
    NAME = "PushPlus"
    LIMIT = 90_000
    FALLBACK = 18_000
    KEYS = ["html_full", "html_lite", "text_short"]

    def __init__(self, token):
        self.token = token

    def enabled(self):
        return bool(self.token)

    def _do(self, title, content):
        ok, raw = self.post_json("https://www.pushplus.plus/send", {
            "token": self.token, "title": title, "content": content, "template": "html"})
        try:
            d = json.loads(raw)
            return d.get("code") == 200, raw
        except Exception:
            return ok, raw

    def send(self, title, content, context=None):
        ok, raw = self._do(title, content)
        if ok:
            return True, raw
        log(f"{self.NAME}: 首次失败，降级到实名限额(2万字)重试 —— {raw[:120]}")
        return self._do(title, self.pick(context or {}, self.FALLBACK))


class WXPusherProvider(Provider):
    """WXPusher：成功码是 1000（不是 200），上限约 4 万字"""
    NAME = "WXPusher"
    LIMIT = 36_000
    KEYS = ["html_full", "html_lite", "text_short"]

    def __init__(self, app_token, uids=None, topic_ids=None):
        self.app_token = app_token
        self.uids = [u for u in (uids or "").split(",") if u.strip()]
        self.topics = [t for t in (topic_ids or "").split(",") if t.strip()]

    def enabled(self):
        return bool(self.app_token) and (self.uids or self.topics)

    def send(self, title, content, context=None):
        payload = {"appToken": self.app_token, "content": content, "summary": title,
                   "contentType": 2, "uids": self.uids, "topicIds": self.topics}
        ok, raw = self.post_json("https://wxpusher.zjiecode.com/api/send/message", payload)
        try:
            d = json.loads(raw)
            return d.get("code") == 1000, raw
        except Exception:
            return ok, raw


class DingTalkProvider(Provider):
    """钉钉机器人：errcode=0；markdown 约 2 万字；开了加签必须带 timestamp+sign"""
    NAME = "钉钉"
    LIMIT = 18_000
    KEYS = ["markdown_full", "markdown_lite", "text_short"]

    def __init__(self, token, secret=None):
        self.token = token
        self.secret = secret

    def enabled(self):
        return bool(self.token)

    def send(self, title, content, context=None):
        params = {"access_token": self.token}
        if self.secret:
            ts = str(round(time.time() * 1000))
            string_to_sign = f"{ts}\n{self.secret}"
            digest = hmac.new(self.secret.encode("utf-8"), string_to_sign.encode("utf-8"),
                              digestmod=hashlib.sha256).digest()
            params["timestamp"] = ts
            params["sign"] = urllib.parse.quote_plus(base64.b64encode(digest))
        payload = {"msgtype": "markdown", "markdown": {"title": title, "text": f"# {title}\n\n{content}"}}
        ok, raw = self.post_json("https://oapi.dingtalk.com/robot/send", payload, params=params)
        try:
            d = json.loads(raw)
            return d.get("errcode") == 0, raw
        except Exception:
            return ok, raw


class EmailProvider(Provider):
    """邮件：不限额；465 用 SSL，其它端口试 STARTTLS"""
    NAME = "邮件"
    LIMIT = 0
    KEYS = ["html_full", "markdown_full"]

    def __init__(self, host, port, user, password, to_addr):
        self.host, self.port, self.user = host, int(port), user
        self.password, self.to = password, to_addr

    def enabled(self):
        return all([self.host, self.port, self.user, self.password, self.to])

    def send(self, title, content, context=None):
        try:
            msg = MIMEMultipart()
            msg["From"] = f"lakeke-sign <{self.user}>"
            msg["To"] = self.to
            msg["Subject"] = Header(title, "utf-8")
            msg.attach(MIMEText(content, "html" if content.lstrip().startswith("<") else "plain", "utf-8"))
            if self.port == 465:
                s = smtplib.SMTP_SSL(self.host, self.port, timeout=20)
            else:
                s = smtplib.SMTP(self.host, self.port, timeout=20)
                try:
                    s.starttls()
                except Exception:
                    pass
            s.login(self.user, self.password)
            s.sendmail(self.user, [self.to], msg.as_string())
            s.quit()
            return True, "ok"
        except Exception as e:
            return False, str(e)


class WebhookProvider(Provider):
    """通用 webhook：POST {"text": "...", "title": "..."}，兼容飞书/自建"""
    NAME = "通用webhook"
    LIMIT = 0
    KEYS = ["text_short"]

    def __init__(self, url):
        self.url = url

    def enabled(self):
        return bool(self.url)

    def send(self, title, content, context=None):
        ok, raw = self.post_json(self.url, {"text": f"{title}\n{content}", "title": title,
                                            "msgtype": "text", "text_content": content})
        return ok, raw


def build_providers(env=None):
    e = env or os.environ
    ps = [
        WeComProvider(e.get("WECOM_WEBHOOK", "").strip()),
        PushPlusProvider(e.get("PUSHPLUS_TOKEN", "").strip()),
        WXPusherProvider(e.get("WXPUSHER_APP_TOKEN", "").strip(),
                         e.get("WXPUSHER_UIDS", ""), e.get("WXPUSHER_TOPIC_IDS", "")),
        DingTalkProvider(e.get("DINGTALK_ACCESS_TOKEN", "").strip(),
                         (e.get("DINGTALK_SECRET", "") or "").strip() or None),
        EmailProvider(e.get("SMTP_HOST", "").strip(), e.get("SMTP_PORT", "0") or 0,
                      e.get("SMTP_USER", "").strip(), e.get("SMTP_PASS", ""),
                      e.get("SMTP_TO", "").strip()),
        WebhookProvider(e.get("LAKEKE_NOTIFY_URL", "").strip()),
    ]
    return [p for p in ps if p.enabled()]


class NotificationManager:
    def __init__(self, providers=None):
        self.providers = providers if providers is not None else build_providers()

    def send_all(self, title, context):
        if not self.providers:
            log("没配置任何通知渠道（跳过）。配 WECOM_WEBHOOK / PUSHPLUS_TOKEN / DINGTALK_ACCESS_TOKEN / SMTP_* 任一即可")
            return 0
        ok_count = 0
        for p in self.providers:
            content = p.pick(context)
            n = len(content.encode("utf-8"))
            ok, raw = p.send(title, content, context)
            if ok:
                ok_count += 1
                log(f"{p.NAME}: 发送成功（{n}B）")
            else:
                log(f"{p.NAME}: 发送失败 —— {raw[:200]}")
        return ok_count


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--body-file")
    ap.add_argument("--text")
    ap.add_argument("--stdin", action="store_true")
    ap.add_argument("--status", default="ok", choices=["ok", "fail"])
    a = ap.parse_args()

    if a.body_file:
        full = open(a.body_file, encoding="utf-8").read()
    elif a.text:
        full = a.text
    elif a.stdin:
        full = sys.stdin.read()
    else:
        full = a.title

    short = a.text or full.splitlines()[0] if full else a.title
    ctx = build_context(full, short_text=short, title=a.title)
    for k, v in ctx.items():
        log(f"内容版本 {k}: {len(v.encode('utf-8'))}B")
    n = NotificationManager().send_all(a.title, ctx)
    log(f"完成：{n}/{len(build_providers())} 个渠道成功")
    sys.exit(0 if n > 0 else 1)


if __name__ == "__main__":
    main()
