"""축약 시드 매니페스트에 원천 리더보드 모델들의 「이 100건 정확도」를 붙인다.

우리가 돌린 결과가 아니라 원천(HELM, BFCL-Result, JudgeBench, RewardBench 2, metabench)이 그 모델을 돌린 항목별 정오에서 계산한 값이다.
프롬프트·채점 방식이 우리 러너와 다르므로 갤러리에는 「원천 결과(참고)」로 따로 보인다.

사용: python3 src/attach_source_results.py --scratch <scratch> [--only <bench>]
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]

# 벤치 → (행렬 파일들, 원천 설명, 모델 이름 정리 함수)
def _helm(name):
    return lambda S: [S / "exp" / "helm" / f"{name}.matrix.json"]


MATRIX = {
    "mmlu-pro-mini": (_helm("cap_mmlu_pro_all"), "HELM capabilities v1.15.0 (CoT 채점)"),
    "openbookqa-mini": (_helm("lite_openbookqa"), "HELM lite v1.13.0"),
    "bbq-mini": (_helm("safety_bbq"), "HELM safety v1.17.0"),
    "legal-lobbying-mini": (_helm("lite_legalbench_corporate_lobbying"), "HELM lite v1.13.0"),
    "tool-call-gate-mini": (lambda S: [S / "cand" / "bfcl" / "bfcl_live_simple.matrix.json", S / "cand" / "bfcl" / "bfcl_live_irrelevance.matrix.json"], "BFCL-Result 2025-12-16 (함수 호출 채점)"),
    "tool-pick-mini": (lambda S: [S / "cand" / "bfcl" / "bfcl_multiple.matrix.json", S / "cand" / "bfcl" / "bfcl_live_multiple.matrix.json"], "BFCL-Result 2025-12-16 (함수 호출 채점)"),
    "judge-pair-mini": (lambda S: [S / "cand" / "jb" / "judgebench.matrix.json"], "JudgeBench 심판 출력 (두 순서 모두 일치해야 정답)"),
    "best-of-4-mini": (lambda S: [S / "cand" / "rb2" / "rb2.matrix.json"], "RewardBench 2 results"),
    "arc-challenge-mini": (lambda S: [S / "matrices" / "arc.matrix.json"], "metabench (Open LLM Leaderboard v1)"),
    "truthfulqa-mc1-mini": (lambda S: [S / "matrices" / "truthfulqa.matrix.json"], "metabench (Open LLM Leaderboard v1)"),
    "winogrande-mini": (lambda S: [S / "matrices" / "winogrande.matrix.json"], "metabench (Open LLM Leaderboard v1)"),
    "hellaswag-mini": (lambda S: [S / "matrices" / "hellaswag.matrix.json"], "metabench (Open LLM Leaderboard v1)"),
    "mmlu-mini": (lambda S: [S / "matrices" / "mmlu.matrix.json"], "metabench (Open LLM Leaderboard v1)"),
}

FRONTIER = re.compile(r"gpt-5|gpt-4\.1|gpt-4o|o3|o4-mini|o1|claude|gemini|grok|qwen3|qwen_qwen3|deepseek|llama-4|llama-3\.[13]|mistral-large|glm", re.I)


def load_matrix(p: Path) -> tuple[list, dict]:
    m = json.loads(p.read_text())
    C = m["correct"]
    if isinstance(C, dict):
        rows = {k: [None if x is None else int(bool(x)) for x in v] for k, v in C.items()}
    else:
        rows = {k: [int(bool(x)) for x in v] for k, v in zip(m["models"], C)}
    return m["items"], rows


def pretty(model: str) -> str:
    """원천별 모델 표기를 읽기 좋게. HELM 'org_model' → 'org/model', JudgeBench 'judge:model' → 'model (judge)'"""
    if ":" in model:
        judge, m = model.split(":", 1)
        return m if judge == "arena_hard" else f"{m} ({judge.replace('_', ' ')})"
    return model.replace("_", "/", 1) if "_" in model and "/" not in model else model


def attach(name: str, S: Path) -> dict | None:
    mp = ROOT / "tasks" / f"{name}.manifest.yaml"
    ip = ROOT / "tasks" / f"{name}.jsonl"
    if name not in MATRIX or not mp.exists() or not ip.exists():
        return None
    files, source = MATRIX[name]
    keys = [json.loads(l)["provenance"]["source_key"] for l in ip.read_text(encoding="utf-8").split("\n") if l.strip()]
    acc_sub, acc_full, n_items = {}, {}, 0
    hits = {}
    for f in files(S):
        if not f.exists():
            print(f"{name}: 행렬 없음 {f}"); return None
        items, rows = load_matrix(f)
        pos = {k: i for i, k in enumerate(items)}
        sel = [pos[k] for k in keys if k in pos]
        n_items += len(sel)
        for model, vec in rows.items():
            vals = [vec[i] for i in sel if vec[i] is not None]
            full = [x for x in vec if x is not None]
            if not vals or len(full) < 0.9 * len(vec):
                continue
            h = hits.setdefault(model, [0, 0, 0, 0])
            h[0] += sum(vals); h[1] += len(vals); h[2] += sum(full); h[3] += len(full)
    models = []
    for model, (hs, ns, hf, nf) in hits.items():
        if ns < 0.9 * n_items:
            continue
        models.append({"model": pretty(model), "acc_subset": round(hs / ns, 4), "acc_full": round(hf / nf, 4), "n_subset": ns,
                       "frontier": bool(FRONTIER.search(model))})
    models.sort(key=lambda x: -x["acc_subset"])
    man = yaml.safe_load(mp.read_text(encoding="utf-8"))
    man["source_results"] = {"source": source, "note": "원천이 그 모델을 돌린 항목별 정오에서 이 벤치의 항목만 골라 계산한 정확도. 프롬프트·채점 방식이 이 갤러리의 실행과 다르므로 참고값이다",
                             "n_models": len(models), "n_frontier": sum(1 for m in models if m["frontier"]),
                             "models": models[:200]}
    mp.write_text(yaml.safe_dump(man, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    top = ", ".join(f"{m['model']} {m['acc_subset']*100:.0f}" for m in models[:4])
    print(f"{name}: 모델 {len(models)} (프런티어 {man['source_results']['n_frontier']}) | {top}")
    return man["source_results"]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--scratch", required=True); ap.add_argument("--only")
    a = ap.parse_args()
    for name in MATRIX:
        if a.only and a.only != name:
            continue
        attach(name, Path(a.scratch))


if __name__ == "__main__":
    main()
