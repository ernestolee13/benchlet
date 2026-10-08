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
