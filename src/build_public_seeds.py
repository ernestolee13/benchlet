#!/usr/bin/env python3
"""공개 벤치 축약 시드 생성기. 원천 항목(HF datasets-server 덤프) + metabench 정오 행렬 → `benchlet distill` → 확장 형식 항목과 매니페스트.

원천은 리포에 넣지 않는다(스크래치 덤프). 축약 보고(검증 모델 MAE 등)는 매니페스트 `distill` 에 남는다.
    python3 src/build_public_seeds.py --src <덤프 폴더> --matrices <metabench data 폴더> [--n 100]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "bench-core"))
from benchlet.distill import distill, render  # noqa: E402

SEED = 20261003
LETTERS = "ABCDEFGH"

BENCHES = {
    "arc-challenge-mini": {
        "src": "arc_challenge_test.jsonl", "matrix": "arc", "license": "CC-BY-SA-4.0", "source_name": "ARC-Challenge test (allenai/ai2_arc)",
        "question": "다음 과학 문제의 정답은 무엇인가. 보기 중 하나만 맞다. 입력은 영어 문제와 보기다.",
        "sig": {"goal": "classify", "answer": "choice(4)", "prob_use": "accuracy_only", "label": "machine", "unit": "query"},
        "row": lambda r: {"input": r["question"], "choices": list(r["choices"]["text"]), "target": list(r["choices"]["label"]).index(r["answerKey"]),
                          "class": f"{len(r['choices']['text'])}-way", "evidence": f"ARC answerKey {r['answerKey']}", "key": r["id"]},
    },
    "hellaswag-mini": {
        "src": "hellaswag_val.jsonl", "matrix": "hellaswag", "license": "MIT", "source_name": "HellaSwag validation (Rowan/hellaswag)",
        "question": "이 상황 서술 다음에 가장 자연스럽게 이어지는 문장은 무엇인가. 보기 넷 중 하나만 맞다. 입력은 영어 상황과 보기다.",
        "sig": {"goal": "classify", "answer": "choice(4)", "prob_use": "accuracy_only", "label": "machine", "unit": "query"},
        "row": lambda r: {"input": r["ctx"], "choices": list(r["endings"]), "target": int(r["label"]), "class": r["activity_label"][:40],
                          "evidence": f"HellaSwag label {r['label']} (source {r['source_id']})", "key": str(r["ind"])},
    },
    "winogrande-mini": {
        "src": "winogrande_val.jsonl", "matrix": "winogrande", "license": "CC-BY", "source_name": "WinoGrande XL validation (allenai/winogrande)",
        "question": "문장의 빈칸(_)에 들어갈 것은 둘 중 무엇인가. 입력은 영어 문장과 보기 둘이다.",
        "sig": {"goal": "classify", "answer": "choice(2)", "prob_use": "accuracy_only", "label": "machine", "unit": "sentence"},
        "row": lambda r: {"input": r["sentence"], "choices": [r["option1"], r["option2"]], "target": int(r["answer"]) - 1, "class": "pronoun",
                          "evidence": f"WinoGrande answer {r['answer']}", "key": str(r["_row_idx"])},
    },
    "truthfulqa-mc1-mini": {
        "src": "truthfulqa_mc.jsonl", "matrix": "truthfulqa", "license": "Apache-2.0", "source_name": "TruthfulQA MC1 (truthfulqa/truthful_qa multiple_choice)",
        "question": "이 질문에 사실에 맞는 답은 보기 중 무엇인가. 흔한 오해나 미신이 아니라 검증된 사실을 고른다. 하나만 맞다. 입력은 영어 질문과 보기다.",
        "sig": {"goal": "classify", "answer": "choice(n)", "prob_use": "accuracy_only", "label": "machine", "unit": "query"},
        "row": lambda r: {"input": r["question"], "choices": list(r["mc1_targets"]["choices"]), "target": list(r["mc1_targets"]["labels"]).index(1),
                          "class": f"{len(r['mc1_targets']['choices'])}-way", "evidence": "TruthfulQA mc1 label", "key": str(r["_row_idx"])},
    },
    "openbookqa-mini": {
        "src": "helm_commonsense.items.jsonl", "matrix": "helm_commonsense", "license": "Apache-2.0", "source_name": "OpenBookQA test (HELM Lite v1.0.0 commonsense scenario, 31 models incl. commercial)",
        "question": "다음 초등 과학 상식 문제의 정답은 보기 넷 중 무엇인가. 입력은 영어 문제와 보기다.",
        "sig": {"goal": "classify", "answer": "choice(4)", "prob_use": "accuracy_only", "label": "machine", "unit": "query"},
        "row": lambda r: {"input": r["input"], "choices": list(r["choices"]), "target": int(r["target"]), "class": "science-fact",
                          "evidence": "OpenBookQA answerKey (HELM references tag correct)", "key": r["id"]},
        "matrix_source": "HELM Lite v1.0.0 crfm-helm-public per_instance_stats (exact_match), 31 models",
    },
    "mmlu-pro-mini": {
        "src": "openeval_mmlu_pro.items.jsonl", "matrix": "openeval_mmlu_pro", "license": "MIT", "source_name": "MMLU-Pro (TIGER-Lab) 1,000건 공통 부분집합, 항목 본문은 OpenEval item 테이블",
        "question": "다음 시험 문제의 정답은 보기 중 무엇인가. 보기는 최대 열 개이고 하나만 맞다. 입력은 영어 문제와 분야, 보기다.",
        "sig": {"goal": "classify", "answer": "choice(n)", "prob_use": "accuracy_only", "label": "machine", "unit": "query"},
        "row": lambda r: {"input": f"[{r['class']}] {r['input']}", "choices": list(r["choices"]), "target": int(r["target"]), "class": r["class"],
                          "evidence": "MMLU-Pro answer_index", "key": r["id"]},
        "matrix_source": "OpenEval (Open-Eval-Commons, CC-BY-NC-4.0) chain_of_thought_correctness, 2024~2026 모델 121개(GPT-5.x, Claude 3.5, Qwen 3 등), 응답 1회 샘플",
    },
    "mmlu-mini": {
        "src": "mmlu_test.jsonl", "matrix": "mmlu", "license": "MIT", "source_name": "MMLU test (cais/mmlu all)",
        "question": "다음 시험 문제의 정답은 보기 넷 중 무엇인가. 입력은 영어 문제와 과목, 보기다.",
        "sig": {"goal": "classify", "answer": "choice(4)", "prob_use": "accuracy_only", "label": "machine", "unit": "query"},
        "row": lambda r: {"input": f"[{r['subject']}] {r['question']}", "choices": list(r["choices"]), "target": int(r["answer"]), "class": r["subject"],
                          "evidence": f"MMLU answer {r['answer']}", "key": str(r["_row_idx"])},
    },
}


def load_rows(p: Path) -> list:
    """덤프를 읽는다. 재개하며 끊긴 줄은 건너뛰고 _row_idx 중복은 첫 것만 쓴다."""
    rows, seen = [], set()
    for l in p.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        k = r.get("_row_idx", r.get("id"))
        if k in seen:
            continue
        seen.add(k); rows.append(r)
    return rows


def shuffle_choices(it: dict, rng: random.Random) -> dict:
    """정답 위치 편향을 막으려고 선택지를 항목별 결정론적으로 섞는다(원천 정답 위치는 metadata 에 남긴다)."""
    order = list(range(len(it["choices"])))
    rng.shuffle(order)
    new_choices = [it["choices"][k] for k in order]
    new_target = order.index(it["target"])
    it["metadata"] = {"source_target": it["target"], "shuffle_order": order}
    it["choices"], it["target"] = new_choices, new_target
    return it


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True); ap.add_argument("--matrices", required=True); ap.add_argument("--n", type=int, default=100)
    ap.add_argument("--only"); ap.add_argument("--method", default="stratified"); ap.add_argument("--n-override", type=int)
    a = ap.parse_args()
    src, mats = Path(a.src), Path(a.matrices)
    for name, spec in BENCHES.items():
        if a.only and a.only != name:
            continue
        rows = load_rows(src / spec["src"]) if (src / spec["src"]).exists() else []
        mp = mats / f"{spec['matrix']}.matrix.json"
        if not (src / spec["src"]).exists() and (mats / spec["src"]).exists():
            rows = load_rows(mats / spec["src"])
        if not mp.exists():
            print(f"{name}: 행렬 없음 {mp}"); continue
        mx = json.loads(mp.read_text(encoding="utf-8"))
        # 행렬 항목 키 → 원천 행 매핑 (키는 metabench 가 쓴 식별자. prepare_matrices.py 가 통일한다)
        by_key = {}
        for r in rows:
            try:
                it = spec["row"](r)
            except Exception:
                continue
            by_key[it["key"]] = it
        keep = [i for i, k in enumerate(mx["items"]) if k in by_key]
        if len(keep) < 40:
            print(f"{name}: 행렬 항목과 원천이 {len(keep)}건만 맞는다"); continue
        n_use = a.n_override or min(a.n, max(40, len(keep) // 5))     # 원천이 작으면(500) 100 대신 더 작게
        res = distill(mx, n=n_use, seed=SEED, method=a.method, keep_item_filter=lambda i, keep=set(keep): i in keep)
        print(f"== {name}\n{render(res)}")
        rng = random.Random(f"{SEED}-{name}")
        items = []
        for j, key in enumerate(res["selected"]):
            it = dict(by_key[key])
            it = shuffle_choices(it, random.Random(f"{SEED}-{name}-{key}"))
            items.append({"id": f"{name}-{j:03d}", "input": it["input"], "question": spec["question"], "choices": it["choices"], "target": it["target"],
                          "type": "binary" if len(it["choices"]) == 2 else "multiclass", "label_source": "machine", "class": it["class"],
                          "difficulty": "easy" if res["difficulty"][key] >= 0.8 else ("hard" if res["difficulty"][key] <= 0.35 else "medium"),
                          "cluster": None, "evidence": it["evidence"],
                          "provenance": {"generator": "build_public_seeds.py", "seed": SEED, "verifier": "source answer key", "label_path": 1,
                                         "read_by_human": False, "read_by_agent": False, "source_key": key},
                          "metadata": dict(it["metadata"], source_difficulty=res["difficulty"][key], irt_b=(res.get("irt_b") or {}).get(key))})
        p = ROOT / "tasks" / f"{name}.jsonl"
        p.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in items), encoding="utf-8")
        sha = hashlib.sha256(p.read_bytes()).hexdigest()
        man = {"name": name, "version": 1, "task_signature": dict(spec["sig"], language="en", n=len(items)), "question": spec["question"],
               "choices": None, "choices_note": "항목마다 선택지 순서를 결정론적으로 섞었다. 원천 정답 위치는 metadata.source_target",
               "generator": {"script": "src/build_public_seeds.py", "seed": SEED}, "source": f"{spec['source_name']} 에서 metabench 정오 행렬(모델 {res['n_models']}개)로 {len(items)}건 축약",
               "domain": [name.replace("-mini", ""), "public-seed", "english"], "visibility": "full", "items_sha256": sha, "license": spec["license"],
               "attribution": {"items": spec["source_name"], "model_responses": spec.get("matrix_source", "metabench (Kipnis et al. 2025) Zenodo 12819251, CC-BY-4.0"), "method": res["method"]},
               "distill": {k: res[k] for k in ("n", "seed", "n_items_total", "n_items_usable", "n_models", "fit_models", "val_models", "val", "val_unweighted", "baseline_val", "fit") if k in res},
               "review": {"checks_run": 0, "human_reviewed_fraction": 0.0, "flagged": 0, "decided": 0},
               "note": "공개 벤치의 축약 시드. 라벨은 원천 정답 키. 검증 모델에서의 전체 정확도 재현 오차를 distill.val 에 적었다"}
        (ROOT / "tasks" / f"{name}.manifest.yaml").write_text(yaml.safe_dump(man, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
        sums = ROOT / "labels" / "SHA256SUMS"
        lines = [l for l in sums.read_text().splitlines() if not l.endswith(f"tasks/{name}.jsonl")]
        sums.write_text("\n".join(lines + [f"{sha}  tasks/{name}.jsonl"]) + "\n")
        print(f"{name}: {len(items)}건 sha {sha[:12]}")


if __name__ == "__main__":
    main()
