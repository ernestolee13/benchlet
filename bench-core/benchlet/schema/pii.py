"""개인정보·시크릿 정규식 스캔. 히트가 하나라도 있으면 게시하지 않는다.

사용자 금지어(개인 계정명·회사 관련어)는 로컬 파일에서만 읽는다(config.BANNED_TERMS_FILE).
"""
from __future__ import annotations

import re
from typing import Iterable

PATTERNS = {
    "email": re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    "phone_kr": re.compile(r"\b01[016789][-. ]?\d{3,4}[-. ]?\d{4}\b|\b0[2-6]\d?[-. ]?\d{3,4}[-. ]?\d{4}\b"),
    "rrn": re.compile(r"\b\d{6}[-]\s?[1-4]\d{6}\b"),
    "ipv4_private": re.compile(r"\b(?:10\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])|192\.168)\.\d{1,3}\.\d{1,3}\b"),
    "api_key": re.compile(r"\b(?:sk-or-v1-[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{30,}|xox[baprs]-[A-Za-z0-9-]{10,})\b"),
    "bearer": re.compile(r"Bearer\s+[A-Za-z0-9._-]{16,}"),
    "handle": re.compile(r"(?<![\w/])@[A-Za-z0-9_.]{3,}\b"),
}


def scan_text(text: str, banned_terms: Iterable[str] = ()) -> list[dict]:
    hits = []
    if not text:
        return hits
    for name, pat in PATTERNS.items():
        for m in pat.finditer(text):
            hits.append({"kind": name, "match": _mask(m.group(0)), "span": [m.start(), m.end()]})
    for term in banned_terms:
        if term and term in text:
            hits.append({"kind": "banned_term", "match": _mask(term), "span": None})
    return hits


def _mask(s: str) -> str:
    """리포에 원문이 그대로 실리지 않게 앞뒤만 남긴다."""
    if len(s) <= 4:
        return s[0] + "*" * (len(s) - 1)
    return s[:2] + "*" * (len(s) - 4) + s[-2:]


ITEM_TEXT_FIELDS = ("input", "question", "evidence", "id", "cluster", "class")


def scan_items(items: list[dict], banned_terms: Iterable[str] = ()) -> list[dict]:
    """항목 전체를 스캔한다. 반환: [{item_id, field, kind, match}]"""
    banned = list(banned_terms)
    out = []
    for it in items:
        for f in ITEM_TEXT_FIELDS:
            v = it.get(f)
            if isinstance(v, str):
                for h in scan_text(v, banned):
                    out.append({"item_id": it.get("id"), "field": f, **h})
        for f in ("choices",):
            for c in it.get(f) or []:
                for h in scan_text(str(c), banned):
                    out.append({"item_id": it.get("id"), "field": f, **h})
        md = it.get("metadata") or {}
        for k, v in md.items():
            if isinstance(v, str):
                for h in scan_text(v, banned):
                    out.append({"item_id": it.get("id"), "field": f"metadata.{k}", **h})
    return out
