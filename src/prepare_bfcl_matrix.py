"""BFCL-Result(2025-12-16) 의 모델별 score 파일에서 항목별 정오 행렬을 만든다. score 파일은 틀린 항목만 나열하므로 전체 id 집합(원본 데이터)에서 빼서 정오를 만든다."""
import json, urllib.request, concurrent.futures as cf, sys
from pathlib import Path
DATE = "2025-12-16"; RAW = f"https://raw.githubusercontent.com/HuanzhiMao/BFCL-Result/main/{DATE}"
H = "https://huggingface.co/datasets/gorilla-llm/Berkeley-Function-Calling-Leaderboard/resolve/main/"
CATS = {"irrelevance": ("non_live", "BFCL_v3_irrelevance.json"), "live_irrelevance": ("live", "BFCL_v3_live_irrelevance.json"),
        "live_relevance": ("live", "BFCL_v3_live_relevance.json"), "multiple": ("non_live", "BFCL_v3_multiple.json"), "live_multiple": ("live", "BFCL_v3_live_multiple.json"), "simple_python": ("non_live", "BFCL_v3_simple.json"), "live_simple": ("live", "BFCL_v3_live_simple.json")}
ANSWERS = {"multiple": "BFCL_v3_multiple.json", "live_multiple": "BFCL_v3_live_multiple.json", "simple_python": "BFCL_v3_simple.json", "live_simple": "BFCL_v3_live_simple.json"}
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
def get(u):
    for _ in range(3):
        try: return urllib.request.urlopen(u, timeout=90).read().decode()
        except Exception as e: err = e
    return None
models = [x["name"] for x in json.loads(get(f"https://api.github.com/repos/HuanzhiMao/BFCL-Result/contents/{DATE}/score"))]
print("models", len(models))
items = {}
for cat, (grp, fn) in CATS.items():
    t = get(H + fn); rows = [json.loads(l) for l in t.splitlines() if l.strip()]
    if cat in ANSWERS:
        ans = {a["id"]: a for a in (json.loads(l) for l in get(H + "possible_answer/" + ANSWERS[cat]).splitlines() if l.strip())}
        for r in rows:
            r["possible_answer"] = ans.get(r["id"], {}).get("ground_truth")
    items[cat] = rows; print(cat, len(rows))
def one(args):
    m, cat, grp = args
    t = get(f"{RAW}/score/{m}/{grp}/BFCL_v4_{cat}_score.json")
    if t is None: return m, cat, None
    ls = [json.loads(l) for l in t.splitlines() if l.strip()]
    head = ls[0]; wrong = {x["id"] for x in ls[1:] if "id" in x}
    return m, cat, (head, wrong)
jobs = [(m, cat, grp) for m in models for cat, (grp, _) in CATS.items()]
res = {}
with cf.ThreadPoolExecutor(12) as ex:
    for m, cat, r in ex.map(one, jobs):
        if r: res.setdefault(cat, {})[m] = r
for cat, rows in items.items():
    ids = [r["id"] for r in rows]
    ms = sorted(res.get(cat, {}))
    mat = {"source": f"BFCL-Result {DATE} {cat}", "models": ms, "items": ids,
           "correct": [[0 if i in res[cat][m][1] else 1 for i in ids] for m in ms],
           "reported_accuracy": {m: res[cat][m][0].get("accuracy") for m in ms}}
    # 일관성 검사: 보고 정확도와 재구성 정확도 비교
    bad = [m for m in ms if abs(sum(mat["correct"][ms.index(m)]) / len(ids) - (mat["reported_accuracy"][m] or 0)) > 0.02]
    (out / f"bfcl_{cat}.matrix.json").write_text(json.dumps(mat))
    (out / f"bfcl_{cat}.items.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    print(f"{cat}: items {len(ids)} models {len(ms)} mismatch>2pp {len(bad)} {bad[:3]}")
print("BFCL_DONE")
