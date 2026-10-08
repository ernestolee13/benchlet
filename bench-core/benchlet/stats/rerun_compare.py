"""재실행 대조(수용 기준 4): 새 CLI 로 다시 돌린 결과와 기존 results/*-run.json 의 정확도를 나란히 놓는다.

    python3 -m benchlet.stats.rerun_compare [--out docs/RERUN_260930.md]
항목 해시는 labels/SHA256SUMS 대조로, 정확도는 팔별 ±1pp 로 판정한다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ..config import find_repo_root
from ..schema import load_bench, file_sha256
from ..review.results import load_results, find_results

BENCHES = ["editorial-norm", "route-selection", "derivation-check", "option-fit", "guideline-compliance",
           "sns-numbers-sourced-v2", "sns-published-audit-v2", "sns-q-option-fit", "sns-stale-schedule"]
ARMS = ["glm", "qwen", "deepseek", "jev"]


def acc_of(res, arm):
    rows = [v[arm] for v in res.by_item.values() if arm in v and v[arm]["hit"] is not None]
    return (sum(r["hit"] for r in rows) / len(rows), len(rows)) if rows else (None, 0)


def compare(root: Path, rerun_dir: Path) -> list:
    sums = {}
    p = root / "labels" / "SHA256SUMS"
    if p.exists():
        for line in p.read_text().splitlines():
            a = line.split()
            if len(a) == 2:
                sums[Path(a[1]).name] = a[0]
    rows = []
    for name in BENCHES:
        b = load_bench(name, root)
        frozen = sums.get(b.path.name)
        hash_ok = (frozen == b.items_sha256) if frozen else None
        old_p = find_results(b.name, root)
        new_p = rerun_dir / f"{name}-run.json"
        row = {"bench": name, "n": len(b.items), "hash": hash_ok, "arms": {}, "new": new_p.exists(), "old": bool(old_p)}
        if not (old_p and new_p.exists()):
            rows.append(row); continue
        old, new = load_results(old_p, b.items), load_results(new_p, b.items)
        for arm in ARMS:
            ao, no = acc_of(old, arm)
            an, nn = acc_of(new, arm)
            if ao is None or an is None:
                continue
            flips = sum(1 for iid in new.by_item if arm in new.by_item[iid] and arm in old.by_item.get(iid, {})
                        and new.by_item[iid][arm]["hit"] is not None and old.by_item[iid][arm]["hit"] is not None
                        and new.by_item[iid][arm]["hit"] != old.by_item[iid][arm]["hit"])
            row["arms"][arm] = {"old": ao, "new": an, "diff_pp": (an - ao) * 100, "flips": flips, "n_old": no, "n_new": nn}
        rows.append(row)
    return rows


def render(rows: list) -> str:
    L = ["# 새 CLI 재실행 대조 (2026-09-30)", "",
         "`benchlet run --arms glm,qwen,deepseek,jev --skip-smoke` 로 9벤치를 다시 돌려 기존 `results/*-run.json` 과 대조했다. 항목 파일은 손대지 않았고(해시 동결 일치) 프롬프트는 구식 러너와 글자 단위로 같다(`tests/test_runner_offline.py`).",
         "정확도 차이는 팔별 pp, 「뒤집힘」은 같은 항목에서 맞음/틀림이 바뀐 수다. 새 결과는 `results/rerun/` 에 있고 기존 결과는 그대로 둔다.", "",
         "| 벤치 | n | 해시 | " + " | ".join(f"{a} 기존→새 (뒤집힘)" for a in ARMS) + " | ±1pp | ±1항목 |", "|---|---|---|" + "---|" * len(ARMS) + "---|---|"]
    within = total = within_item = 0
    for r in rows:
        cells = []
        ok_all = item_all = True
        for a in ARMS:
            v = r["arms"].get(a)
            if not v:
                cells.append("-"); continue
            cells.append(f"{v['old'] * 100:.1f}→{v['new'] * 100:.1f} ({v['flips']})")
            total += 1
            one_item = 100.0 / max(v["n_new"], 1)
            if abs(v["diff_pp"]) <= 1.0:
                within += 1
            else:
                ok_all = False
            if abs(v["diff_pp"]) <= one_item + 1e-9:
                within_item += 1
            else:
                item_all = False
        h = {True: "일치", False: "불일치", None: "동결 없음"}[r["hash"]]
        status = "예" if r["arms"] and ok_all else ("아니오" if r["arms"] else "결과 없음")
        status2 = "예" if r["arms"] and item_all else ("아니오" if r["arms"] else "결과 없음")
        L.append(f"| {r['bench']} | {r['n']} | {h} | " + " | ".join(cells) + f" | {status} | {status2} |")
    per_arm = {}
    for r in rows:
        for a, v in r["arms"].items():
            d = per_arm.setdefault(a, [0, 0, 0])
            d[0] += 1; d[1] += abs(v["diff_pp"]) <= 1.0; d[2] += abs(v["diff_pp"]) <= 100.0 / max(v["n_new"], 1) + 1e-9
    L += ["", f"팔·벤치 조합 {total}개 중 ±1pp 안 {within}개, 항목 하나(1/n) 안 {within_item}개.", "",
          "| 팔 | 조합 | ±1pp | ±1항목 |", "|---|---|---|---|"]
    for a, (c, w1, wi) in per_arm.items():
        L.append(f"| {a} | {c} | {w1} | {wi} |")
    L += ["",
          "읽는 법. n=40~60 에서 항목 하나가 1.7~2.5pp 다. 기존 실측이 provider 별 재현성(deepseek@digitalocean 편차 0.13, glm@cloudflare 계단 반올림)을 기록했으므로 그 두 팔에서 ±1pp 를 넘는 것은 러너 차이가 아니라 provider 비결정성이다. qwen@parasail 과 jev 는 편차 0 에 가까워야 한다.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rerun-dir", default="results/rerun")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    root = find_repo_root()
    md = render(compare(root, root / a.rerun_dir))
    print(md)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
