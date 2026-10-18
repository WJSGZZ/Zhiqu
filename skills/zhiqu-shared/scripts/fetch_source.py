#!/usr/bin/env python3
"""取一个官方网址的原文或附件，并在旁边留一份来源记录。

只用 Python 标准库，供高考、读研、求职三个技能共用。一次只取一个明确的公开网址；
不执行网页脚本，不登录，不处理验证码，不伪装浏览器网络特征。取不到就如实记录原因。

用法：
    python3 fetch_source.py URL --output 文件路径 [--referer 入口页] [--form key=value ...]

成功：写出原件和“文件路径.source.json”，退出码 0。
失败：只写“文件路径.source.json”（status=unretrieved、reason、next_action），退出码 2。
来源记录与维护者的个人爬虫共用 source-receipt-v1 格式。
"""
import argparse
import hashlib
import json
import os
import re
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "source-receipt-v1"
RETRY_PAUSE = 1  # 两次尝试之间至少间隔 1 秒
OWN_UA = "Zhiqu-fetch/1.0 (+https://github.com/WJSGZZ/Zhiqu)"
COMMON_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/141.0 Safari/537.36")
MAGIC = {
    ".pdf": (b"%PDF-",),
    ".xlsx": (b"PK\x03\x04",),
    ".docx": (b"PK\x03\x04",),
    ".zip": (b"PK\x03\x04", b"PK\x05\x06"),
    ".xls": (b"\xd0\xcf\x11\xe0", b"<?xml", b"<Workbook"),
    ".doc": (b"\xd0\xcf\x11\xe0",),
}


class Unretrieved(Exception):
    def __init__(self, reason, next_action="manual_download"):
        super().__init__(reason)
        self.reason = reason
        self.next_action = next_action
        self.attempts = []


def now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def ssl_context():
    ctx = ssl.create_default_context()
    if not ctx.get_ca_certs() and os.path.exists("/etc/ssl/cert.pem"):
        # 部分 macOS 版 Python 没有自带根证书；改用系统证书，仍然校验证书。
        ctx = ssl.create_default_context(cafile="/etc/ssl/cert.pem")
    return ctx


def challenge(body, content_type):
    """识别验证码、浏览器校验和登录页；这类页面不能当作原文。"""
    if "html" not in content_type.lower() and not body.lstrip()[:15].lower().startswith((b"<!doctype html", b"<html")):
        return None
    text = body[:262144].decode("utf-8", errors="replace")
    title = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
    heading = title.group(1).strip().lower() if title else ""
    if any(x in heading for x in ("captcha", "人机验证", "安全验证", "验证码")):
        return "验证码或人机验证页"
    if "just a moment" in heading or "cf-chl-" in text:
        return "网站的浏览器校验页"
    if heading in {"login", "sign in", "登录", "用户登录"} or re.search(r"<input\b[^>]*\btype\s*=\s*['\"]?password", text, re.I):
        return "要求登录的页面"
    if re.search(r"<(?:div|iframe)\b[^>]*(?:g-recaptcha|h-captcha|turnstile)", text, re.I):
        return "验证码或人机验证页"
    return None


def check_type(url, body, expect=None):
    suffix = ("." + expect.lstrip(".").lower()) if expect else Path(urllib.parse.urlsplit(url).path).suffix.lower()
    if suffix in MAGIC and not body.lstrip().startswith(MAGIC[suffix]):
        raise Unretrieved(f"文件头与 {suffix} 不符，可能是拦截页或网页；需打开原站核对")


