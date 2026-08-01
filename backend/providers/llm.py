"""LLM 客户端：OpenAI 兼容协议（/chat/completions），支持多提供商轮询。
覆盖: deepseek / openai / claude(部分) / kimi / qwen / 各类中转(含 Gemini 中转)。
视觉: content 里带 image_url data URL。
轮询: 活动提供商(cfg.provider)优先，失败/限速自动切换 providers 池中的下一个（429 后冷却 45s）。
"""
import base64
import json
import os
import time

import requests

# ---------- 多提供商池（轮询/故障转移） ----------
_provider_cooldown = {}  # base_url -> 冷却截止时间戳
_PROVIDER_COOLDOWN_S = 45


def _provider_pool(cfg):
    """候选提供商列表（活动 provider 在前），每项: base_url/api_key/model。"""
    act_url = (cfg.get("provider.base_url") or "").rstrip("/")
    pool = [{
        "base_url": act_url,
        "api_key": cfg.get("provider.api_key") or "",
        "model": cfg.get("provider.model") or "",
    }]
    seen = {act_url}
    for p in cfg.get("providers", []) or []:
        if not p.get("enabled", True):
            continue
        url = (p.get("base_url") or "").rstrip("/")
        if url and url not in seen:
            seen.add(url)
            pool.append({
                "base_url": url,
                "api_key": p.get("api_key") or "",
                "model": p.get("model") or "",
            })
    return pool


def _post_session(cfg, p, body, timeout):
    """向单个提供商发一次请求。返回 (json_resp, err)。"""
    b = dict(body)
    b["model"] = p["model"] or body.get("model", "")  # 每个提供商用自己的模型名
    url = (p["base_url"] or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
    headers = {"Authorization": f"Bearer {p['api_key']}"}
    proxies = None
    if cfg.get("proxy.enabled"):
        u = cfg.get("proxy.url", "")
        if u:
            proxies = {"http": u, "https": u}
    try:
        r = requests.post(url, json=b, headers=headers, timeout=timeout, proxies=proxies)
        if r.status_code == 200:
            return r.json(), None
        return None, RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    except Exception as e:
        return None, e


def _run_pool(cfg, body, timeout):
    """按池顺序尝试：活动提供商优先；失败/限速 → 下一个。返回 (resp, err, used_url)。"""
    now = time.time()
    last = None
    for p in _provider_pool(cfg):
        if not p["api_key"]:
            continue
        if now < _provider_cooldown.get(p["base_url"], 0):
            continue
        resp, err = _post_session(cfg, p, body, timeout)
        if err is None:
            return resp, None, p["base_url"]
        last = err
        if "429" in str(err) or "速率" in str(err) or "rate" in str(err).lower():
            _provider_cooldown[p["base_url"]] = time.time() + _PROVIDER_COOLDOWN_S
    return None, last or RuntimeError("所有 AI 提供商均不可用"), None


def chat(cfg, messages, json_mode=True, vision_image=None, timeout=40):
    """对话（可选 JSON 模式 / 视觉），自动轮询多个提供商。"""
    if not any(p["api_key"] for p in _provider_pool(cfg)):
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
    resp, err, _ = _run_pool(cfg, body, timeout)
    if err is not None:
        # 部分模型不支持 response_format → 去掉后重试一轮
        if json_mode and "response_format" in body and "400" in str(err):
            body.pop("response_format", None)
            resp, err, _ = _run_pool(cfg, body, timeout)
        if err is not None:
            return None, err
    return resp, None


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


def chat_provider(provider, messages, json_mode=True, timeout=40, cfg=None):
    """用指定提供商配置直接对话（设置页"测试"用，不走池）。返回 (resp, err)。"""
    if cfg is None:
        from ..config import Config
        cfg = Config()
    p = {
        "base_url": (provider.get("base_url") or "").rstrip("/"),
        "api_key": provider.get("api_key") or "",
        "model": provider.get("model") or "",
    }
    if not p["api_key"]:
        return None, "未配置 API Key"
    body = {"model": p["model"], "messages": messages, "temperature": 0.3}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    resp, err = _post_session(cfg, p, body, timeout)
    if err and json_mode and "response_format" in body and "400" in str(err):
        body.pop("response_format", None)
        resp, err = _post_session(cfg, p, body, timeout)
    return resp, err


def chat_tools(cfg, messages, tools, tool_choice="auto", timeout=60):
    """带工具调用的对话（AI 管家用），自动轮询多个提供商。返回原始响应。"""
    if not any(p["api_key"] for p in _provider_pool(cfg)):
        return None, "未配置 API Key"
    body = {
        "model": cfg.get("provider.model", ""),
        "messages": messages,
        "temperature": 0.3,
        "tools": tools,
        "tool_choice": tool_choice,
    }
    resp, err, _ = _run_pool(cfg, body, timeout)
    return resp, err


def image_to_b64(path, max_bytes=4_000_000):
    """封面转 base64（过大跳过视觉）。"""
    try:
        if os.path.getsize(path) > max_bytes:
            return None
        return base64.b64encode(open(path, "rb").read()).decode()
    except Exception:
        return None
