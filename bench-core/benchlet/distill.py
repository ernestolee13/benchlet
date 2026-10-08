"""공개 벤치 축약 (`benchlet distill`). 모델 M 개 × 항목 N 개 정오 행렬에서 n 건을 골라, 보지 않은 모델에서도
전체 정확도와 순위가 보존되게 한다. IRT 없이 난이도 층화 + 적합 모델 기준 교환 탐색. 검증 모델 수치만 보고한다.

행렬 형식(JSON): {"models": [...], "items": [...], "correct": [[0/1 ...] per model]} 또는 CSV(첫 열 model, 나머지 열 item id).
"""
from __future__ import annotations

import csv
import json
import math
import random
from pathlib import Path


def load_matrix(path: Path) -> dict:
    p = Path(path)
    if p.suffix == ".json":
        d = json.loads(p.read_text(encoding="utf-8"))
        return {"models": list(d["models"]), "items": [str(x) for x in d["items"]], "correct": [[int(v) for v in row] for row in d["correct"]]}
    rows = list(csv.reader(p.open(encoding="utf-8")))
    header, body = rows[0], rows[1:]
    return {"models": [r[0] for r in body], "items": header[1:], "correct": [[int(float(v)) for v in r[1:]] for r in body]}


def _acc(row: list, idx: list) -> float:
    return sum(row[i] for i in idx) / len(idx)


def _kendall(a: list, b: list) -> float:
    n = len(a)
    if n < 2:
        return 1.0
    conc = disc = 0
    for i in range(n):
        for j in range(i + 1, n):
            s = (a[i] - a[j]) * (b[i] - b[j])
            if s > 0: conc += 1
            elif s < 0: disc += 1
    tot = conc + disc
    return (conc - disc) / tot if tot else 1.0


def _spearman(a: list, b: list) -> float:
    def ranks(x):
        order = sorted(range(len(x)), key=lambda i: x[i])
        r = [0.0] * len(x)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and x[order[j + 1]] == x[order[i]]:
                j += 1
            for k in range(i, j + 1):
                r[order[k]] = (i + j) / 2 + 1
            i = j + 1
        return r
    ra, rb = ranks(a), ranks(b)
    n = len(a)
    ma, mb = sum(ra) / n, sum(rb) / n
    num = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    den = math.sqrt(sum((x - ma) ** 2 for x in ra) * sum((y - mb) ** 2 for y in rb))
    return num / den if den else 1.0


def evaluate(correct: list, model_idx: list, subset: list, all_idx: list) -> dict:
    full = [_acc(correct[m], all_idx) for m in model_idx]
    sub = [_acc(correct[m], subset) for m in model_idx]
    errs = [abs(f - s) for f, s in zip(full, sub)]
    return {"mae": sum(errs) / len(errs), "max_err": max(errs), "kendall": _kendall(full, sub), "spearman": _spearman(full, sub), "n_models": len(model_idx)}


def _objective(correct, fit_idx, subset, all_idx) -> float:
    e = evaluate(correct, fit_idx, subset, all_idx)
    return e["mae"] + 0.5 * e["max_err"] + 0.1 * (1 - e["kendall"])


def evaluate_weighted(correct: list, model_idx: list, subset: list, weights: list, all_idx: list) -> dict:
    """앵커 가중 추정: acc_hat(m) = Σ w_c · correct[m][anchor_c]. (Anchor Points, tinyBenchmarks 의 가중 평균과 같은 꼴)"""
    full = [_acc(correct[m], all_idx) for m in model_idx]
    est = [sum(w * correct[m][i] for i, w in zip(subset, weights)) for m in model_idx]
    errs = [abs(f - e) for f, e in zip(full, est)]
    return {"mae": sum(errs) / len(errs), "max_err": max(errs), "kendall": _kendall(full, est), "spearman": _spearman(full, est), "n_models": len(model_idx)}