def once(url, *, headers, data, max_bytes, timeout):
    req = urllib.request.Request(url, data=data, headers=headers, method="POST" if data else "GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl_context()) as resp:
            length = resp.headers.get("Content-Length")
            if length and length.isdigit() and int(length) > max_bytes:
                raise Unretrieved(f"文件超过 {max_bytes} 字节上限", "review_budget")
            chunks, size = [], 0
            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_bytes:
                    raise Unretrieved(f"文件超过 {max_bytes} 字节上限", "review_budget")
                chunks.append(chunk)
            return {"url": resp.geturl(), "http_status": resp.status,
                    "content_type": resp.headers.get("Content-Type", ""), "body": b"".join(chunks)}
    except urllib.error.HTTPError as exc:
        if exc.code == 429:
            raise Unretrieved("网站限流（HTTP 429），停止，不重试", "stop_rate_limited")
        if exc.code in (401, 407):
            raise Unretrieved(f"需要登录或授权（HTTP {exc.code}）", "stop_login")
        return {"error": f"HTTP {exc.code}", "http_status": exc.code}
    except (urllib.error.URLError, TimeoutError, ConnectionError, ssl.SSLError) as exc:
        reason = getattr(exc, "reason", exc)
        return {"error": f"网络错误：{reason}"}


def retrieve(url, *, referer=None, form=None, max_bytes=20 * 1024 * 1024, timeout=20, expect=None):
    data = urllib.parse.urlencode(form).encode() if form else None
    plans = [("own_ua", url, {"User-Agent": OWN_UA}),
             ("common_ua", url, dict({"User-Agent": COMMON_UA}, **({"Referer": referer} if referer else {})))]
    if url.startswith("https://") and not data:
        # 部分政府网站的 https 打不开而 http 正常；只对公开只读的 GET 降级。
        plans.append(("http", "http://" + url[len("https://"):], plans[1][2]))
    attempts, last = [], "未尝试"
    try:
        for i, (method, target, headers) in enumerate(plans):
            if i:
                time.sleep(RETRY_PAUSE)
            item = once(target, headers=headers, data=data, max_bytes=max_bytes, timeout=timeout)
            if "error" in item:
                last = item["error"]
                attempts.append({"url": target, "method": method, "reason": last})
                continue
            attempts.append({"url": target, "method": method, "http_status": item["http_status"]})
            blocked = challenge(item["body"], item["content_type"])
            if blocked:
                raise Unretrieved(f"{blocked}；请本人用自己的浏览器打开并保存",
                                  "stop_login" if "登录" in blocked else "manual_download")
            check_type(item["url"], item["body"], expect)
            return item, attempts
        raise Unretrieved(f"几种方式都没取到：{last}")
    except Unretrieved as exc:
        exc.attempts = attempts
        raise


def write_new(path, content):
    with open(path, "xb") as f:
        f.write(content)


def main(argv=None):
    ap = argparse.ArgumentParser(description="取一个官方网址的原文或附件，并留来源记录")
    ap.add_argument("url")
    ap.add_argument("--output", required=True, help="原件保存路径；已存在则拒绝覆盖")
    ap.add_argument("--referer", help="真实的入口页网址（可选）")
    ap.add_argument("--form", action="append", default=[], help="公开查询表单字段 key=value，可重复；只用于只读查询")
    ap.add_argument("--expect", help="附件类型，如 pdf、xlsx；网址看不出扩展名时用")
    ap.add_argument("--max-mb", type=float, default=20)
    ap.add_argument("--timeout", type=float, default=20)
    args = ap.parse_args(argv)

    out = Path(args.output)
    receipt_path = Path(str(out) + ".source.json")
    if urllib.parse.urlsplit(args.url).scheme not in ("http", "https"):
        ap.error("只接受 http 或 https 网址")
    if out.exists() or receipt_path.exists():
        ap.error("输出文件或来源记录已存在，拒绝覆盖")
    form = []
    for pair in args.form:
        if "=" not in pair:
            ap.error(f"--form 需要 key=value：{pair}")
        form.append(tuple(pair.split("=", 1)))

    meta = {"schema_version": SCHEMA, "source_url": args.url, "request_url": args.url,
            "retrieved_at": now(), "retrieval_method": "urllib"}
    try:
        item, attempts = retrieve(args.url, referer=args.referer, form=form or None,
                                  max_bytes=int(args.max_mb * 1024 * 1024), timeout=args.timeout, expect=args.expect)
    except Unretrieved as exc:
        meta.update(status="unretrieved", reason=exc.reason, next_action=exc.next_action, attempts=exc.attempts)
        write_new(receipt_path, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
        print(json.dumps({"status": "unretrieved", "reason": exc.reason, "receipt": str(receipt_path)}, ensure_ascii=True))
        return 2
    write_new(out, item["body"])
    meta.update(status="retrieved", attempts=attempts, final_url=item["url"], http_status=item["http_status"],
                content_type=item["content_type"], bytes=len(item["body"]),
                sha256=hashlib.sha256(item["body"]).hexdigest())
    write_new(receipt_path, json.dumps(meta, ensure_ascii=False, indent=2).encode("utf-8"))
    print(json.dumps({"status": "retrieved", "output": str(out), "bytes": len(item["body"]),
                      "sha256": meta["sha256"]}, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
