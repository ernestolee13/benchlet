#!/usr/bin/env python3
"""metabench 정오 행렬(long CSV: source,item,correct) + 프롬프트 파일 → 우리 원천 키로 정렬한 matrix JSON.

프롬프트는 few-shot 전체라 마지막 블록이 평가 항목이다. 벤치마다 마지막 블록을 뽑아 원천 덤프의 텍스트와 맞춘다.
모델은 메모리와 시간 때문에 벤치마다 max_models 개만 무작위(시드)로 쓴다. 정렬된 항목만 행렬에 남긴다.
    python3 src/prepare_matrices.py --data <benchmark-data> --src <덤프 폴더> --out <폴더> [--only arc]
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
from collections import defaultdict
from pathlib import Path

csv.field_size_limit(10 ** 9)
SEED = 20261003


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip().lower()


def hs_preprocess(text: str) -> str:
    """lm-eval hellaswag 의 전처리와 같다: [title] → ". ", 대괄호 태그 제거, 이중 공백 정리."""
    text = text.strip().replace(" [title]", ". ")
    text = re.sub(r"\[.*?\]", "", text)
    return text.replace("  ", " ")


def last_block(prompt: str) -> str:
    parts = [p for p in prompt.strip().split("\n\n") if p.strip()]
    return parts[-1] if parts else prompt


def key_arc(prompt, rows_index):
    blk = last_block(prompt)
    m = re.search(r"Question:\s*(.*?)(?:\nAnswer:|$)", blk, re.S)
    return rows_index.get(norm(m.group(1))) if m else None


def key_hellaswag(prompt, rows_index):
    blk = last_block(prompt)
    # "{activity}: {ctx}" + 정답 ending. ctx 앞부분(60자)으로 찾는다
    for k, v in rows_index.items():
        pass
    return rows_index.get(norm(blk)[:120])


def key_truthfulqa(prompt, rows_index):
    qs = re.findall(r"Q:\s*(.*?)\n", prompt + "\n")
    return rows_index.get(norm(qs[-1])) if qs else None


def key_winogrande(prompt, rows_index):
    return rows_index.get(norm(last_block(prompt)))


def key_mmlu(prompt, rows_index):
    blk = last_block(prompt)
    q = blk.split("\n")[0]
    return rows_index.get(norm(q))


def build_index(bench, rows):
    idx = {}
    for r in rows:
        if bench == "arc":
            idx[norm(r["question"])] = r["id"]
        elif bench == "hellaswag":
            idx[norm(f"{r['activity_label']}: {hs_preprocess(r['ctx'])}")[:120]] = str(r["_row_idx"])
        elif bench == "truthfulqa":
            idx[norm(r["question"])] = str(r["_row_idx"])
        elif bench == "winogrande":
            # lm-eval winogrande(partial): 마지막 블록 = 빈칸(_) 앞 접두 + 정답 선택지
            opt = r["option1"] if str(r["answer"]) == "1" else r["option2"]
            idx[norm(r["sentence"].split("_")[0] + " " + opt)] = str(r["_row_idx"])
        elif bench == "mmlu":
            idx.setdefault(norm(r["question"]), str(r["_row_idx"]))
    return idx


KEYFN = {"arc": key_arc, "hellaswag": key_hellaswag, "truthfulqa": key_truthfulqa, "winogrande": key_winogrande, "mmlu": key_mmlu}


def list_models(csv_path: Path) -> list:
    models, seen = [], set()
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["source"] not in seen:
                seen.add(r["source"]); models.append(r["source"])
    return models


def read_long(csv_path: Path, max_models: int, rng: random.Random, keep_items: set, chosen: set | None = None):
    """long CSV 를 읽는다. chosen(모델 집합)이 없으면 파일의 모델 목록에서 표본을 뽑는다(벤치 전체에서 한 번만 뽑아 넘기는 게 맞다)."""
    models = list_models(csv_path)
    if chosen is None:
        chosen = set(rng.sample(models, min(max_models, len(models))))
    mat = defaultdict(dict)
    with csv_path.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["source"] in chosen and r["item"] in keep_items:
                v = r["correct"].strip().lower()
                mat[r["source"]][r["item"]] = 1 if v in ("1", "1.0", "true") else 0
    return models, mat


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", required=True); ap.add_argument("--src", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--only"); ap.add_argument("--max-models", type=int, default=800)
    a = ap.parse_args()
    data, src, out = Path(a.data), Path(a.src), Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    rng = random.Random(SEED)
    srcfile = {"arc": "arc_challenge_test.jsonl", "hellaswag": "hellaswag_val.jsonl", "truthfulqa": "truthfulqa_mc.jsonl", "winogrande": "winogrande_val.jsonl", "mmlu": "mmlu_test.jsonl"}
    for bench in ["arc", "truthfulqa", "winogrande", "hellaswag", "mmlu"]:
        if a.only and a.only != bench:
            continue
        rows, seen_idx = [], set()
        for l in (src / srcfile[bench]).read_text(encoding="utf-8").splitlines():
            if not l.strip():
                continue
            try:
                r = json.loads(l)
            except json.JSONDecodeError:
                continue              # 덤프 재개 시 끊긴 줄
            if r.get("_row_idx") in seen_idx:
                continue
            seen_idx.add(r.get("_row_idx")); rows.append(r)
        index = build_index(bench, rows)
        # 프롬프트 → 원천 키
        files = sorted(data.glob("mmlu_*_prompts.csv")) if bench == "mmlu" else [data / f"{bench}_prompts.csv"]
        item_key = {}          # (file stem, item) → source key
        n_prompts = 0
        for pf in files:
            with pf.open(encoding="utf-8") as f:
                for r in csv.DictReader(f):
                    n_prompts += 1
                    k = KEYFN[bench](r["prompt"], index)
                    if k:
                        item_key[(pf.stem.replace("_prompts", ""), r["item"])] = k
        print(f"{bench}: 프롬프트 {n_prompts}, 원천 정렬 {len(item_key)}", flush=True)
        # 행렬
        mats = {}
        all_models = None
        csvs = sorted(p for p in data.glob("mmlu_*.csv") if not p.name.endswith("_prompts.csv")) if bench == "mmlu" else [data / f"{bench}.csv"]
        chosen = None
        if len(csvs) > 1:
            # 과목 파일마다 모델 목록이 달라서, 첫 파일 기준으로 한 번만 표본을 뽑아 전 파일에 같은 집합을 쓴다
            base = list_models(csvs[0])
            chosen = set(random.Random(SEED).sample(base, min(a.max_models, len(base))))
            all_models = base
        for cf in csvs:
            stem = cf.stem
            keep = {it for (s, it) in item_key if s == stem}
            if not keep:
                continue
            models, mat = read_long(cf, a.max_models, random.Random(SEED), keep, chosen)
            if all_models is None:
                all_models = models
            for m, d in mat.items():
                for it, v in d.items():
                    mats.setdefault(m, {})[item_key[(stem, it)]] = v
        keys = sorted({k for d in mats.values() for k in d})
        models = [m for m in mats if len(mats[m]) >= 0.9 * len(keys)]
        correct = [[mats[m].get(k, 0) for k in keys] for m in models]
        obj = {"source": f"metabench Zenodo 12819251 ({bench}), CC-BY-4.0", "models": models, "items": keys, "correct": correct,
               "note": f"models sampled {len(models)} of {len(all_models or [])}; items aligned {len(keys)}"}
        (out / f"{bench}.matrix.json").write_text(json.dumps(obj), encoding="utf-8")
        print(f"{bench}: 행렬 모델 {len(models)} × 항목 {len(keys)} → {out / (bench + '.matrix.json')}", flush=True)


if __name__ == "__main__":
    main()
