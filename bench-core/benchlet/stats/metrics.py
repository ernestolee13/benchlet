"""통계 층. 정확도 + Wilson, AUROC(진단), Brier(요약), McNemar 정확검정, 클래스별, 단일 표면 특징 최선 정확도.

결정 규칙은 하나다. 이진 0.5, 다지 argmax. 임계를 옮기지 않는다.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict


def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    if not n:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = p + z * z / (2 * n)
    r = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return ((c - r) / d, (c + r) / d)


def auroc(scores: list, labels: list) -> float | None:
    """labels 는 1 이 양성. 동률은 0.5 로 센다(Mann-Whitney)."""
    pos = [s for s, y in zip(scores, labels) if y == 1]
    neg = [s for s, y in zip(scores, labels) if y == 0]
    if not pos or not neg:
        return None
    tot = 0.0
    for p in pos:
        for q in neg:
            tot += 1.0 if p > q else (0.5 if p == q else 0.0)
    return tot / (len(pos) * len(neg))


def brier(probs: list, labels: list) -> float | None:
    if not probs:
        return None
    return sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs)


def mcnemar_exact(b: int, c: int) -> float:
    """b = 팔1 만 맞음, c = 팔2 만 맞음. 양측 정확 이항검정 p 값."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def min_detectable_gap(n: int, base: float = 0.75) -> float:
    """페어드 비교에서 n 개로 볼 수 있는 대략의 격차(pp). 불일치율 30% 가정 McNemar 근사."""
    if n <= 0:
        return 1.0
    disc = max(1, int(round(n * 0.3)))
    # 불일치 항목 중 한쪽이 유의하게 많으려면 |b-c| ≳ 1.96*sqrt(disc)
    return 1.96 * math.sqrt(disc) / n


def accuracy_table(preds: dict) -> dict:
    """preds: {arm: [(hit:int|None, p_pos:float|None, y:int)]} → {arm: {n, ok, acc, ci, auroc, brier}}"""
    out = {}
    for arm, rows in preds.items():
        ok = [(h, p, y) for h, p, y in rows if h is not None]
        n_ok = len(ok)
        hits = sum(h for h, _, _ in ok)
        acc = hits / n_ok if n_ok else None
        ps = [(p, y) for _, p, y in ok if p is not None]
        out[arm] = {
            "n": len(rows), "ok": n_ok, "hit": hits, "acc": acc,
            "ci95": list(wilson(hits, n_ok)) if n_ok else None,
            "auroc": auroc([p for p, _ in ps], [y for _, y in ps]) if ps else None,
            "brier": brier([p for p, _ in ps], [y for _, y in ps]) if ps else None,
        }
    return out


def per_class_table(rows: list) -> dict:
    """rows: [(cls, arm, hit)] → {cls: {arm: (hit, n)}}"""
    t = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for cls, arm, hit in rows:
        if hit is None:
            continue
        t[cls or "-"][arm][0] += int(hit)
        t[cls or "-"][arm][1] += 1
    return {c: {a: tuple(v) for a, v in d.items()} for c, d in t.items()}


# ── 표면 특징 ────────────────────────────────────────────────────────────────
_NUM = re.compile(r"\d")
_YEAR = re.compile(r"(?:19|20)\d{2}년")
_AMOUNT = re.compile(r"\d[\d,]*\s*(?:조|억|만|천)?\s*원")
_QUOTE = re.compile(r"[\"“”「」『』]")
_TOKEN = re.compile(r"[가-힣A-Za-z]{2,}")


def surface_features(text: str) -> dict:
    t = text or ""
    return {
        "길이": len(t),
        "줄 수": t.count("\n") + 1,
        "줄바꿈 유무": int("\n" in t),
        "콜론 유무": int(":" in t or "：" in t),
        "숫자 유무": int(bool(_NUM.search(t))),
        "숫자 개수": len(_NUM.findall(t)),
        "연도 유무": int(bool(_YEAR.search(t))),
        "금액 유무": int(bool(_AMOUNT.search(t))),
        "인용부호 유무": int(bool(_QUOTE.search(t))),
        "물음표 유무": int("?" in t),
        "느낌표 유무": int("!" in t),
        "영문 대문자 유무": int(bool(re.search(r"[A-Z]", t))),
        "문장 수": len([s for s in re.split(r"[.!?。]\s+", t) if s.strip()]),
        "과거형 종결": int(bool(re.search(r"(?:었|았|였|했)(?:다|습니다|어요|어)\.?\s*$", t.strip()))),
    }


def _best_threshold_acc(values: list, ys: list) -> tuple:
    """단일 수치 특징으로 임계 하나를 두고 두 방향으로 찍었을 때 최선 정확도."""
    n = len(ys)
    pairs = sorted(zip(values, ys))
    best, best_t, best_dir = 0.0, None, ">="
    cands = sorted(set(values))
    for t in cands:
        ge = sum(1 for v, y in pairs if (v >= t) == (y == 1))
        lt = n - ge
        if ge > best:
            best, best_t, best_dir = ge, t, ">="
        if lt > best:
            best, best_t, best_dir = lt, t, "<"
    return best / n, best_t, best_dir


def best_surface_feature(inputs: list, ys: list, top_tokens: int = 40) -> dict:
    """ys 는 1 이 양성(target 0). 반환: {best: {feature, acc, threshold, direction}, table: [...]}.
    상위 어휘는 항목의 20% 이상에 나오는 토큰만 본다."""
    n = len(ys)
    if n < 4 or len(set(ys)) < 2:
        return {"best": None, "table": [], "note": "양쪽 라벨이 모두 있어야 한다"}
    feats = [surface_features(x) for x in inputs]
    table = []
    for name in feats[0]:
        vals = [f[name] for f in feats]
        acc, t, d = _best_threshold_acc(vals, ys)
        table.append({"feature": name, "acc": acc, "threshold": t, "direction": d})
    df = Counter()
    toks_per = []
    for x in inputs:
        toks = set(_TOKEN.findall(x or ""))
        toks_per.append(toks)
        df.update(toks)
    for tok, c in df.most_common():
        if c < max(3, 0.2 * n) or c > 0.8 * n:
            continue
        vals = [int(tok in s) for s in toks_per]
        acc, t, d = _best_threshold_acc(vals, ys)
        table.append({"feature": f"어휘 「{tok}」", "acc": acc, "threshold": t, "direction": d})
        if len(table) > 14 + top_tokens:
            break
    table.sort(key=lambda r: -r["acc"])
    base = max(sum(ys), n - sum(ys)) / n
    return {"best": table[0] if table else None, "table": table[:12], "majority": base}
