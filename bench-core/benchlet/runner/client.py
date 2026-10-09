"""OpenAI 호환 chat completions 한 종류만 말한다. base_url · api_key · model · extra_body 넷으로 추상화.

게이트웨이별 분기 코드는 두지 않는다. 벤더 확장(OpenRouter 의 provider·reasoning)은 extra_body 로 들어온다.
typed 팔(Jev)은 OpenRouter decisions 엔드포인트 하나뿐이라 프리셋 안에서만 쓴다.
"""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.request
from urllib.parse import urlparse

LETTERS = "ABCDEFGHIJKLMN"
# 선택지가 LETTERS 보다 많으면(라우터·의도 분류 77~150개) 글자 대신 라벨 이름을 답하게 한다 (mode=label, 확률 없음)
LABEL_MAX_TOKENS = 48


def match_label(text: str, labels: list) -> int | None:
    """모델이 낸 텍스트에서 라벨 하나를 고른다. 정확 일치 → 대소문자·공백·따옴표 무시 → 유일한 부분 일치. 못 고르면 None."""
    if not text:
        return None
    t = text.strip()
    if t.startswith("{"):
        try:
            obj = json.loads(t)
            if isinstance(obj, dict) and isinstance(obj.get("label"), str):
                t = obj["label"]
        except json.JSONDecodeError:
            pass
    first = t.split("\n", 1)[0].strip().strip("`\"'「」 .:").strip()
    if first in labels:
        return labels.index(first)
    def norm(x):
        return "".join(ch for ch in x.lower() if ch.isalnum())
    nf = norm(first)
    if nf:
        hits = [i for i, l in enumerate(labels) if norm(l) == nf]
        if len(hits) == 1:
            return hits[0]
        hits = [i for i, l in enumerate(labels) if norm(l) in nf or nf in norm(l)]
        if len(hits) == 1:
            return hits[0]
    return None


