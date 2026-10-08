"""RewardBench 2 결과(allenai/reward-bench-2-results eval-set-scores)에서 모델별 항목별 정오 행렬을 만든다. results==1.0 이면 정답(best-of-4 를 맞힘)."""
import json, urllib.request, concurrent.futures as cf, sys
from pathlib import Path
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
H = "https://huggingface.co/datasets/allenai/reward-bench-2-results/resolve/main/"
d = json.loads(urllib.request.urlopen("https://huggingface.co/api/datasets/allenai/reward-bench-2-results", timeout=60).read())
files = [s["rfilename"] for s in d["siblings"] if s["rfilename"].startswith("eval-set-scores/") and s["rfilename"].endswith(".json")]
print("files", len(files), flush=True)
def one(f):
    for _ in range(3):
        try:
            j = json.loads(urllib.request.urlopen(H + f, timeout=300).read())
            ids = [str(x) for x in j["id"]]; res = j["results"]; sub = j["subset"]
            return f, {"model": j["model"], "model_type": j.get("model_type"), "ids": ids, "results": res, "subset": sub}
        except Exception as e:
            err = e
    print("fail", f, err, flush=True); return f, None
rows = {}
with cf.ThreadPoolExecutor(6) as ex:
    for n, (f, r) in enumerate(ex.map(one, files), 1):
        if r: rows[r["model"]] = r
        if n % 20 == 0: print(n, flush=True)
# 공통 항목 집합 (Ties 제외)
first = next(iter(rows.values()))
ids = [i for i, s in zip(first["ids"], first["subset"]) if s != "Ties"]
subset = {i: s for i, s in zip(first["ids"], first["subset"])}
models = sorted(rows)
mat = {"source": "RewardBench 2 results (allenai/reward-bench-2-results eval-set-scores), results==1.0 is correct; Ties subset excluded",
       "models": models, "model_type": {m: rows[m]["model_type"] for m in models}, "items": ids, "subset": {i: subset[i] for i in ids},
       "correct": []}
for m in models:
    pos = {i: k for k, i in enumerate(rows[m]["ids"])}
    mat["correct"].append([1 if (i in pos and rows[m]["results"][pos[i]] == 1.0) else 0 for i in ids])
(out / "rb2.matrix.json").write_text(json.dumps(mat))
gen = [m for m in models if "Generative" in str(rows[m]["model_type"])]
print("models", len(models), "generative", len(gen), gen[:40]); print("items", len(ids)); print("RB2_DONE")
