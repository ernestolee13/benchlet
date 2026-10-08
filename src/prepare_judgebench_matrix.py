"""JudgeBench HF 공간의 심판 출력(outputs/*.jsonl, 심판마다 쌍 620개 × 판정 2회)에서 심판별 항목별 정오 행렬을 만든다.
정오 규칙: 두 판정(원순서, 뒤집은 순서) 모두 라벨과 일치해야 정답(논문의 position-consistent accuracy).
논문 수치(o3-mini-high 80.86, GPT-4o 56.57 on GPT-4o split)와 맞는 해석을 고른다."""
import json, urllib.request, concurrent.futures as cf, sys, re, collections
from pathlib import Path
out = Path(sys.argv[1]); out.mkdir(parents=True, exist_ok=True)
SP = "https://huggingface.co/spaces/ScalerLab/JudgeBench/resolve/main/"
d = json.loads(urllib.request.urlopen("https://huggingface.co/api/spaces/ScalerLab/JudgeBench", timeout=60).read())
files = [s["rfilename"] for s in d["siblings"] if s["rfilename"].startswith("outputs/")]
print("judge files", len(files), flush=True)
dec = json.JSONDecoder()
def parse(t):
    i, objs = 0, []
    while i < len(t):
        while i < len(t) and t[i].isspace(): i += 1
        if i >= len(t): break
        o, i = dec.raw_decode(t, i); objs.append(o)
    return objs
def flip(lab): return {"A>B": "B>A", "B>A": "A>B"}.get(lab, lab)
def one(f):
    try: t = urllib.request.urlopen(SP + f, timeout=300).read().decode()
    except Exception as e: print("fail", f, e, flush=True); return f, None
    m = re.search(r"response_model=([^,]+),judge_name=([^,]+),judge_model=(.+)\.jsonl$", f)
    resp_model, judge_name, judge_model = m.groups()
    rows = {}
    for o in parse(t):
        js = o.get("judgments") or []
        d1 = (js[0] or {}).get("decision") if len(js) > 0 else None
        d2 = (js[1] or {}).get("decision") if len(js) > 1 else None
        rows[o["pair_id"]] = {"label": o["label"], "d1": d1, "d2": d2}
    return f, {"resp_model": resp_model, "judge": f"{judge_name}:{judge_model}", "rows": rows}
res = []
with cf.ThreadPoolExecutor(8) as ex:
    for f, r in ex.map(one, files):
        if r: res.append(r)
# 항목 = 두 split 의 pair_id 합집합. 심판 = judge 이름(응답 모델 split 둘을 합쳐 한 심판으로)
judges = collections.defaultdict(dict)
for r in res:
    judges[r["judge"]].update(r["rows"])
ids = sorted({pid for r in res for pid in r["rows"]})
def correct(row, rule):
    lab, d1, d2 = row["label"], row["d1"], row["d2"]
    if rule == "both_same": return int(d1 == lab and d2 == lab)
    if rule == "both_flip": return int(d1 == lab and d2 == flip(lab))
    return int(d1 == lab)
# 해석 선택: GPT-4o split 에서 o3-mini-high 가 80.86 에 가까운 규칙
gpt_ids = sorted({pid for r in res if r["resp_model"].startswith("gpt-4o") for pid in r["rows"]})
for rule in ["both_same", "both_flip", "first_only"]:
    accs = {}
    for j, rows in judges.items():
        if "o3-mini-2025-01-31_high" in j or "gpt-4o-2024-05-13" in j and "arena_hard" in j:
            sel = [rows[i] for i in gpt_ids if i in rows]
            accs[j] = sum(correct(x, rule) for x in sel) / len(sel) if sel else None
    print(rule, {k: round(v * 100, 2) for k, v in accs.items() if v is not None})
rule = sys.argv[2] if len(sys.argv) > 2 else "both_flip"
# 심판 대부분이 GPT-4o split(350쌍)만 돌렸으므로 항목은 그 split 로, 심판은 그 항목의 90% 이상을 판정한 것으로 한다
ids = gpt_ids
models = sorted(j for j in judges if sum(1 for i in ids if i in judges[j]) >= 0.9 * len(ids))
mat = {"source": f"JudgeBench judge outputs (HF space ScalerLab/JudgeBench outputs/), rule={rule}", "models": models, "items": ids,
       "correct": [[correct(judges[j][i], rule) if i in judges[j] else 0 for i in ids] for j in models],
       "coverage": {j: len(judges[j]) for j in models}}
(out / "judgebench.matrix.json").write_text(json.dumps(mat))
print("items", len(ids), "judges(full coverage)", len(models), [m for m in models]); print("JB_DONE")
