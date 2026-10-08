"""행렬 없는 시드의 검증: 우리 팔로 전체 세트와 100건 축약본을 돌린 결과를 비교해 매니페스트 distill.own_arms 에 적는다.

정확도는 호출이 성공한 항목 기준. 「같은 100건을 전체 실행 안에서 본 정확도」도 같이 적어 실행 잡음과 축약 오차를 가른다.
사용: python3 src/compare_full_vs_mini.py --scratch <scratch> [--only <name-mini>]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def acc_by_arm(run: dict, keys: set | None, key_of) -> dict:
    out = {}
    for arm in run["arms"]:
        h = n = 0
        for it in run["items"]:
            if keys is not None and key_of(it["id"]) not in keys:
                continue
            r = it["arms"].get(arm) or {}
            if r.get("err"):
                continue
            if "p_violation" in r and r["p_violation"] is not None:
                n += 1; h += int((r["p_violation"] >= 0.5) == (it["target"] == 0))
            elif r.get("pred_index") is not None:
                n += 1; h += int(int(r["pred_index"]) == int(it["target"]))
        out[arm] = {"acc": round(h / n, 4) if n else None, "ok": n, "n": len(run["items"]) if keys is None else len(keys)}
    return out


def compare(name: str, S: Path) -> dict | None:
    base = name[:-5]
    fp, mp = S / "exp" / "full" / f"{base}-full-run.json", ROOT / "results" / f"{name}-run.json"
    if not fp.exists() or not mp.exists():
        print(f"{name}: 실행 결과 없음 ({fp.exists()}, {mp.exists()})"); return None
    full, mini = json.loads(fp.read_text()), json.loads(mp.read_text())
    fitems = {it["id"]: it for it in (json.loads(l) for l in (S / "exp" / "full" / f"{base}-full.jsonl").read_text(encoding="utf-8").split("\n") if l.strip())}
    mitems = [json.loads(l) for l in (ROOT / "tasks" / f"{name}.jsonl").read_text(encoding="utf-8").split("\n") if l.strip()]
    sel = {it["provenance"]["source_key"] for it in mitems}
    key_of = lambda iid: fitems[iid]["provenance"]["source_key"]     # noqa: E731
    a_full = acc_by_arm(full, None, key_of)
    a_sub = acc_by_arm(full, sel, key_of)
    a_mini = acc_by_arm(mini, None, lambda iid: iid)
    # 호출 성공률이 70% 아래인 팔은 표본이 작아 비교에서 뺀다(예: deepseek 의 라벨 질량 실패)
    reliable = lambda a: a_full[a]["ok"] >= 0.7 * a_full[a]["n"] and a_mini[a]["ok"] >= 0.7 * a_mini[a]["n"]     # noqa: E731
    excluded = [a for a in a_full if a in a_mini and not reliable(a)]
    arms = [a for a in a_full if a_full[a]["acc"] is not None and a_mini.get(a, {}).get("acc") is not None and reliable(a)]
    gaps = {a: round(abs(a_full[a]["acc"] - a_mini[a]["acc"]) * 100, 2) for a in arms}
    rank = lambda d: sorted(arms, key=lambda a: -d[a]["acc"])     # noqa: E731
    rep = {"date": mini.get("date"), "arms": {a: {"full_acc": a_full[a]["acc"], "full_ok": a_full[a]["ok"], "full_n": a_full[a]["n"],
                                               "mini_acc": a_mini[a]["acc"], "mini_ok": a_mini[a]["ok"],
                                               "same_items_in_full_run_acc": a_sub[a]["acc"], "gap_pp": gaps[a]} for a in arms},
           "mae_pp": round(sum(gaps.values()) / len(gaps), 2) if gaps else None, "max_gap_pp": max(gaps.values()) if gaps else None,
           "rank_full": rank(a_full), "rank_mini": rank(a_mini), "rank_preserved": rank(a_full) == rank(a_mini),
           "excluded_arms_low_success": {a: {"full_ok": a_full[a]["ok"], "mini_ok": a_mini[a]["ok"]} for a in excluded},
           "sampling_se_pp_at_100": "정확도 80% 기준 이항 표준오차 약 4pp. 그 안의 차이는 표본 잡음이다",
           "note": "검증 집단은 우리 4팔뿐이다. gap 에는 제공자 실행 잡음(같은 항목 재실행 차이 최대 2pp)이 섞여 있다"}
    man_p = ROOT / "tasks" / f"{name}.manifest.yaml"
    man = yaml.safe_load(man_p.read_text(encoding="utf-8"))
    man.setdefault("distill", {})["own_arms"] = rep
    man_p.write_text(yaml.safe_dump(man, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print(f"{name}: MAE {rep['mae_pp']}pp 최대 {rep['max_gap_pp']}pp 순위 보존 {rep['rank_preserved']} | " +
          " ".join(f"{a} {a_full[a]['acc']*100:.0f}→{a_mini[a]['acc']*100:.0f}" for a in arms) + (f" | 제외 {excluded}" if excluded else ""))
    return rep


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--scratch", required=True); ap.add_argument("--only"); ap.add_argument("--names", default="")
    a = ap.parse_args()
    names = [a.only] if a.only else (a.names.split(",") if a.names else
             [p.stem for p in (ROOT / "tasks").glob("*-mini.jsonl") if "own_arms" in (ROOT / "tasks" / f"{p.stem}.manifest.yaml").read_text(encoding="utf-8")])
    for n in names:
        compare(n, Path(a.scratch))


if __name__ == "__main__":
    main()