def anchor_select(correct: list, fit_idx: list, usable: list, n: int, rng: random.Random, rounds: int = 25) -> tuple:
    """항목을 적합 모델 정오 벡터로 k-means(k=n) 군집화하고 군집마다 중심에 가장 가까운 항목(앵커)을 고른다. 가중치 = 군집 크기 비율."""
    import numpy as np
    X = np.array([[correct[m][i] for m in fit_idx] for i in usable], dtype=float)   # 항목 × 적합 모델
    k = n
    # k-means++ 초기화
    centers = [X[rng.randrange(len(X))]]
    d2 = ((X - centers[0]) ** 2).sum(1)
    for _ in range(1, k):
        probs = d2 / d2.sum() if d2.sum() > 0 else np.ones(len(X)) / len(X)
        idx = rng.choices(range(len(X)), weights=probs.tolist())[0]
        centers.append(X[idx])
        d2 = np.minimum(d2, ((X - X[idx]) ** 2).sum(1))
    Cn = np.stack(centers)
    for _ in range(rounds):
        dist = ((X[:, None, :] - Cn[None, :, :]) ** 2).sum(2)
        lab = dist.argmin(1)
        newC = np.stack([X[lab == j].mean(0) if (lab == j).any() else Cn[j] for j in range(k)])
        if np.allclose(newC, Cn):
            break
        Cn = newC
    dist = ((X[:, None, :] - Cn[None, :, :]) ** 2).sum(2)
    lab = dist.argmin(1)
    anchors, weights = [], []
    for j in range(k):
        members = np.where(lab == j)[0]
        if len(members) == 0:
            continue
        best = members[dist[members, j].argmin()]
        anchors.append(usable[int(best)]); weights.append(len(members) / len(X))
    # 빈 군집이 있으면 가장 큰 군집에서 추가 앵커를 뽑아 n 을 채운다
    while len(anchors) < n:
        big = int(np.bincount(lab).argmax())
        members = [int(x) for x in np.where(lab == big)[0] if usable[int(x)] not in anchors]
        if not members:
            break
        pick = rng.choice(members); anchors.append(usable[pick]); weights.append(0.0)
    tot = sum(weights)
    return anchors, [w / tot for w in weights]


# ── 1PL(Rasch) IRT: tinyBenchmarks 의 IRT / p-IRT 추정과 같은 꼴을 numpy 로 ────────────────────────
def fit_rasch(C: list, fit_idx: list, usable: list, iters: int = 300, lr: float = 0.5, reg: float = 0.01, max_models: int = 600, rng=None):
    """능력 θ_m 과 난이도 b_i 를 경사 상승으로 적합한다. 모델이 많으면 max_models 개만 무작위로 쓴다. 반환 (b: 항목별 난이도 dict idx→b, θ 평균·표준편차)."""
    import numpy as np
    rng = rng or random.Random(0)
    fm = list(fit_idx)
    if len(fm) > max_models:
        fm = rng.sample(fm, max_models)
    X = np.array([[C[m][i] for i in usable] for m in fm], dtype=float)      # 모델 × 항목
    th = np.zeros(len(fm)); b = np.zeros(len(usable))
    for _ in range(iters):
        P = 1 / (1 + np.exp(-(th[:, None] - b[None, :])))
        R = X - P
        th += lr * (R.mean(1) - reg * th)
        b -= lr * (R.mean(0) + reg * b)        # ∂LL/∂b = -(X-P)
    return {usable[j]: float(b[j]) for j in range(len(usable))}, float(th.mean()), float(th.std())


def _theta_mle(resp: list, bs: list, iters: int = 30) -> float:
    """항목 응답(0/1)과 난이도로 능력 MLE (뉴턴). 약한 사전(정규)으로 극단을 막는다."""
    th = 0.0
    for _ in range(iters):
        g = h = 0.0
        for x, b in zip(resp, bs):
            p = 1 / (1 + math.exp(-(th - b)))
            g += x - p; h += p * (1 - p)
        g -= 0.1 * th; h += 0.1
        if h <= 0:
            break
        step = g / h
        th += max(-2.0, min(2.0, step))
        if abs(step) < 1e-5:
            break
    return th


