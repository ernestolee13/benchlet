"""결과 파일 → 보고 표. 정확도·Wilson·클래스별·AUROC·Brier·McNemar·표면 특징 최선."""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

from ..review.results import RunResults, load_results
from ..schema.load import Bench
from .metrics import accuracy_table, per_class_table, mcnemar_exact, best_surface_feature, min_detectable_gap


def build_report(bench: Bench, res: RunResults) -> dict:
    by_id = {it["id"]: it for it in bench.items}
    preds = defaultdict(list)
    cls_rows = []
    for iid, d in res.by_item.items():
        it = by_id[iid]
        y = 1 if it["target"] == 0 else 0
        for arm, v in d.items():
            p_pos = v["p_pos"] if it["type"] == "binary" else None
            preds[arm].append((v["hit"], p_pos, y))
            cls_rows.append((it.get("class"), arm, v["hit"]))
    summary = accuracy_table(preds)
    per_class = per_class_table(cls_rows)
    pair = {}
    arms = list(preds)
    for a, b in combinations(arms, 2):
        bb = cc = 0
        for iid, d in res.by_item.items():
            ha, hb = d.get(a, {}).get("hit"), d.get(b, {}).get("hit")
            if ha is None or hb is None:
                continue
            bb += int(ha == 1 and hb == 0); cc += int(ha == 0 and hb == 1)
        pair[f"{a} vs {b}"] = {"only_a": bb, "only_b": cc, "p": mcnemar_exact(bb, cc)}
    n = len(res.by_item)
    surf = None
    if bench.type == "binary":
        surf = best_surface_feature([by_id[i]["input"] for i in res.by_item], [1 if by_id[i]["target"] == 0 else 0 for i in res.by_item])
    excluded = {a: (sum(1 for h, _, _ in rows if h is None)) for a, rows in preds.items()}
    return {"bench": bench.name, "n": n, "summary": summary, "per_class": per_class, "pairwise": pair,
            "surface": surf, "min_gap_pp": round(min_detectable_gap(n) * 100), "excluded": excluded}


def render_report(rep: dict) -> str:
    L = [f"## {rep['bench']}  (n={rep['n']}, 검출 가능 격차 약 {rep['min_gap_pp']}pp)", "",
         "| 팔 | 성공 | 정확도 | Wilson 95% | AUROC(진단) | Brier | 제외 |", "|---|---|---|---|---|---|---|"]
    for arm, s in rep["summary"].items():
        acc = f"{s['acc'] * 100:.1f}%" if s["acc"] is not None else "-"
        ci = f"[{s['ci95'][0] * 100:.0f}, {s['ci95'][1] * 100:.0f}]" if s["ci95"] else "-"
        au = f"{s['auroc']:.2f}" if s["auroc"] is not None else "N/A"
        br = f"{s['brier']:.3f}" if s["brier"] is not None else "N/A"
        L.append(f"| {arm} | {s['ok']}/{s['n']} | {acc} | {ci} | {au} | {br} | {rep['excluded'].get(arm, 0)} |")
    L += ["", "클래스별 (맞음/n)", "", "| 클래스 | " + " | ".join(rep["summary"]) + " |", "|---|" + "---|" * len(rep["summary"])]
    for c in sorted(rep["per_class"]):
        row = rep["per_class"][c]
        L.append(f"| {c} | " + " | ".join(f"{row[a][0]}/{row[a][1]}" if a in row else "-" for a in rep["summary"]) + " |")
    if rep["pairwise"]:
        L += ["", "쌍 비교 (McNemar 정확검정)", "", "| 쌍 | 앞만 맞음 | 뒤만 맞음 | p |", "|---|---|---|---|"]
        for k, v in rep["pairwise"].items():
            L.append(f"| {k} | {v['only_a']} | {v['only_b']} | {v['p']:.3f} |")
    if rep.get("surface") and rep["surface"].get("best"):
        b = rep["surface"]["best"]
        L += ["", f"단일 표면 특징 최선 정확도: 「{b['feature']}」 {b['acc']:.0%} (다수결 {rep['surface']['majority']:.0%}). 70% 를 넘으면 그 특징을 깨는 항목을 더한다"]
    L += ["", "AUROC 는 진단용이다. 높은데 정확도가 낮으면 임계를 옮기지 말고 질문을 고친다. 요약 지표는 Brier."]
    return "\n".join(L)
