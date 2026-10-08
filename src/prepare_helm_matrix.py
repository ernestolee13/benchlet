"""HELM 공개 버킷에서 시나리오 하나의 모델별 항목 정오 행렬과 항목 본문을 내린다.
사용: python3 src/prepare_helm_matrix.py <leaderboard> <scenario_prefix> <out_name> [metric] [outdir]
예: python3 src/prepare_helm_matrix.py capabilities mmlu_pro cap_mmlu_pro "" <scratch>/helm
행렬 파일: {items: [instance_id], models: [name], correct: {model: [0/1/None]}}"""
import json, sys, re, urllib.request, concurrent.futures as cf
from pathlib import Path
B = "https://storage.googleapis.com/crfm-helm-public/"
lb, key, out_name = sys.argv[1], sys.argv[2], sys.argv[3]
metric = sys.argv[4] if len(sys.argv) > 4 else None
def get(u):
    for _ in range(3):
        try: return json.loads(urllib.request.urlopen(u, timeout=120).read())
        except Exception as e: err = e
    print("fail", u[-120:], err); return None
def _ver(s):
    m = re.search(r"v(\d+)\.(\d+)\.(\d+)", s); return tuple(map(int, m.groups())) if m else (0, 0, 0)
_lst = get(f"https://storage.googleapis.com/storage/v1/b/crfm-helm-public/o?prefix={lb}/benchmark_output/releases/&delimiter=/")
rel = max(_lst["prefixes"], key=_ver)      # 최신 릴리스
print("release", rel)
runs = get(B + rel + "runs_to_run_suites.json")
sel = {k: v for k, v in runs.items() if k.startswith(key)}
print(lb, key, "runs", len(sel))
def one(kv):
    run, suite = kv
    m = re.search(r"model=([^,]+)", run).group(1)
    sub = re.search(r"subset=([^,]+)", run); sub = sub.group(1) if sub else ""
    dp = get(B + f"{lb}/benchmark_output/runs/{suite}/{run}/display_predictions.json")
    if not dp: return m, sub, None, None
    met = metric or next((n for n in ("exact_match", "chain_of_thought_correctness", "quasi_exact_match") if n in dp[0]["stats"]), None)
    if met is None:
        pis = get(B + f"{lb}/benchmark_output/runs/{suite}/{run}/per_instance_stats.json")
        if not pis: return m, sub, None, None
        corr = {}
        for p in pis:
            if p.get("train_trial_index", 0) != 0: continue
            st = {s["name"]["name"]: s.get("mean") for s in p["stats"]}
            met = next((n for n in ("exact_match", "quasi_exact_match", "chain_of_thought_correctness") if n in st), None)
            corr[p["instance_id"]] = st.get(met)
        return m, sub, corr, met
    corr = {d["instance_id"]: d["stats"].get(met) for d in dp if d.get("train_trial_index", 0) == 0}
    return m, sub, corr, met
items_text = {}
results = {}
with cf.ThreadPoolExecutor(8) as ex:
    for m, sub, corr, met in ex.map(one, sel.items()):
        if corr is None: continue
        results.setdefault(sub, {})[m] = corr
        results.setdefault("_metric", met)
# 항목 본문: 각 subset 의 첫 run 에서 instances.json
for sub in [s for s in results if s != "_metric"]:
    run = next(k for k in sel if (f"subset={sub}" in k if sub else True))
    inst = get(B + f"{lb}/benchmark_output/runs/{sel[run]}/{run}/instances.json")
    for it in inst or []:
        items_text[(sub, it["id"])] = {"input": it["input"]["text"], "references": [(r["output"]["text"], r.get("tags", [])) for r in it.get("references", [])], "split": it.get("split")}
outdir = Path(sys.argv[5]) if len(sys.argv) > 5 else Path("scratch_helm"); outdir.mkdir(exist_ok=True, parents=True)
for sub in [s for s in results if s != "_metric"]:
    models = sorted(results[sub]); ids = sorted({i for m in models for i in results[sub][m]})
    mat = {"leaderboard": lb, "release": rel, "scenario": key, "subset": sub, "metric": results["_metric"], "items": ids, "models": models,
           "correct": {m: [results[sub][m].get(i) for i in ids] for m in models}}
    name = f"{out_name}{'_' + sub if sub else ''}"
    (outdir / f"{name}.matrix.json").write_text(json.dumps(mat))
    with open(outdir / f"{name}.items.jsonl", "w") as f:
        for i in ids:
            t = items_text.get((sub, i)); 
            if t: f.write(json.dumps({"id": i, **t}, ensure_ascii=False) + "\n")
    cov = sum(1 for m in models for i in ids if results[sub][m].get(i) is not None) / max(1, len(models) * len(ids))
    print(f"  {name}: items {len(ids)} models {len(models)} coverage {cov:.2f} metric {results['_metric']}")
