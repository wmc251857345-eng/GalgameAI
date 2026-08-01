"""通用工具：名称规范化、编码识别、HTTP(代理+重试)、时间。"""
import datetime
import re
import time
import unicodedata

import requests

# ---------- 名称规范化（匹配 key） ----------
_SYMBOLS = re.compile(
    r"[×x・~〜\-_—–\s:：.。·･!！?？()（）\[\]【】<>《》\"'`’‘“”★☆♥♡＊*＋+]+"
)


def normalize(s):
    """全角→半角、小写、去符号空格。用于匹配。"""
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", str(s)).lower()
    return _SYMBOLS.sub("", s)


# ---------- 时间 ----------
def now_iso():
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ---------- 文本文件读取（编码自动检测） ----------
def read_text_file(path, max_chars=4000):
    """自动检测编码读取（Shift-JIS/GBK/UTF-8/BOM），失败返回 ''。"""
    try:
        raw = open(path, "rb").read(max_chars * 4)
    except OSError:
        return ""
    if not raw:
        return ""
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", "ignore")[:max_chars]
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", "ignore")[:max_chars]
    try:
        import charset_normalizer

        best = charset_normalizer.from_bytes(raw).best()
        if best and best.encoding:
            return str(best)[:max_chars]
    except Exception:
        pass
    for enc in ("utf-8", "shift_jis", "gb18030"):
        try:
            return raw.decode(enc)[:max_chars]
        except (UnicodeDecodeError, LookupError):
            continue
    return ""


# ---------- HTTP ----------
def http_session(cfg, proxy_ok=True):
    """requests.Session，按配置注入代理。proxy_ok=False 用于国内直连源(bgm)。"""
    s = requests.Session()
    s.headers["User-Agent"] = "GALA/0.2 (Galgame AI Library Agent)"
    if proxy_ok and cfg.get("proxy.enabled"):
        url = cfg.get("proxy.url", "")
        if url:
            s.proxies = {"http": url, "https": url}
    return s


def http_get_json(session, url, params=None, timeout=15, tries=3):
    last = None
    for i in range(tries):
        try:
            r = session.get(url, params=params, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}")
            if r.status_code in (401, 403, 404, 429):
                break
        except Exception as e:
            last = e
        time.sleep(1.5 * (i + 1))
    raise last


def http_post_json(session, url, json_body=None, timeout=90, tries=3, headers=None):
    last = None
    for i in range(tries):
        try:
            r = session.post(url, json=json_body, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code in (401, 403, 404):
                break
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    raise last


def download_file(session, url, dest, timeout=60):
    """下载到 dest，成功返回 True。"""
    try:
        r = session.get(url, timeout=timeout)
        if r.status_code == 200 and r.content:
            with open(dest, "wb") as f:
                f.write(r.content)
            return True
    except Exception:
        pass
    return False


# ---------- DNS 防污染（DoH + socket 补丁） ----------
import socket  # noqa: E402

_dns_cache = {}  # host -> ip


def doh_resolve(host, timeout=6):
    """DoH 解析（阿里优先，直连/代理自适应），绕过 DNS 污染。返回 IP 或 None。"""
    if host in _dns_cache:
        return _dns_cache[host]
    for url, proxied in (("https://223.5.5.5/resolve", False),
                         ("https://dns.google/resolve", True)):
        try:
            s = requests.Session()
            s.headers["User-Agent"] = "GALA/0.2"
            if proxied:
                s.proxies = {"http": "http://127.0.0.1:7897", "https": "http://127.0.0.1:7897"}
            r = s.get(url, params={"name": host, "type": "A"}, timeout=timeout)
            if r.status_code == 200:
                ips = [a["data"] for a in r.json().get("Answer", []) if a.get("type") == 1]
                if ips:
                    _dns_cache[host] = ips[0]
                    return ips[0]
        except Exception:
            continue
    return None


def patch_dns(host, ip):
    """让 socket.getaddrinfo(host) 返回指定 IP（TLS SNI 仍用原主机名）。幂等。"""
    if getattr(patch_dns, "_patched", None) == (host, ip):
        return
    orig = socket.getaddrinfo

    def patched(name, *a, **kw):
        if name == host:
            name = ip
        return orig(name, *a, **kw)

    socket.getaddrinfo = patched
    patch_dns._patched = (host, ip)