def irt_select(bdict: dict, usable: list, n: int) -> list:
    """난이도 b 의 n 분위마다 분위 중앙에 가장 가까운 항목을 고른다(능력 범위 전체에 정보가 고르게)."""
    order = sorted(usable, key=lambda i: bdict[i])
    chosen = []
    for j in range(n):
        seg = order[j * len(order) // n:(j + 1) * len(order) // n]
        if not seg:
            continue
        mid = len(seg) // 2
        chosen.append(seg[mid])
    return chosen


def evaluate_irt(C: list, model_idx: list, subset: list, bdict: dict, all_idx: list) -> dict:
    """검증 모델마다 부분집합 응답으로 θ 를 추정하고 전체 정확도를 예측. p-IRT = 본 항목은 관측, 못 본 항목은 IRT 예측."""
    bs_sub = [bdict[i] for i in subset]
    unseen = [i for i in all_idx if i not in set(subset)]
    bs_un = [bdict[i] for i in unseen]
    full, est_irt, est_pirt = [], [], []
    for m in model_idx:
        resp = [C[m][i] for i in subset]
        th = _theta_mle(resp, bs_sub)
        pred_all = sum(1 / (1 + math.exp(-(th - bdict[i]))) for i in all_idx) / len(all_idx)
        pred_un = (sum(1 / (1 + math.exp(-(th - b))) for b in bs_un) / len(bs_un)) if bs_un else 0.0
        obs = sum(resp) / len(resp)
        full.append(_acc(C[m], all_idx)); est_irt.append(pred_all)
        est_pirt.append((len(subset) * obs + len(unseen) * pred_un) / len(all_idx))
    out = {}
    for name, est in (("irt", est_irt), ("pirt", est_pirt)):
        errs = [abs(f - e) for f, e in zip(full, est)]
        out[name] = {"mae": sum(errs) / len(errs), "max_err": max(errs), "kendall": _kendall(full, est), "spearman": _spearman(full, est), "n_models": len(model_idx)}
    return out


SWAP_MIN_MODELS = 100      # 전체 모델 수가 이보다 적으면 교환 탐색이 과적합해 층화 무작위보다 못하다(2026-10-05 실측: HELM 67~91개는 무작위가, BFCL 109개·metabench 800개는 교환이 낫다)


def distill(matrix: dict, n: int = 100, seed: int = 20261003, strata: int = 5, fit_frac: float = 0.7,
            iters: int = 4000, min_var: float = 0.0, keep_item_filter=None, method: str = "auto",
            swap_min_models: int = SWAP_MIN_MODELS) -> dict:
    """method: auto(기본) = 모델 수가 swap_min_models 이상이면 stratified(교환 탐색), 아니면 random(층화 무작위).
    stratified 와 random 둘 다 상대 방법의 검증 수치를 alt 로 같이 돌려준다."""
    rng = random.Random(seed)
    models, items, C = matrix["models"], matrix["items"], matrix["correct"]
    M, N = len(models), len(items)
    # 1. 전처리: 분산 0 항목 제거, 선택 필터
    p = [sum(C[m][i] for m in range(M)) / M for i in range(N)]
    usable = [i for i in range(N) if (p[i] * (1 - p[i]) > min_var) and (keep_item_filter is None or keep_item_filter(i))]
    if len(usable) < n:
        raise ValueError(f"쓸 수 있는 항목 {len(usable)} < n {n}")
    # 2. 적합/검증 모델 분리
    midx = list(range(M)); rng.shuffle(midx)
    k = max(2, int(M * fit_frac))
    fit_idx, val_idx = midx[:k], midx[k:] or midx[:k]
    # 3. 난이도 층화 비례 배분
    order = sorted(usable, key=lambda i: p[i])
    bins = [order[j * len(order) // strata:(j + 1) * len(order) // strata] for j in range(strata)]
    alloc = [max(1, round(n * len(b) / len(order))) for b in bins]
    while sum(alloc) > n:
        alloc[alloc.index(max(alloc))] -= 1
    while sum(alloc) < n:
        alloc[alloc.index(min(alloc))] += 1
    chosen = []
    for b, a in zip(bins, alloc):
        chosen += rng.sample(b, min(a, len(b)))
    baseline = list(chosen)
    all_idx = usable
    if method == "auto":
        method = "stratified" if M >= swap_min_models else "random"
    if method == "irt":
        bdict, th_mean, th_std = fit_rasch(C, fit_idx, usable, rng=rng)
        sel = irt_select(bdict, usable, n)
        ev = evaluate_irt(C, val_idx, sel, bdict, all_idx)
        evb = evaluate_irt(C, val_idx, baseline, bdict, all_idx)
        return {
            "n": len(sel), "seed": seed, "method": "1PL IRT (Rasch) fitted on fit models; items = difficulty-quantile medians; estimator p-IRT (observed on seen items + IRT prediction on unseen); val models held out",
            "n_items_total": N, "n_items_usable": len(usable), "n_models": M, "fit_models": len(fit_idx), "val_models": len(val_idx),
            "selected": [items[i] for i in sel], "selected_idx": sel,
            "difficulty": {items[i]: round(p[i], 4) for i in sel}, "irt_b": {items[i]: round(bdict[i], 4) for i in sel},
            "theta_fit": {"mean": round(th_mean, 3), "std": round(th_std, 3)},
            "val": ev["pirt"], "val_irt_only": ev["irt"], "val_unweighted": evaluate(C, val_idx, sel, all_idx),
            "fit": evaluate_irt(C, fit_idx, sel, bdict, all_idx)["pirt"],
            "baseline_val": evaluate(C, val_idx, baseline, all_idx), "baseline_val_pirt": evb["pirt"],
        }
    if method == "anchor":
        anchors, weights = anchor_select(C, fit_idx, usable, n, rng)
        return {
            "n": len(anchors), "seed": seed, "method": "anchor points: k-means(k=n) on fit-model correctness vectors, medoid per cluster, weight = cluster share; val models held out; no IRT",
            "n_items_total": N, "n_items_usable": len(usable), "n_models": M, "fit_models": len(fit_idx), "val_models": len(val_idx),
            "selected": [items[i] for i in anchors], "selected_idx": anchors, "weights": {items[i]: round(w, 6) for i, w in zip(anchors, weights)},
            "difficulty": {items[i]: round(p[i], 4) for i in anchors},
            "val": evaluate_weighted(C, val_idx, anchors, weights, all_idx), "val_unweighted": evaluate(C, val_idx, anchors, all_idx),
            "fit": evaluate_weighted(C, fit_idx, anchors, weights, all_idx),
            "baseline_val": evaluate(C, val_idx, baseline, all_idx),
        }
    # 4. 교환 탐색 (같은 층 안에서만). numpy 로 적합 모델의 전체 정확도는 한 번만, 부분집합 정확도는 증분으로 계산한다
    import numpy as np
    Cf = np.array([[C[m][i] for i in all_idx] for m in fit_idx], dtype=float)      # 적합 모델 × 쓸 수 있는 항목
    pos = {i: j for j, i in enumerate(all_idx)}
    full = Cf.mean(1)
    full_rank = np.argsort(np.argsort(full))

    def objective(sub):
        cols = [pos[i] for i in sub]
        acc = Cf[:, cols].mean(1)
        err = np.abs(acc - full)
        rank = np.argsort(np.argsort(acc))
        d = full_rank - rank
        spear = 1 - 6 * float((d * d).sum()) / (len(full) * (len(full) ** 2 - 1))
        return float(err.mean() + 0.5 * err.max() + 0.1 * (1 - spear))

    bin_of = {i: j for j, b in enumerate(bins) for i in b}
    cur = objective(chosen)
    chosen_set = set(chosen)
    for _ in range(iters):
        out = rng.choice(chosen)
        cand = rng.choice(bins[bin_of[out]])
        if cand in chosen_set:
            continue
        trial = [cand if x == out else x for x in chosen]
        val = objective(trial)
        if val < cur:
            cur, chosen = val, trial
            chosen_set = set(chosen)
    swapped = chosen
    if method == "random":
        chosen = baseline
    try:
        bdict, _, _ = fit_rasch(C, fit_idx, usable, rng=rng)
        irt_b = {items[i]: round(bdict[i], 4) for i in chosen}
    except Exception:            # noqa: BLE001
        irt_b = {}
    desc = {"stratified": "difficulty-stratified (5 quantiles) + swap search on fit models (objective: mean and max |acc_sub - acc_full| and 1 - Kendall tau); val models held out",
            "random": f"difficulty-stratified (5 quantiles) random sample; swap search skipped because models {M} < {swap_min_models} (it overfits); val models held out"}[method]
    return {
        "irt_b": irt_b,
        "n": n, "seed": seed, "strata": strata, "n_items_total": N, "n_items_usable": len(usable),
        "n_models": M, "fit_models": len(fit_idx), "val_models": len(val_idx),
        "selected": [items[i] for i in chosen], "selected_idx": chosen,
        "difficulty": {items[i]: round(p[i], 4) for i in chosen},
        "val": evaluate(C, val_idx, chosen, all_idx), "fit": evaluate(C, fit_idx, chosen, all_idx),
        "baseline_val": evaluate(C, val_idx, baseline, all_idx),
        "alt": {"method": "swap search" if method == "random" else "stratified random",
                "val": evaluate(C, val_idx, swapped if method == "random" else baseline, all_idx)},
        "method": desc, "method_key": method,
    }


def render(r: dict) -> str:
    v, b, f = r["val"], r["baseline_val"], r["fit"]
    kind = "p-IRT 추정" if r.get("val_irt_only") else ("가중 추정" if r.get("weights") else "부분집합 정확도")
    L = [f"항목 {r['n']} / 쓸 수 있는 {r['n_items_usable']} / 전체 {r['n_items_total']} · 모델 {r['n_models']} (적합 {r['fit_models']}, 검증 {r['val_models']}) · {r['method']}",
         "| 집단 | MAE | 최대 오차 | Kendall τ | Spearman |", "|---|---|---|---|---|",
         f"| 검증 모델, {kind} (보고 기준) | {v['mae']*100:.2f}pp | {v['max_err']*100:.2f}pp | {v['kendall']:.3f} | {v['spearman']:.3f} |"]
    if r.get("val_unweighted"):
        u = r["val_unweighted"]
        L.append(f"| 검증 모델, 단순 정확도 (추정 없이) | {u['mae']*100:.2f}pp | {u['max_err']*100:.2f}pp | {u['kendall']:.3f} | {u['spearman']:.3f} |")
    if r.get("val_irt_only"):
        u = r["val_irt_only"]
        L.append(f"| 검증 모델, IRT 만 (θ 추정 → 전체 예측) | {u['mae']*100:.2f}pp | {u['max_err']*100:.2f}pp | {u['kendall']:.3f} | {u['spearman']:.3f} |")
    if r.get("baseline_val_pirt"):
        u = r["baseline_val_pirt"]
        L.append(f"| 층화 무작위 + p-IRT 추정 (검증) | {u['mae']*100:.2f}pp | {u['max_err']*100:.2f}pp | {u['kendall']:.3f} | {u['spearman']:.3f} |")
    if r.get("alt") and r.get("method_key") == "random":
        u = r["alt"]["val"]
        L.append(f"| 교환 탐색 대안 (검증, 채택 안 함) | {u['mae']*100:.2f}pp | {u['max_err']*100:.2f}pp | {u['kendall']:.3f} | {u['spearman']:.3f} |")
    return "\n".join(L + [
        f"| 층화 무작위 기준선 (검증) | {b['mae']*100:.2f}pp | {b['max_err']*100:.2f}pp | {b['kendall']:.3f} | {b['spearman']:.3f} |",
        f"| 적합 모델 (참고, 과적합 가능) | {f['mae']*100:.2f}pp | {f['max_err']*100:.2f}pp | {f['kendall']:.3f} | {f['spearman']:.3f} |",
    ])
