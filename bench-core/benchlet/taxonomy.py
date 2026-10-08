"""분류 체계(통제 어휘). registry/taxonomy.yaml 을 읽어 레이블을 검증·정규화하고 매니페스트에 넣는다."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

AXES = ("domain", "input_kind", "source_kind", "language")


def load(root: Path) -> dict:
    p = root / "registry" / "taxonomy.yaml"
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}


def _vals(tax: dict, axis: str) -> list:
    v = tax.get(axis) or {}
    return list(v.keys()) if isinstance(v, dict) else list(v)


def synonym_map(tax: dict) -> dict:
    """동의어 → 정규형 (소문자, 공백 제거)."""
    m = {}
    for canon, syns in (tax.get("keywords") or {}).items():
        m[_n(canon)] = canon
        for s in syns or []:
            m[_n(s)] = canon
    return m


def _n(s: str) -> str:
    return re.sub(r"[\s_\-]+", "", str(s)).lower()


def normalize_keywords(tax: dict, kws: list) -> list:
    sm = synonym_map(tax)
    out = []
    for k in kws or []:
        c = sm.get(_n(k), k)
        if c not in out:
            out.append(c)
    return out


def expand_query(tax: dict, query: str) -> set:
    """검색어를 정규형 키워드와 그 동의어 전부로 넓힌다."""
    toks = set(re.findall(r"[가-힣A-Za-z0-9][가-힣A-Za-z0-9 _\-]*", query or ""))
    sm = synonym_map(tax)
    out = set()
    for t in toks:
        t = t.strip()
        if not t:
            continue
        out.add(t)
        c = sm.get(_n(t))
        if c:
            out.add(c); out.update(tax["keywords"].get(c) or [])
    return out


def check_labels(tax: dict, labels: dict) -> list:
    """반환: 경고 목록. 축 값이 어휘 밖이면 경고(막지는 않는다)."""
    warns = []
    for axis in ("domain", "input_kind", "source_kind", "language"):
        allowed = set(_vals(tax, axis))
        v = labels.get(axis)
        if v in (None, "", []):
            warns.append(f"taxonomy.{axis} 없음 (어휘: {', '.join(sorted(allowed))[:120]})")
            continue
        for x in (v if isinstance(v, list) else [v]):
            if x not in allowed:
                warns.append(f"taxonomy.{axis}={x!r} 는 어휘 밖. 가까운 값을 고르거나 taxonomy.yaml 에 제안")
    if not labels.get("keywords"):
        warns.append("keywords 없음 (시작 목록에서 2~5개)")
    return warns


def labels_of(manifest: dict) -> dict:
    t = dict(manifest.get("taxonomy") or {})
    t["keywords"] = manifest.get("keywords") or t.get("keywords") or []
    return t


def apply_file(root: Path, path: Path, labels: dict, tax: dict) -> None:
    m = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    m["taxonomy"] = {k: labels[k] for k in AXES if k in labels}
    m["keywords"] = normalize_keywords(tax, labels.get("keywords") or [])
    path.write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
