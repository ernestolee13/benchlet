"""실행 결과 파일을 읽어 팔별 예측으로 푼다. 구식 run.py 결과와 새 러너 결과 둘 다 읽는다."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from ..runner.arms import arm_family


@dataclass
class RunResults:
    path: Path
    arms: list
    by_item: dict = field(default_factory=dict)   # id → {arm: {pred, p_pos, hit, err}}
    meta: dict = field(default_factory=dict)

    def families(self) -> dict:
        fam = {}
        for a in self.arms:
            fam[a] = (self.meta.get("arms") or {}).get(a, {}).get("family") or arm_family(a)
        return fam


def find_results(bench_name: str, root: Path, explicit: str | None = None) -> Path | None:
    if explicit:
        p = Path(explicit)
        return p if p.exists() else None
    short = {"editorial-norm": "norm", "route-selection": "route", "derivation-check": "deriv",
             "option-fit": "fit", "guideline-compliance": "guide"}
    for cand in [root / "results" / f"{bench_name}-run.json",
                 root / "results" / f"{short.get(bench_name, '')}-run.json"]:
        if cand.name != "-run.json" and cand.exists():
            return cand
    return None


def _pred_for(arm_rec: dict, it: dict):
    """(pred_index, p_pos, err). p_pos 는 P(choices[0])."""
    if arm_rec.get("err"):
        return None, None, arm_rec["err"]
    choices = it["choices"]
    if it["type"] == "binary":
        p = arm_rec.get("p_violation", arm_rec.get("p_pos"))
        if p is None:
            return None, None, "확률 없음"
        return (0 if p >= 0.5 else 1), float(p), None
    if arm_rec.get("pred_index") is not None:
        pred = int(arm_rec["pred_index"])
    elif arm_rec.get("choice") is not None:
        c = arm_rec["choice"]
        pred = choices.index(c) if c in choices else None
    else:
        return None, None, "예측 없음"
    probs = arm_rec.get("probs")
    p_pos = None
    if isinstance(probs, list) and len(probs) == len(choices):
        p_pos = float(probs[it["target"]])
    elif isinstance(arm_rec.get("probabilities"), dict):
        p_pos = arm_rec["probabilities"].get(choices[it["target"]])
    return pred, p_pos, None


def load_results(path: Path, items: list) -> RunResults:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    by_id = {it["id"]: it for it in items}
    arms = list(raw.get("agg", {}).keys()) or sorted({a for r in raw["items"] for a in r["arms"]})
    rr = RunResults(path=Path(path), arms=arms, meta={k: v for k, v in raw.items() if k not in ("items", "agg")})
    for rec in raw["items"]:
        it = by_id.get(rec["id"])
        if not it:
            continue
        d = {}
        for arm, a in rec["arms"].items():
            pred, p_pos, err = _pred_for(a, it)
            d[arm] = {"pred": pred, "p_pos": p_pos, "err": err,
                      "hit": None if pred is None else int(pred == it["target"])}
        rr.by_item[rec["id"]] = d
    return rr
