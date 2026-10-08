"""팔 레지스트리. OpenRouter 검증 조합표(data/or_verified.json)가 1급 자원이다.

팔 스펙 형식
  qwen                       프리셋 키 (아래 ARMS)
  qwen/qwen3.8-27b@parasail  OpenRouter 모델@provider 핀
  custom:<model>             임의의 OpenAI 호환 엔드포인트. BENCHLET_BASE_URL · BENCHLET_API_KEY 환경변수 둘만 받는다
  jev                        typed 팔 (OpenRouter decisions)
"""
from __future__ import annotations

import json
import os

from ..config import VERIFIED_TABLE, OPENROUTER_BASE_URL

ARMS = {
    "glm":      {"model": "z-ai/glm-4.7-flash",            "provider": "cloudflare",   "in_per_m": 0.0605, "family": "GLM",      "mode": "logprob"},
    "qwen":     {"model": "qwen/qwen3.8-27b",              "provider": "parasail",     "in_per_m": 0.0605, "family": "Qwen",     "mode": "logprob"},
    "deepseek": {"model": "deepseek/deepseek-v4-flash",    "provider": "digitalocean", "in_per_m": 0.14,   "family": "DeepSeek", "mode": "logprob"},
    "ds-low":   {"model": "deepseek/deepseek-v4-flash-0731", "provider": "coreweave",  "in_per_m": 0.018,  "family": "DeepSeek", "mode": "logprob"},
    "ds-high":  {"model": "deepseek/deepseek-v4.1-flash",  "provider": "digitalocean", "in_per_m": 0.30,   "family": "DeepSeek", "mode": "logprob"},
    "gemma":    {"model": "google/gemma-4-31b-it",         "provider": "coreweave",    "in_per_m": 0.09,   "family": "Gemma",    "mode": "logprob"},
    "nemotron": {"model": "nvidia/nemotron-3.5-lightning", "provider": "coreweave",    "in_per_m": 0.06,   "family": "NVIDIA",   "mode": "logprob"},
    "jev":      {"model": "typesafe/jev-1.13",             "provider": "openrouter",   "in_per_m": 0.042,  "family": "Jev",      "mode": "typed"},
}

_FAMILY_HINT = [("deepseek", "DeepSeek"), ("qwen", "Qwen"), ("glm", "GLM"), ("gemma", "Gemma"), ("gemini", "Gemini"),
                ("nemotron", "NVIDIA"), ("jev", "Jev"), ("claude", "Anthropic"), ("gpt", "OpenAI"), ("llama", "Llama"),
                ("mistral", "Mistral"), ("kimi", "Moonshot"), ("minimax", "MiniMax")]


def arm_family(key: str) -> str:
    if key in ARMS:
        return ARMS[key]["family"]
    k = key.lower()
    for hint, fam in _FAMILY_HINT:
        if hint in k:
            return fam
    return key


def verified_table() -> dict:
    return json.loads(VERIFIED_TABLE.read_text(encoding="utf-8"))


def openrouter_extra_body(provider: str | None) -> dict:
    """검증된 호출 템플릿. reasoning 끄기 + provider 핀 + fallbacks 금지."""
    body = {"reasoning": {"enabled": False}}
    if provider and provider != "openrouter":
        body["provider"] = {"only": [provider], "allow_fallbacks": False, "require_parameters": True}
    else:
        body["provider"] = {"require_parameters": True}
    return body


def resolve_arms(specs: list) -> list:
    """팔 스펙 목록 → [{key, model, provider, family, mode, in_per_m, preset, base_url, api_key_env, extra_body}]"""
    out = []
    for spec in specs:
        spec = spec.strip()
        if not spec:
            continue
        if spec in ARMS:
            a = dict(ARMS[spec]); a["key"] = spec; a["preset"] = "openrouter"
        elif spec.startswith("custom:"):
            model = spec.split(":", 1)[1]
            a = {"key": spec, "model": model, "provider": os.environ.get("BENCHLET_PROVIDER") or None,
                 "family": arm_family(model), "mode": "logprob", "in_per_m": float(os.environ.get("BENCHLET_IN_PER_M", "0") or 0),
                 "preset": "custom"}
        else:
            model, _, provider = spec.partition("@")
            a = {"key": spec, "model": model, "provider": provider or None, "family": arm_family(model),
                 "mode": "logprob", "in_per_m": 0.0, "preset": "openrouter"}
            for row in verified_table().get("verified_working", []):
                if row["model"] == model and (not provider or row["provider"] == provider):
                    a.update({"provider": row["provider"], "in_per_m": row.get("in_per_m", 0.0), "family": row.get("family", a["family"])})
        if a["preset"] == "openrouter":
            a["base_url"] = OPENROUTER_BASE_URL
            a["api_key_env"] = "OPENROUTER_API_KEY"
            a["extra_body"] = openrouter_extra_body(a.get("provider")) if a["mode"] != "typed" else {}
        else:
            a["base_url"] = os.environ.get("BENCHLET_BASE_URL", "")
            a["api_key_env"] = "BENCHLET_API_KEY"
            extra = os.environ.get("BENCHLET_EXTRA_BODY")
            a["extra_body"] = json.loads(extra) if extra else {}
        out.append(a)
    return out
