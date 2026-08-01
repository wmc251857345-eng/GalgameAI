"""LLM 客户端：OpenAI 兼容协议（/chat/completions）。
覆盖: deepseek / openai / claude(部分) / kimi / qwen / 各类中转(含 Gemini 中转)。
视觉: content 里带 image_url data URL。
"""
import base64
import json
import time

from ..utils import http_session


def _endpoint(cfg):
    name = cfg.get("provider.name", "")
    base = (cfg.get("provider.base_url") or "").rstrip("/")
    if not base:
        base = {
            "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
            "openai": "https://api.openai.com/v1",
            "deepseek": "https://api.deepseek.com/v1",
        }.get(name, "https://api.openai.com/v1")
    return base + "/chat/completions"


def chat(cfg, messages, json_mode=True, vision_image=None, timeout=90):
    api_key = cfg.get("provider.api_key", "")
    if not api_key:
        return None, "未配置 API Key"
    body = {
        "model": cfg.get("provider.model", ""),
        "messages": messages,
        "temperature": 0.3,
    }
    if vision_image:
        last = messages[-1]
        body["messages"][-1] = {
            "role": last["role"],
            "content": [
                {"type": "text", "text": last["content"]},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/jpeg;base64,{vision_image}"}},
            ],
        }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    s = http_session(cfg, proxy_ok=True)
    url = _endpoint(cfg)
    headers = {"Authorization": f"Bearer {api_key}"}
    last = None
    for i in range(3):
        try:
            r = s.post(url, json=body, headers=headers, timeout=timeout)
            if r.status_code == 200:
                return r.json(), None
            if r.status_code == 400 and json_mode:
                body.pop("response_format", None)  # 部分模型不支持 → 重试
                json_mode = False
                continue
            last = RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
            if r.status_code in (401, 403):
                break
        except Exception as e:
            last = e
        time.sleep(2 * (i + 1))
    return None, last


def chat_json(cfg, system, user, vision_image=None):
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    resp, err = chat(cfg, messages, json_mode=True, vision_image=vision_image)
    if err or not resp:
        return None, err
    try:
        content = resp["choices"][0]["message"]["content"].strip()
        if content.startswith("```"):  # 去掉可能的 markdown 包裹
            content = content.split("\n", 1)[1].rsplit("```", 1)[0].strip()
        return json.loads(content), None
    except Exception as e:
        return None, e


def image_to_b64(path, max_bytes=4_000_000):
    """封面转 base64（过大跳过视觉）。"""
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        return base64.b64encode(open(path, "rb").read()).decode()
    except Exception:
        return None


import os  # noqa: E402  (image_to_b64 用到)
