#!/usr/bin/env python3
"""HELM Lite 공개 버킷(crfm-helm-public)에서 시나리오 하나의 모델×항목 정오 행렬과 항목 본문을 만든다.

per_instance_stats.json(항목별 exact_match) + instances.json(본문·보기·정답)을 모델 실행 폴더마다 읽는다. 인증 없음.
    python3 src/prepare_helm.py --scenario commonsense --version v1.0.0 --out <폴더>
산출: <out>/helm_<scenario>.matrix.json, <out>/helm_<scenario>.items.jsonl (확장 형식 항목, id = HELM instance id)
"""
from __future__ import annotations

import argparse
import json
import urllib.parse
import urllib.request
from pathlib import Path

BUCKET = "https://storage.googleapis.com/crfm-helm-public"
API = "https://storage.googleapis.com/storage/v1/b/crfm-helm-public/o"


def get_json(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "benchlet/0.1"}), timeout=120) as r:
        return json.loads(r.read())


def list_runs(version: str, scenario: str) -> list:
    prefix = f"lite/benchmark_output/runs/{version}/"
    out, token = [], None
    while True:
        url = f"{API}?prefix={urllib.parse.quote(prefix, safe='')}&delimiter=/&maxResults=1000" + (f"&pageToken={token}" if token else "")
        d = get_json(url)
        out += [p[len(prefix):-1] for p in d.get("prefixes", []) if p[len(prefix):].startswith(scenario + ":")]
        token = d.get("nextPageToken")
        if not token:
            break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scenario", default="commonsense"); ap.add_argument("--version", default="v1.0.0"); ap.add_argument("--out", required=True)
    ap.add_argument("--metric", default="exact_match")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    runs = list_runs(a.version, a.scenario)
    print(f"{a.scenario}@{a.version}: 실행 {len(runs)}")
    items, mat, models = {}, {}, []
    for run in runs:
        model = run.split("model=")[-1]
        base = f"{BUCKET}/lite/benchmark_output/runs/{a.version}/{urllib.parse.quote(run, safe='')}"
        try:
            stats = get_json(base + "/per_instance_stats.json")
            if not items:
                for inst in get_json(base + "/instances.json"):
                    refs = inst.get("references") or []
                    choices = [r["output"]["text"] for r in refs]
                    correct = [i for i, r in enumerate(refs) if "correct" in (r.get("tags") or [])]
                    if len(choices) < 2 or len(correct) != 1:
                        continue
                    items[inst["id"]] = {"id": inst["id"], "input": inst["input"]["text"], "choices": choices, "target": correct[0], "split": inst.get("split")}
        except Exception as e:                       # noqa: BLE001
            print(f"  건너뜀 {model}: {type(e).__name__}"); continue
        row = {}
        for ps in stats:
            iid = ps.get("instance_id")
            for st in ps.get("stats", []):
                if st.get("name", {}).get("name") == a.metric:
                    row[iid] = 1 if (st.get("mean") or 0) >= 0.5 else 0
        if row:
            models.append(model); mat[model] = row
    keys = sorted(k for k in items if all(k in mat[m] for m in models))
    obj = {"source": f"HELM Lite {a.version} {a.scenario} (crfm-helm-public), metric {a.metric}", "models": models, "items": keys,
           "correct": [[mat[m][k] for k in keys] for m in models]}
    (out / f"helm_{a.scenario}.matrix.json").write_text(json.dumps(obj), encoding="utf-8")
    with (out / f"helm_{a.scenario}.items.jsonl").open("w", encoding="utf-8") as f:
        for k in keys:
            f.write(json.dumps(items[k], ensure_ascii=False) + "\n")
    print(f"행렬 모델 {len(models)} × 항목 {len(keys)}; 모델: {', '.join(models[:8])} ...")


if __name__ == "__main__":
    main()
