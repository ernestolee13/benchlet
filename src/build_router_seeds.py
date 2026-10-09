"""다지 라우터(의도 분류) 축약 시드. 라벨이 77~150개라 글자 선택이 아니라 라벨 이름을 답한다(러너 mode=label).

원천
  BANKING77 (PolyAI, CC-BY-4.0): 은행 고객 문의 3,080건 test, 의도 77개
  CLINC150 (Larson et al. 2019, CC-BY-3.0): 일반 비서 질의 test 4,500건, 의도 150개 (oos 제외)

표본은 2026-10-09 Haiku 5.5·4.5 실측(라벨 10·50·77·150개)과 같은 난수(라벨 부분집합 seed 1, 항목 seed 3)로 뽑아
그 실측값과 항목이 같다. 행렬이 없으므로 경로 B(클래스 층화 없음, 원천 분포 그대로 무작위 100건).

사용: python3 src/build_router_seeds.py --scratch <scratch>   (scratch/cand/router/{banking77_test.csv,clinc_full.json})
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED_LABELS, SEED_ITEMS, N = 1, 3, 100

QUESTION_B77 = ("Classify the bank customer message into exactly one intent label from the allowed list. "
                "Pick the label whose definition matches what the customer is asking for, not just shared words.")
QUESTION_CLINC = ("Classify the user utterance into exactly one intent label from the allowed list. "
                  "Pick the label whose meaning matches what the user wants, not just shared words.")

BENCHES = {
    "banking77-router-mini": dict(src="banking77", subset=None, question=QUESTION_B77, license="CC-BY-4.0",
                                  prior="원천에 모델별 항목 출력 없음. 같은 100건을 json_schema enum + 자기보고 confidence 로 돌린 2026-10-09 실측: Haiku 5.5 83% (ECE .078), Haiku 4.5 80% (ECE .081). 라벨 번호 한 토큰 출력은 64%",
                                  attribution="BANKING77 (Casanueva et al. 2020, PolyAI), test split 3,080 messages, 77 intents",
                                  summary="은행 고객 문의를 의도 77개 중 하나로", unit="query", domain=["banking77", "router", "public-seed", "english"]),
    "clinc150-router-mini": dict(src="clinc150", subset=None, question=QUESTION_CLINC, license="CC-BY-3.0",
                                 prior="원천에 모델별 항목 출력 없음. 같은 100건을 json_schema enum + 자기보고 confidence 로 돌린 2026-10-09 실측: Haiku 5.5 91% (ECE .063), Haiku 4.5 86% (ECE .085)",
                                 attribution="CLINC150 (Larson et al. 2019), test split 4,500 in-scope utterances, 150 intents",
                                 summary="비서 질의를 의도 150개 중 하나로", unit="query", domain=["clinc150", "router", "public-seed", "english"]),
    "clinc50-router-mini": dict(src="clinc150", subset=50, question=QUESTION_CLINC, license="CC-BY-3.0",
                                prior="원천에 모델별 항목 출력 없음. 같은 100건을 json_schema enum + 자기보고 confidence 로 돌린 2026-10-09 실측: Haiku 5.5 96%, Haiku 4.5 97%. 라벨 10개 부분집합은 둘 다 98% 라 벤치로 두지 않았다",
                                attribution="CLINC150 (Larson et al. 2019), test split, 50 of 150 intents (random subset, seed 1)",
                                summary="비서 질의를 의도 50개 중 하나로 (150개 중 부분집합)", unit="query", domain=["clinc150", "router", "public-seed", "english"]),
}


def load(src: str, S: Path):
    if src == "banking77":
        rows = list(csv.DictReader(open(S / "banking77_test.csv", encoding="utf-8")))
        rows = [(r["text"], r["category"]) for r in rows]
    else:
        d = json.loads((S / "clinc_full.json").read_text(encoding="utf-8"))
        rows = [(t, l) for t, l in d["test"]]
    return rows, sorted({l for _, l in rows})


def build(name: str, cfg: dict, S: Path) -> None:
    rows, labels = load(cfg["src"], S)
    n_total = len(rows)
    if cfg["subset"]:
        labels = sorted(random.Random(SEED_LABELS).sample(labels, cfg["subset"]))
        rows = [r for r in rows if r[1] in labels]
    sample = random.Random(SEED_ITEMS).sample(rows, min(N, len(rows)))
    pos = {r: i for i, r in enumerate(rows)}
    items = []
    for k, (text, label) in enumerate(sample):
        items.append({
            "id": f"{name}-{k:04d}", "input": text, "question": cfg["question"], "choices": labels,
            "target": labels.index(label), "type": "multiclass", "label_source": "machine", "class": label,
            "difficulty": None, "cluster": None, "evidence": f"source label {label}",
            "provenance": {"generator": "build_router_seeds.py", "seed": SEED_ITEMS, "verifier": "source label",
                           "label_path": 1, "read_by_human": False, "read_by_agent": False,
                           "source_key": f"{cfg['src']}:{pos[(text, label)]}"},
            "metadata": {"n_labels": len(labels)},
        })
    jp = ROOT / "tasks" / f"{name}.jsonl"
    jp.write_text("".join(json.dumps(it, ensure_ascii=False) + "\n" for it in items), encoding="utf-8")
    strata = {}
    for it in items:
        strata[it["class"]] = strata.get(it["class"], 0) + 1
    man = {
        "name": name, "version": 1,
        "task_signature": {"goal": "route", "answer": f"choice({len(labels)})", "prob_use": "accuracy_only", "label": "machine",
                           "unit": cfg["unit"], "language": "en", "n": len(items)},
        "question": cfg["question"], "choices": labels,
        "choices_note": f"라벨 {len(labels)}개 고정. 글자 선택이 아니라 라벨 이름을 답하는 러너 모드(label)로 돌린다. 확률 없음",
        "generator": {"script": "src/build_router_seeds.py", "seed": SEED_ITEMS},
        "source": f"{cfg['attribution']} 에서 무작위 100건 (전체 {len(rows)}건)",
        "domain": cfg["domain"], "visibility": "full",
        "items_sha256": hashlib.sha256(jp.read_bytes()).hexdigest(),
        "license": cfg["license"],
        "attribution": {"items": cfg["attribution"],
                        "model_responses": cfg["prior"],
                        "method": "random sample of the test split (seed 3); label subset by seed 1 where noted. No per-model matrix"},
        "distill": {"method": "random", "n": len(items), "n_items_total": len(rows), "n_labels": len(labels),
                    "classes_in_sample": len(strata), "selected_keys_in_full": [it["provenance"]["source_key"] for it in items]},
        "review": {"checks_run": 0, "human_reviewed_fraction": 0.0, "flagged": 0, "decided": 0},
        "note": (f"{cfg['summary']}. 원천 라벨을 정답으로 쓴다. 비슷한 의도(예: card_arrival 과 card_delivery_estimate)가 많아 "
                 "라벨 정의를 읽고 고르는 판단이 필요하다. 선택지가 많으면 첫 토큰 로그확률을 못 쓰므로 모든 모델이 라벨 이름 생성으로 돌고 "
                 "정확도만 본다"),
        "taxonomy": {"domain": ["agent-tools", "customer-support"], "input_kind": "query", "source_kind": "public-distilled", "language": "en"},
        "keywords": ["라우팅", "의도 분류", "다지선택", "intent", "router"],
    }
    mp = ROOT / "tasks" / f"{name}.manifest.yaml"
    mp.write_text(yaml.safe_dump(man, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print(f"{name}: items {len(items)} labels {len(labels)} classes {len(strata)} total {len(rows)}/{n_total}")


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--scratch", required=True); ap.add_argument("--only")
    a = ap.parse_args()
    S = Path(a.scratch) / "cand" / "router"
    for name, cfg in BENCHES.items():
        if a.only and a.only != name:
            continue
        build(name, cfg, S)


if __name__ == "__main__":
    main()
