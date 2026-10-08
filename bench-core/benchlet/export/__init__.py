"""내보내기: Inspect JSONL, lm-eval 태스크 YAML, HF eval.yaml. 글자 접두는 여기서만 붙는다."""
from __future__ import annotations

import json
from pathlib import Path

import yaml

from ..runner.client import LETTERS
from ..schema.load import Bench


def to_inspect_jsonl(bench: Bench, out: Path) -> Path:
    """Inspect Sample: input · choices · target(글자) · id · metadata."""
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        for it in bench.items:
            rec = {"id": it["id"], "input": f"{it['question']}\n\n{it['input']}", "choices": list(it["choices"]),
                   "target": LETTERS[it["target"]],
                   "metadata": {k: it.get(k) for k in ("class", "label_source", "difficulty", "cluster", "evidence")}}
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return out


def to_lm_eval_yaml(bench: Bench, out_dir: Path) -> Path:
    """lm-evaluation-harness 태스크. 항목은 같은 폴더의 items.jsonl (Inspect 형식과 같은 파일을 쓴다)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    items = to_inspect_jsonl(bench, out_dir / "items.jsonl")
    n = max(len(it["choices"]) for it in bench.items)
    task = {
        "task": bench.name,
        "dataset_path": "json",
        "dataset_kwargs": {"data_files": {"test": str(items.name)}},
        "test_split": "test",
        "output_type": "multiple_choice",
        "doc_to_text": "{{input}}\n\n" + "\n".join(f"{LETTERS[i]}. {{{{choices[{i}]}}}}" for i in range(n)) + "\n답:",
        "doc_to_choice": [LETTERS[i] for i in range(n)],
        "doc_to_target": "{{ " + " ".join(f"0 if target == '{LETTERS[i]}' else" for i in range(0)) + f"['{','.join(LETTERS[:n])}'.split(',').index(target)] " + "}}",
        "metric_list": [{"metric": "acc", "aggregation": "mean", "higher_is_better": True}],
        "metadata": {"version": bench.manifest.get("version", 1), "note": "결정 규칙 argmax. 확률 팔 결과는 benchlet 결과 파일 참조"},
    }
    task["doc_to_target"] = "{{ '" + ",".join(LETTERS[:n]) + "'.split(',').index(target) }}"
    p = out_dir / f"{bench.name}.yaml"
    p.write_text(yaml.safe_dump(task, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def to_hf_eval_yaml(bench: Bench, out: Path, results: dict | None = None) -> Path:
    """HF Community Evals eval.yaml. 생성 팔은 multiple_choice + choice 로, 확률 팔 결과는 source 링크로."""
    out.parent.mkdir(parents=True, exist_ok=True)
    sig = bench.manifest.get("task_signature") or {}
    doc = {
        "name": bench.name,
        "task_type": "multiple_choice",
        "question_column": "input",
        "choices_column": "choices",
        "answer_column": "target",
        "answer_format": "letter",
        "language": sig.get("language", "ko"),
        "n_items": len(bench.items),
        "metrics": ["accuracy"],
        "note": "결정 규칙 argmax 고정. 임계·온도 보정 없음. 확률 팔(logprob·typed)의 Brier·AUROC 는 source 의 benchlet 결과 파일에 있다",
        "source": bench.manifest.get("generator") or {},
    }
    if results:
        from ..runner.arms import ARMS
        arms_meta = results.get("arms") or {k: dict(ARMS.get(k, {"model": k}), prob_source={"typed": "typed"}.get(ARMS.get(k, {}).get("mode"), "logprob"))
                                            for k in results.get("agg", {})}
        doc["eval_results"] = [{"model": v.get("model"), "provider": v.get("provider"), "prob_source": v.get("prob_source"),
                                "accuracy": round(results["agg"][k]["hit"] / results["agg"][k]["ok"], 4) if results["agg"].get(k, {}).get("ok") else None}
                               for k, v in arms_meta.items()]
    else:
        doc["eval_results"] = "pending"
    out.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out