class ChatClient:
    def __init__(self, base_url: str, api_key: str, extra_body: dict | None = None, timeout: int = 90):
        self.base_url = base_url.rstrip("/")
        self._key = api_key
        self.extra_body = extra_body or {}
        self.timeout = timeout

    @property
    def host(self) -> str:
        return urlparse(self.base_url).netloc

    RETRY_CODES = (429, 500, 502, 503, 504)
    RETRY_WAITS = (1.0, 2.0, 4.0, 8.0, 16.0)         # 제공자 속도 제한(429)은 동시 호출에서 흔하다. 지수 대기 뒤 다시 시도

    def _post(self, url: str, body: dict):
        req_bytes = json.dumps(body).encode()
        headers = {"Authorization": "Bearer " + self._key, "Content-Type": "application/json"}
        t0 = time.time()
        err = None
        for attempt in range(len(self.RETRY_WAITS) + 1):
            req = urllib.request.Request(url, data=req_bytes, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read()), int((time.time() - t0) * 1000), None
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:160].replace(self._key, "***")
                err = f"HTTP {e.code} {msg}"
                if e.code not in self.RETRY_CODES or attempt == len(self.RETRY_WAITS):
                    break
            except Exception as e:                       # noqa: BLE001
                err = type(e).__name__
                if attempt == len(self.RETRY_WAITS):
                    break
            time.sleep(self.RETRY_WAITS[attempt])
        return None, int((time.time() - t0) * 1000), err

    def chat(self, model: str, prompt: str, **params):
        body = {"model": model, "messages": [{"role": "user", "content": prompt}]}
        body.update(self.extra_body)
        body.update(params)
        return self._post(self.base_url + "/chat/completions", body)

    # ── 확률 팔: 첫 토큰 로그확률 ───────────────────────────────────────────
    def logprob_choice(self, model: str, prompt: str, n_labels: int, in_per_m: float = 0.0) -> dict:
        resp, ms, err = self.chat(model, prompt, max_tokens=1, temperature=0, logprobs=True, top_logprobs=8)
        out = {"ms": ms, "err": err, "probs": None, "mass": None, "provider": None, "reasoning_tokens": None,
               "in_tok": 0, "cost": 0.0, "has_logprobs": False, "raw_text": None}
        if err:
            return out
        u = resp.get("usage") or {}
        out["in_tok"] = u.get("prompt_tokens") or 0
        out["cost"] = out["in_tok"] / 1e6 * in_per_m
        out["provider"] = resp.get("provider")
        out["reasoning_tokens"] = ((u.get("completion_tokens_details") or {}).get("reasoning_tokens"))
        ch = (resp.get("choices") or [{}])[0]
        out["raw_text"] = ((ch.get("message") or {}).get("content") or "")[:8]
        probs, mass, note = read_probs(resp, n_labels)
        out["has_logprobs"] = note not in ("logprobs 없음", "top_logprobs 없음")
        out["probs"], out["mass"] = probs, mass
        if probs is None:
            out["err"] = note
        return out

    # ── 생성 팔: 로그확률이 없을 때 강등. 정확도만 ───────────────────────────
    def generate_choice(self, model: str, prompt: str, n_labels: int, in_per_m: float = 0.0) -> dict:
        resp, ms, err = self.chat(model, prompt, max_tokens=4, temperature=0)
        out = {"ms": ms, "err": err, "pred_index": None, "in_tok": 0, "cost": 0.0, "provider": None, "raw_text": None}
        if err:
            return out
        u = resp.get("usage") or {}
        out["in_tok"] = u.get("prompt_tokens") or 0
        out["cost"] = out["in_tok"] / 1e6 * in_per_m
        out["provider"] = resp.get("provider")
        text = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        out["raw_text"] = text[:8]
        for chx in text:
            if chx.upper() in LETTERS[:n_labels]:
                out["pred_index"] = LETTERS.index(chx.upper())
                break
        if out["pred_index"] is None:
            out["err"] = "답 글자를 못 읽음"
        return out

    # ── 라벨 팔: 선택지가 많을 때 라벨 이름을 생성시킨다. 확률 없음 ──────────
    def label_choice(self, model: str, system: str, user: str, labels: list, in_per_m: float = 0.0) -> dict:
        resp, ms, err = self.chat(model, system + "\n\n" + user, max_tokens=LABEL_MAX_TOKENS, temperature=0)
        out = {"ms": ms, "err": err, "pred_index": None, "in_tok": 0, "cost": 0.0, "provider": None, "raw_text": None,
               "answer_format": "label-name"}
        if err:
            return out
        u = resp.get("usage") or {}
        out["in_tok"] = u.get("prompt_tokens") or 0
        out["cost"] = out["in_tok"] / 1e6 * in_per_m
        out["provider"] = resp.get("provider")
        text = (((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()
        out["raw_text"] = text[:60]
        out["pred_index"] = match_label(text, labels)
        if out["pred_index"] is None:
            out["err"] = "라벨 이름을 못 읽음"
        return out

    # ── typed 팔: OpenRouter decisions ────────────────────────────────────
    def decisions(self, url: str, model: str, state: str, questions: dict, in_per_m: float = 0.0):
        resp, ms, err = self._post(url, {"model": model, "state": state, "questions": questions})
        out = {"ms": ms, "err": err, "in_tok": 0, "cost": 0.0, "model": None, "answers": {}}
        if err:
            return out
        u = resp.get("usage") or {}
        out["in_tok"] = u.get("input_tokens") or u.get("prompt_tokens") or 0
        out["cost"] = out["in_tok"] / 1e6 * in_per_m
        out["model"] = resp.get("model")
        out["answers"] = resp.get("answers") or {}
        return out


def read_probs(resp: dict, n_labels: int):
    """상위 로그확률에서 라벨 글자만 뽑아 라벨 집합 안에서 재정규화한다. (probs, mass, note)"""
    ch = (resp.get("choices") or [{}])[0]
    toks = ((ch.get("logprobs") or {}).get("content")) or []
    if not toks:
        return None, None, "logprobs 없음"
    top = toks[0].get("top_logprobs") or []
    if not top:
        return None, None, "top_logprobs 없음"
    want = set(LETTERS[:n_labels])
    raw = {}
    for t in top:
        tok = (t.get("token") or "").strip()
        if tok in want and tok not in raw:
            raw[tok] = math.exp(t["logprob"])
    if not raw:
        return None, 0.0, "라벨 토큰이 상위에 없음"
    tot = sum(raw.values())
    probs = [raw.get(LETTERS[i], 0.0) / tot for i in range(n_labels)]
    return probs, round(tot, 4), "ok"


# ── Anthropic Messages API. 로그확률이 없어 생성(글자) 또는 라벨(json_schema enum) 팔로만 쓴다 ──────────
# 가격 (USD / 1M 토큰): 입력, 캐시 읽기, 캐시 쓰기(5분), 출력. 모델 id 접두로 맞춘다. 없으면 0 으로 두고 비용을 기록하지 않는다
# 출처: platform.claude.com/docs/en/about-claude/pricing (2026-10-09 확인). 입력, 캐시 읽기, 캐시 쓰기 5분, 출력
ANTHROPIC_PRICES = {
    "claude-haiku-5-5":  (0.10, 0.01, 0.125, 0.50),
    "claude-haiku-4-5":  (1.00, 0.10, 1.25, 5.00),
    "claude-sonnet-5-5": (2.00, 0.10, 2.50, 10.00),
    "claude-opus-5-5":   (4.00, 0.20, 5.00, 20.00),
    "claude-fable-5-1":  (10.00, 0.25, 12.50, 50.00),
}


def anthropic_price(model: str) -> tuple:
    for k, v in ANTHROPIC_PRICES.items():
        if model.startswith(k):
            return v
    return (0.0, 0.0, 0.0, 0.0)


class AnthropicClient(ChatClient):
    VERSION = "2023-06-01"

    def _post(self, url: str, body: dict):
        req_bytes = json.dumps(body).encode()
        headers = {"x-api-key": self._key, "anthropic-version": self.VERSION, "Content-Type": "application/json"}
        t0 = time.time()
        err = None
        for attempt in range(len(self.RETRY_WAITS) + 1):
            req = urllib.request.Request(url, data=req_bytes, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as r:
                    return json.loads(r.read()), int((time.time() - t0) * 1000), None
            except urllib.error.HTTPError as e:
                msg = e.read().decode(errors="replace")[:200].replace(self._key, "***")
                err = f"HTTP {e.code} {msg}"
                if e.code == 529:                       # overloaded
                    pass
                elif e.code not in self.RETRY_CODES or attempt == len(self.RETRY_WAITS):
                    break
            except Exception as e:                       # noqa: BLE001
                err = type(e).__name__
                if attempt == len(self.RETRY_WAITS):
                    break
            time.sleep(self.RETRY_WAITS[min(attempt, len(self.RETRY_WAITS) - 1)])
        return None, int((time.time() - t0) * 1000), err

    def _messages(self, body: dict):
        """thinking 을 끈다(Haiku 5.5 는 기본 켜짐이라 작은 max_tokens 에서 빈 응답이 온다, 2026-10-09 실측).
        적응형 thinking 모델이 disabled 를 400 으로 거부하면 필드를 빼고 한 번 더 보낸다. temperature 는 보내지 않는다(신형이 거부)."""
        b = dict(body); b.setdefault("thinking", {"type": "disabled"})
        resp, ms, err = self._post(self.base_url + "/messages", b)
        if err and "HTTP 400" in err and "thinking" in b:
            b.pop("thinking", None)
            resp, ms2, err = self._post(self.base_url + "/messages", b); ms += ms2
        return resp, ms, err

    @staticmethod
    def _text(resp: dict) -> str:
        return "".join(c.get("text", "") for c in (resp.get("content") or []) if c.get("type") == "text")

    @staticmethod
    def _usage(resp: dict, model: str) -> tuple:
        """(prompt_tokens 합계, 비용 USD)"""
        u = resp.get("usage") or {}
        i, cr, cw, o = (u.get("input_tokens") or 0, u.get("cache_read_input_tokens") or 0,
                        u.get("cache_creation_input_tokens") or 0, u.get("output_tokens") or 0)
        pi, pcr, pcw, po = anthropic_price(model)
        return i + cr + cw, (i * pi + cr * pcr + cw * pcw + o * po) / 1e6

    def chat(self, model: str, prompt: str, **params):
        """OpenAI 호환 모양으로 돌려준다(choices[0].message.content, usage.prompt_tokens). logprobs 는 없다."""
        # 글자 답 하나지만 적응형 thinking 이 켜진 모델은 생각 블록이 예산을 먹으므로 넉넉히 준다. 텍스트 블록만 읽는다
        body = {"model": model, "max_tokens": 512, "messages": [{"role": "user", "content": prompt}]}
        resp, ms, err = self._messages(body)
        if err:
            return None, ms, err
        toks, cost = self._usage(resp, model)
        return {"choices": [{"message": {"content": self._text(resp)}}], "usage": {"prompt_tokens": toks},
                "_cost": cost, "_stop": resp.get("stop_reason")}, ms, None

    def generate_choice(self, model: str, prompt: str, n_labels: int, in_per_m: float = 0.0) -> dict:
        """글자 답을 json_schema enum 으로 강제한다. 자유 생성이면 Haiku 5.5 가 풀이를 먼저 쓰고 마지막에 답을 두어
        첫 글자 파서가 풀이 속 글자(E 등)를 집는다(2026-10-10 실측, mmlu-pro). enum 이면 다른 팔의 첫 토큰과 같은 「즉답」이다."""
        letters = list(LETTERS[:n_labels])
        schema = {"type": "object", "properties": {"answer": {"type": "string", "enum": letters}},
                  "required": ["answer"], "additionalProperties": False}
        body = {"model": model, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}],
                "output_config": {"format": {"type": "json_schema", "schema": schema}}}
        fmt = "json-schema-enum"
        resp, ms, err = self._messages(body)
        if err and "HTTP 400" in err and "output_config" in err:
            body.pop("output_config"); fmt = "letter-text"
            resp, ms2, err = self._messages(body); ms += ms2
        out = {"ms": ms, "err": err, "pred_index": None, "in_tok": 0, "cost": 0.0, "provider": "anthropic", "raw_text": None,
               "answer_format": fmt}
        if err:
            return out
        out["in_tok"], out["cost"] = self._usage(resp, model)
        text = self._text(resp).strip()
        out["raw_text"] = text[:24]
        ans = None
        if text.startswith("{"):
            try:
                ans = str(json.loads(text).get("answer", "")).strip().upper()
            except json.JSONDecodeError:
                ans = None
        if ans is None:
            # 자유 텍스트 폴백: 한 글자 답이거나 첫 줄의 첫 글자만 믿는다. 풀이 속 글자는 집지 않는다
            first = text.split("\n", 1)[0].strip().strip("*()[]「」.: ")
            ans = first.upper() if len(first) == 1 else None
        if ans in letters:
            out["pred_index"] = letters.index(ans)
        else:
            out["err"] = "답 글자를 못 읽음"
        return out

    def label_choice(self, model: str, system: str, user: str, labels: list, in_per_m: float = 0.0) -> dict:
        """라벨 목록은 system 블록에 두고 프롬프트 캐시를 건다. 답은 json_schema enum 으로 강제한다."""
        schema = {"type": "object", "properties": {"label": {"type": "string", "enum": list(labels)}},
                  "required": ["label"], "additionalProperties": False}
        # 적응형 thinking 이 켜진 모델(disabled 거부)은 생각 토큰이 예산을 먹는다. 200 이면 Sonnet 5.5 가 5건 중 1건 max_tokens 로 끊겼다
        body = {"model": model, "max_tokens": 1024,
                "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                "messages": [{"role": "user", "content": user}],
                "output_config": {"format": {"type": "json_schema", "schema": schema}}}
        fmt = "json-schema-enum"
        resp, ms, err = self._messages(body)
        if err and "HTTP 400" in err and "output_config" in err:
            body.pop("output_config"); body["max_tokens"] = LABEL_MAX_TOKENS; fmt = "label-name"
            resp, ms2, err = self._messages(body); ms += ms2
        out = {"ms": ms, "err": err, "pred_index": None, "in_tok": 0, "cost": 0.0, "provider": "anthropic",
               "raw_text": None, "answer_format": fmt}
        if err:
            return out
        out["in_tok"], out["cost"] = self._usage(resp, model)
        u = resp.get("usage") or {}
        out["cache_read"] = u.get("cache_read_input_tokens") or 0
        text = self._text(resp).strip()
        out["raw_text"] = text[:60]
        out["pred_index"] = match_label(text, labels)
        if out["pred_index"] is None:
            out["err"] = "라벨 이름을 못 읽음" + (f" (stop={resp.get('stop_reason')})" if resp.get("stop_reason") != "end_turn" else "")
        return out
