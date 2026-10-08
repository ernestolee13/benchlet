#!/usr/bin/env python3
"""OpenEval(Open-Eval-Commons/OpenEval, CC-BY-NC-4.0) 응답 parquet → 모델×항목 정오 행렬 + 항목 파일.

response_id = <item_id>_<model>_<k>, model.name, scores.value[0] (mmlu_pro 는 chain_of_thought_correctness). 응답이 여럿이면 평균 ≥ 0.5 를 정답으로.
    python3 src/prepare_openeval.py --dir <parquet 폴더> --bench mmlu_pro --out <폴더>
"""
from __future__ import annotations

import argparse
import glob
import json
from collections import defaultdict
from pathlib import Path

import pyarrow.parquet as pq


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True); ap.add_argument("--bench", default="mmlu_pro"); ap.add_argument("--out", required=True)
    a = ap.parse_args()
    d, out = Path(a.dir), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    # 항목
    it = pq.read_table(sorted(glob.glob(str(d / f"{a.bench}-00000-of-00001.parquet")))[0])
    items = {}
    for i in range(it.num_rows):
        iid = it.column("item_id")[i].as_py()
        c = it.column("item_content")[i].as_py()
        try:
            q = json.loads(c["input"][0]); ref = json.loads(c["references"][0])
        except Exception:
            continue
        items[iid] = {"id": iid, "input": q.get("question", ""), "choices": list(q.get("options") or []), "target": int(ref.get("answer_index", -1)),
                      "class": q.get("category"), "src": q.get("src")}
    print(f"items: {len(items)}")
    # 응답
    acc = defaultdict(lambda: defaultdict(list))
    files = sorted(p for p in glob.glob(str(d / f"{a.bench}-*-of-*.parquet")) if "of-00001" not in p)
    for f in files:
        pf = pq.ParquetFile(f)
        for rg in range(pf.num_row_groups):
            t = pf.read_row_group(rg, columns=["response_id", "model", "scores"])
            rids, models, scores = t.column("response_id").to_pylist(), t.column("model").to_pylist(), t.column("scores").to_pylist()
            for rid, m, sc in zip(rids, models, scores):
                name = (m or {}).get("name") or "?"
                iid = rid[: rid.rfind("_" + name + "_")] if ("_" + name + "_") in rid else rid.rsplit("_", 2)[0]
                vals = (sc or {}).get("value") or []
                if iid in items and vals:
                    acc[name][iid].append(float(vals[0]))
        print(f"  {Path(f).name}: 모델 {len(acc)}", flush=True)
    # 밀집 블록: 모델 50개 이상이 푼 항목만, 그 항목의 95% 이상을 푼 모델만 (OpenEval 의 MMLU-Pro 는 1,000건 공통 부분집합 + 11개 모델 전수)
    item_models = defaultdict(int)
    for m in acc:
        for k in acc[m]:
            item_models[k] += 1
    keys = sorted(k for k in items if item_models[k] >= 50)
    models = [m for m in acc if sum(1 for k in keys if k in acc[m]) >= 0.95 * len(keys)]
    keep = [k for k in keys if all(k in acc[m] for m in models)]
    correct = [[1 if (sum(acc[m][k]) / len(acc[m][k])) >= 0.5 else 0 for k in keep] for m in models]
    obj = {"source": f"OpenEval {a.bench} (Open-Eval-Commons, CC-BY-NC-4.0), metric {list(acc[models[0]].keys())[:0]}chain_of_thought_correctness", "models": models, "items": keep, "correct": correct,
           "note": f"dense block: models {len(models)} of {len(acc)} covering >=95% of items solved by >=50 models; items {len(keep)}; responses sampled at temperature 1 (single sample per item)"}
    (out / f"openeval_{a.bench}.matrix.json").write_text(json.dumps(obj), encoding="utf-8")
    with (out / f"openeval_{a.bench}.items.jsonl").open("w", encoding="utf-8") as f:
        for k in keep:
            f.write(json.dumps(items[k], ensure_ascii=False) + "\n")
    print(f"행렬 모델 {len(models)} × 항목 {len(keep)}; 모델 예: {models[:12]}")
    print("전체 모델 수:", len(acc), "커버리지 낮은 모델 예:", [m for m in acc if m not in models][:8])


if __name__ == "__main__":
    main()
