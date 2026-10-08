"""MCP 서버: bench_* 툴 18개. 전부 bench-core 를 감싼다. 모델 호출은 서버가 직접 한다(sampling 없음).

    benchlet mcp            # stdio 로 기동. .mcp.json 이 이걸 부른다
루트는 --root 또는 BENCHLET_ROOT, 없으면 cwd 에서 tasks/ 나 .git 을 찾아 올라간다.
레지스트리(로컬)는 <root>/registry/benches/<owner>/<slug>/ 이고 정적 사이트가 이걸 읽는다.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import threading
import uuid
from pathlib import Path

import yaml

from .. import NAME, __version__
from ..config import find_repo_root, load_banned_terms
from ..review import run_checks, render_markdown
from ..review.results import load_results, find_results
from ..runner.arms import ARMS, verified_table
from ..schema import load_bench, validate_bench, expand_minimal
from ..schema.pii import scan_items
from ..stats.report import build_report, render_report
from .protocol import Server, ToolError

OWNER = os.environ.get("BENCHLET_OWNER", "ernestolee13")
RUNS: dict = {}          # run_id → {status, bench, arms, progress, result_path, error}


def _root() -> Path:
    return Path(os.environ["BENCHLET_ROOT"]).resolve() if os.environ.get("BENCHLET_ROOT") else find_repo_root()


def _bench(bench_id: str):
    try:
        return load_bench(bench_id, _root())
    except FileNotFoundError as e:
        raise ToolError(str(e)) from e


def _obj(schema_props: dict, required: list | None = None) -> dict:
    return {"type": "object", "properties": schema_props, "required": required or []}


S = {"str": {"type": "string"}, "int": {"type": "integer"}, "bool": {"type": "boolean"},
     "strs": {"type": "array", "items": {"type": "string"}}}

server = Server(NAME, __version__)


# ── 모델·생성 ─────────────────────────────────────────────────────────────────
@server.tool("bench_models", "검증된 OpenRouter 조합표·가격·호출 템플릿과 프리셋 팔. 매달 바뀌므로 verified_at 을 본다", _obj({}))
def bench_models():
    t = verified_table()
    return {"verified_at": t.get("verified_at"), "critical": t.get("critical"), "call_template": t.get("call_template"),
            "presets": {k: {kk: v[kk] for kk in ("model", "provider", "in_per_m", "family", "mode")} for k, v in ARMS.items()},
            "verified_working": t.get("verified_working"), "blocked": t.get("blocked"),
            "custom": "custom:<model> 팔은 BENCHLET_BASE_URL · BENCHLET_API_KEY · (선택) BENCHLET_EXTRA_BODY 환경변수만 받는다. 요건은 references/run-guide.md"}


@server.tool("bench_create", "최소 형식 벤치를 만든다(benches/<name>/bench.yaml + 빈 items.jsonl). bench_id 는 그 폴더 경로",
             _obj({"name": S["str"], "question": {"type": "string", "description": "공통 가이드. 한 문장 질문 + 정의 + 예외 + 범위 + 입력 설명"},
                   "choices": S["strs"], "type": {"type": "string", "enum": ["binary", "multiclass", "route"]},
                   "domain": S["strs"], "source_desc": S["str"], "language": S["str"],
                   "goal": {"type": "string", "enum": ["compliance", "classify", "route", "derive", "gate", "fit", "rank"]},
                   "unit": {"type": "string", "enum": ["sentence", "post", "record", "query", "pair"]},
                   "taxonomy_domain": {"type": "array", "items": {"type": "string"}, "description": "bench_taxonomy 의 domain 키"},
                   "keywords": {"type": "array", "items": {"type": "string"}, "description": "bench_taxonomy 의 키워드 정규형 2~5개"},
                   "input_kind": S["str"], "source_kind": {"type": "string", "enum": ["own-data", "public-distilled", "synthetic-rules"]}}, ["name", "question", "choices"]))
def bench_create(name, question, choices, type=None, domain=None, source_desc=None, language="ko", goal=None, unit=None,
                 taxonomy_domain=None, keywords=None, input_kind=None, source_kind=None):
    if not re.match(r"^[a-z0-9][a-z0-9-]{1,60}$", name):
        raise ToolError("name 은 소문자·숫자·하이픈만")
    d = _root() / "benches" / name
    if d.exists():
        raise ToolError(f"이미 있다: {d}")
    d.mkdir(parents=True)
    typ = type or ("binary" if len(choices) == 2 else "multiclass")
    spec = {"name": name, "version": 1, "guide": question, "choices": list(choices), "type": typ,
            "task_signature": {"goal": goal or "", "answer": "binary" if typ == "binary" else f"choice({len(choices)})", "prob_use": "accuracy_only",
                               "label": "judged", "unit": unit or "", "language": language},
            "domain": domain or [], "source": source_desc or "", "visibility": "sample", "license": "CC-BY-4.0",
            "taxonomy": {"domain": taxonomy_domain or [], "input_kind": input_kind or "", "source_kind": source_kind or "own-data", "language": language},
            "keywords": keywords or [],
            "items": "items.jsonl", "review": {"checks_run": 0, "human_reviewed_fraction": 0.0, "flagged": 0, "decided": 0}}
    from ..taxonomy import load as _tload, check_labels, normalize_keywords
    tax = _tload(_root())
    spec["keywords"] = normalize_keywords(tax, spec["keywords"])
    warns = check_labels(tax, dict(spec["taxonomy"], keywords=spec["keywords"])) if tax else []
    (d / "bench.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (d / "items.jsonl").write_text("", encoding="utf-8")
    return {"bench_id": str(d.relative_to(_root())), "path": str(d), "taxonomy_warnings": warns,
            "note": "bench_add_items 로 항목을 넣는다. 핸들은 경로라 세션이 끝나도 유효하다. 분류 경고가 있으면 bench_taxonomy 어휘로 맞춘다"}


@server.tool("bench_add_items", "항목을 넣는다. 스키마 오류·중복 해시·극성 경고·개인정보 스캔 히트가 있으면 넣지 않고 isError",
             _obj({"bench_id": S["str"], "items": {"type": "array", "items": {"type": "object"},
                                                   "description": "최소 형식 항목 [{input, target, evidence, class, label_source?, cluster?, difficulty?}]"}},
                  ["bench_id", "items"]))
def bench_add_items(bench_id, items):
    root = _root()
    d = root / bench_id
    if not (d / "bench.yaml").exists():
        raise ToolError("bench_create 로 만든 벤치 폴더여야 한다")
    spec = yaml.safe_load((d / "bench.yaml").read_text(encoding="utf-8"))
    existing = [json.loads(l) for l in (d / "items.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for i, it in enumerate(items):
        for k in ("input", "target"):
            if k not in it:
                raise ToolError(f"항목 {i}: {k} 없음")
    merged = existing + list(items)
    b = load_bench(str(d), root)
    b.items = expand_minimal(spec, merged, spec["name"])
    r = validate_bench(b, sha_file=None)
    new_ids = {it["id"] for it in b.items[len(existing):]}
    errs = [e for e in r.errors]
    pii = [h for h in r.pii_hits if h["item_id"] in new_ids]
    if errs or pii:
        raise ToolError("넣지 않았다.\n" + "\n".join(errs) + "\n" + "\n".join(f"개인정보 {h['item_id']} {h['field']} {h['kind']} {h['match']}" for h in pii))
    with (d / "items.jsonl").open("a", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    return {"added": len(items), "total": len(merged), "warnings": r.warnings,
            "polarity": [w for w in r.warnings if "극성" in w]}


# ── 검증·검수 ─────────────────────────────────────────────────────────────────
@server.tool("bench_validate", "형식 검증. 어떻게 만들었든 게시 전 통과해야 한다. CLI·웹과 같은 검사기",
             _obj({"bench_id": S["str"]}, ["bench_id"]))
def bench_validate(bench_id):
    root = _root()
    b = _bench(bench_id)
    r = validate_bench(b, sha_file=root / "labels" / "SHA256SUMS")
    return {"ok": r.ok, "format": b.format, "n": len(b.items), "sha256": b.items_sha256,
            "errors": r.errors, "warnings": r.warnings, "pii_hits": r.pii_hits, "info": r.info}


@server.tool("bench_review", "검수 검사 v0(1·2·5·7·8·9·10·11)를 돌려 플래그 큐를 만든다. 1·2 는 결과 파일이 있어야 한다. 동기(모델 호출 없음)",
             _obj({"bench_id": S["str"], "checks": {"type": "array", "items": {"type": "integer"}},
                   "results": {"type": "string", "description": "결과 파일 경로. 없으면 results/<bench>-run.json 을 찾는다"},
                   "rules": {"type": "object", "description": "검사 8 매처 {선택지: [정규식]}"}}, ["bench_id"]))
def bench_review(bench_id, checks=None, results=None, rules=None):
    root = _root()
    b = _bench(bench_id)
    p = find_results(b.name, root, results)
    res = load_results(p, b.items) if p else None
    rep = run_checks(b, res, checks, rules=rules)
    out = root / "results" / "review" / f"{b.name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_markdown(rep), encoding="utf-8")
    out.with_suffix(".json").write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {}
    for f in rep.flags:
        counts[f.strength] = counts.get(f.strength, 0) + 1
    _bump_manifest_review(root, b, checks_run=len(rep.checks_run), flagged=len(rep.flags))
    return {"run_id": str(out.relative_to(root)), "checks_run": rep.checks_run, "skipped": rep.skipped,
            "flags": counts, "queue": str(out.relative_to(root)), "results_used": str(p.relative_to(root)) if p else None}


@server.tool("bench_review_queue", "플래그 큐(강도순). 사람이 볼 목록", _obj({"bench_id": S["str"], "limit": S["int"]}, ["bench_id"]))
def bench_review_queue(bench_id, limit=50):
    root = _root()
    b = _bench(bench_id)
    p = root / "results" / "review" / f"{b.name}.json"
    if not p.exists():
        raise ToolError("bench_review 를 먼저 돌려라")
    d = json.loads(p.read_text(encoding="utf-8"))
    decided = _decisions(root, b)
    flags = [dict(f, decided=decided.get(f.get("item_id"))) for f in d["flags"]][:limit]
    return {"bench": b.name, "n_flags": len(d["flags"]), "flags": flags, "sections": list(d.get("sections", {}).keys())}


@server.tool("bench_review_decide", "플래그 항목에 사람 결정을 남긴다(keep/fix/drop). 결정은 <bench>.decisions.jsonl 과 매니페스트에 남는다",
             _obj({"bench_id": S["str"], "item_id": S["str"], "decision": {"type": "string", "enum": ["keep", "fix", "drop"]},
                   "note": S["str"]}, ["bench_id", "item_id", "decision"]))
def bench_review_decide(bench_id, item_id, decision, note=""):
    root = _root()
    b = _bench(bench_id)
    p = _decisions_path(root, b)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"item_id": item_id, "decision": decision, "note": note, "by": "human",
                            "at": dt.datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False) + "\n")
    n = len(_decisions(root, b))
    _bump_manifest_review(root, b, decided=n)
    return {"decided": n, "file": str(p.relative_to(root))}


def _decisions_path(root, b):
    return b.path.parent / (b.path.stem + ".decisions.jsonl") if b.format != "minimal" else b.path.parent / "decisions.jsonl"


def _decisions(root, b) -> dict:
    p = _decisions_path(root, b)
    out = {}
    if p.exists():
        for l in p.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l)
                out[d["item_id"]] = d["decision"]
    return out


def _manifest_path(b):
    return b.path if b.format == "minimal" else b.path.with_name(b.path.stem + ".manifest.yaml")


def _bump_manifest_review(root, b, **kv):
    p = _manifest_path(b)
    if not p.exists():
        return
    m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    rev = m.setdefault("review", {})
    rev.update(kv)
    p.write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")


# ── 계획 ──────────────────────────────────────────────────────────────────────
@server.tool("bench_plan", "발견 후보와 시간 예산으로 권장 벤치·등급·라벨 경로·n·검수 시간·비용 표를 낸다(references/plan.md 규칙)",
             _obj({"candidates": {"type": "array", "items": {"type": "object"},
                                  "description": "[{name, signature:{goal,answer,prob_use,label,unit}, grade: core|aux|later, label_path: 1|2|3, n_available, n_classes, prerequisites?}]"},
                   "budget_min": S["int"], "n": S["int"], "class_min": S["int"], "arms": S["int"]}, ["candidates"]))
def bench_plan(candidates, budget_min=60, n=None, class_min=8, arms=2):
    rows = []
    for c in candidates:
        sig = c.get("signature") or {}
        lp = int(c.get("label_path", 2))
        default_n = 80 if lp == 1 else 48
        want = int(n or c.get("n") or default_n)
        if sig.get("prob_use") == "threshold":
            want = max(want, 60)
        if sig.get("prob_use") == "calibrated":
            want = max(want, 100)
        want = max(want, class_min * int(c.get("n_classes") or 1))
        avail = c.get("n_available")
        capped = min(want, int(avail)) if avail else want
        read_frac = 0.2 if lp == 1 else 1.0
        minutes = round(capped * read_frac * 20 / 60, 1)
        cost = round(capped * arms * 0.00003, 4)
        grade = c.get("grade", "aux")
        recommended = grade == "core" or (grade == "aux" and lp in (1, 2))
        rows.append({"name": c.get("name"), "signature": sig, "grade": grade, "label_path": lp, "n": capped,
                     "n_wanted": want, "n_available": avail, "classes": c.get("n_classes"), "review_min": minutes,
                     "cost_usd": cost, "prerequisites": c.get("prerequisites") or [], "recommended": recommended})
    seen = {}
    for r in rows:
        key = (r["signature"].get("goal"), r["signature"].get("answer"), r["signature"].get("unit"))
        if key in seen and r["recommended"]:
            r["recommended"] = False
            r["merge_into"] = seen[key]
        elif r["recommended"]:
            seen[key] = r["name"]
    total = sum(r["review_min"] for r in rows if r["recommended"])
    dropped = []
    for r in sorted([r for r in rows if r["recommended"]], key=lambda r: {"later": 0, "aux": 1, "core": 2}[r["grade"]]):
        if total <= budget_min:
            break
        r["recommended"] = False; r["dropped_for_budget"] = True; dropped.append(r["name"]); total -= r["review_min"]
    return {"rows": rows, "total_review_min": round(total, 1), "budget_min": budget_min, "dropped_for_budget": dropped,
            "note": "게시하려면 레지스트리 형식(references/format.md)을 그대로 따라야 한다. 선택은 plan.yaml 로 잠근다"}


# ── 동결·실행 ─────────────────────────────────────────────────────────────────
@server.tool("bench_freeze", "항목 해시를 labels/SHA256SUMS 에 동결하고 사전등록 템플릿을 돌려준다", _obj({"bench_id": S["str"]}, ["bench_id"]))
def bench_freeze(bench_id):
    root = _root()
    b = _bench(bench_id)
    p = root / "labels" / "SHA256SUMS"
    p.parent.mkdir(exist_ok=True)
    rel = str(b.path.relative_to(root)) if b.format != "minimal" else str((b.path.parent / "items.jsonl").relative_to(root))
    line = f"{b.items_sha256}  {rel}"
    lines = p.read_text().splitlines() if p.exists() else []
    if not any(l.endswith("  " + rel) for l in lines):
        p.write_text("\n".join(lines + [line]) + "\n")
    tmpl = ("# 사전등록\n\n동결 " + dt.date.today().isoformat() + f"\n\n```\n{line}\n```\n\n## 사전 예측\n\n| # | 예측 | 틀렸다면 |\n|---|---|---|\n| 1 |  |  |\n\n"
            "## 판정 규칙\n\n이진 0.5, 다지 argmax. 임계·온도 보정 없음.\n")
    return {"sha256": b.items_sha256, "frozen_line": line, "preregister_template": tmpl}


@server.tool("bench_run", "스모크 뒤 전량 실행을 백그라운드로 시작한다. run_id 를 돌려주고 bench_status 로 폴링한다",
             _obj({"bench_id": S["str"], "arms": S["strs"], "limit": S["int"], "skip_smoke": S["bool"]}, ["bench_id"]))
def bench_run(bench_id, arms=None, limit=0, skip_smoke=False):
    from ..runner.run import run_bench, RunConfig
    from ..runner.smoke import smoke_bench
    from ..config import read_env_key
    root = _root()
    b = _bench(bench_id)
    arms = arms or ["qwen", "jev"]
    if not read_env_key("OPENROUTER_API_KEY") and not any(a.startswith("custom:") for a in arms):
        raise ToolError("OPENROUTER_API_KEY 가 없다. 실행은 선택이다. 게시만 하고 기준 팔 결과를 받아라(경로 0)")
    run_id = "run-" + uuid.uuid4().hex[:8]
    out = root / "results" / f"{b.name}-run.json"
    st = RUNS[run_id] = {"status": "smoke", "bench": b.name, "arms": arms, "started": dt.datetime.now().isoformat(timespec="seconds"),
                         "result_path": str(out.relative_to(root)), "smoke": None, "excluded": [], "error": None}

    def work():
        try:
            modes, smoke = {}, None
            use = list(arms)
            if not skip_smoke:
                smoke = smoke_bench(b, use, progress=False)
                st["smoke"] = smoke
                bad = [k for k, v in smoke.items() if not v["usable"]]
                modes = {k: v["mode"] for k, v in smoke.items()}
                use = [k for k in use if k not in bad]
                st["excluded"] = bad
                if not use:
                    st["status"] = "unusable"; st["error"] = "쓸 수 있는 조합이 없다. 게시만 해라(경로 0)"; return
            st["status"] = "running"
            res = run_bench(b, RunConfig(arms=use, limit=limit, out=out, progress=False, smoke=smoke, arm_modes=modes))
            st["agg"] = res["agg"]; st["status"] = "done"
        except BaseException as e:                       # noqa: BLE001
            st["status"] = "error"; st["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run_id, "status": "smoke", "note": "bench_status(run_id) 로 폴링. 스모크에 걸린 조합은 자동으로 뺀다"}


@server.tool("bench_status", "실행 진행·비용", _obj({"run_id": S["str"]}, ["run_id"]))
def bench_status(run_id):
    st = RUNS.get(run_id)
    if not st:
        raise ToolError("모르는 run_id (서버가 재시작됐으면 results/<bench>-run.json 을 직접 본다)")
    return st


@server.tool("bench_results", "결과 보기: summary | per_class | pairwise | disagreements",
             _obj({"bench_id": S["str"], "view": {"type": "string", "enum": ["summary", "per_class", "pairwise", "disagreements", "markdown"]},
                   "results": S["str"]}, ["bench_id"]))
def bench_results(bench_id, view="summary", results=None):
    root = _root()
    b = _bench(bench_id)
    p = find_results(b.name, root, results)
    if not p:
        return {"results": "pending", "note": "결과가 없다. 실행은 선택이다"}
    res = load_results(p, b.items)
    rep = build_report(b, res)
    if view == "markdown":
        return render_report(rep)
    if view == "summary":
        return {"n": rep["n"], "min_gap_pp": rep["min_gap_pp"], "summary": rep["summary"], "surface": rep.get("surface", {}).get("best") if rep.get("surface") else None}
    if view == "per_class":
        return {"per_class": rep["per_class"]}
    if view == "pairwise":
        return {"pairwise": rep["pairwise"]}
    by_id = {it["id"]: it for it in b.items}
    rows = []
    for iid, d in res.by_item.items():
        hits = {a: v["hit"] for a, v in d.items() if v["hit"] is not None}
        if len(set(hits.values())) > 1:
            it = by_id[iid]
            rows.append({"id": iid, "class": it.get("class"), "target": it["choices"][it["target"]], "hits": hits,
                         "input": it["input"][:200]})
    return {"disagreements": rows, "n": len(rows)}


# ── 내보내기·게시·레지스트리 ──────────────────────────────────────────────────
@server.tool("bench_export", "inspect | lm-eval | hf", _obj({"bench_id": S["str"], "format": {"type": "string", "enum": ["inspect", "lm-eval", "hf"]}}, ["bench_id"]))
def bench_export(bench_id, format="inspect"):
    from ..export import to_inspect_jsonl, to_lm_eval_yaml, to_hf_eval_yaml
    root = _root()
    b = _bench(bench_id)
    out = root / "export" / b.name
    if format == "inspect":
        p = to_inspect_jsonl(b, out / f"{b.name}.inspect.jsonl")
    elif format == "lm-eval":
        p = to_lm_eval_yaml(b, out)
    else:
        rp = find_results(b.name, root)
        p = to_hf_eval_yaml(b, out / "eval.yaml", json.loads(rp.read_text(encoding="utf-8")) if rp else None)
    return {"path": str(p.relative_to(root))}


def _experiment_block(raw: dict) -> dict:
    """결과 파일에서 「어떻게 실험했나」를 뽑는다. 구식 러너 결과는 팔 메타가 없어 프리셋으로 채우고 그 사실을 적는다."""
    tmpl = verified_table().get("call_template") or {}
    arms = raw.get("arms")
    legacy = arms is None
    if legacy:
        arms = {}
        for k in raw.get("agg", {}):
            a = ARMS.get(k, {"model": k, "provider": None, "family": None, "mode": "logprob", "in_per_m": None})
            arms[k] = {"model": a["model"], "provider": a.get("provider"), "family": a.get("family"), "mode": a.get("mode"),
                       "prob_source": "typed" if a.get("mode") == "typed" else "logprob", "base_url": "openrouter.ai",
                       "in_per_m": a.get("in_per_m"), "smoke": None}
    return {
        "date": raw.get("date") or "2026-09-30", "template": raw.get("template") or "legacy-seed",
        "runner": "benchlet" if not legacy else "src/run.py (구식 러너, 팔 메타는 프리셋에서 채움)",
        "arms": arms,
        "protocol": {"decision_rule": "이진 0.5, 다지 argmax. 임계·온도 보정 없음",
                     "logprob_call": {k: tmpl.get(k) for k in ("max_tokens", "temperature", "logprobs", "top_logprobs", "reasoning")},
                     "provider_pin": "provider.only=[pin], allow_fallbacks=false, require_parameters=true",
                     "binary": "극성 반전 2회 호출 평균: p = ½[P(A|choices[0]=A) + P(B|choices[0]=B)]",
                     "multiclass": "항목별 결정론적 셔플 뒤 원 인덱스로 복원(generic) 또는 파일에 든 셔플 그대로(legacy-seed)",
                     "typed": "Jev noul(이진)/choice(다지), 질문을 instructions 로 그대로 전달",
                     "label_mass": "상위 8토큰 중 라벨 토큰 질량 < 0.5 이면 오류로 두고 세지 않음",
                     "renormalize": "라벨 토큰 확률을 라벨 집합 안에서 재정규화"},
        "items_sha256": raw.get("items_sha256"),
    }


def registry_dir(root: Path) -> Path:
    return root / "registry" / "benches"


def publish_bundle(root: Path, b, visibility: str = "sample", owner: str = OWNER) -> dict:
    r = validate_bench(b, sha_file=root / "labels" / "SHA256SUMS")
    if not r.ok:
        raise ToolError("게시 거부: validate 실패\n" + "\n".join(r.summary_lines()))
    out = registry_dir(root) / owner / b.name
    out.mkdir(parents=True, exist_ok=True)
    man = dict(b.manifest)
    man.update({"name": b.name, "owner": owner, "version": man.get("version", 1), "items_sha256": b.items_sha256,
                "n": len(b.items), "choices": b.choices or sorted({str(c) for it in b.items for c in it["choices"]}),
                "choices_note": None if b.choices else "항목마다 선택지 순서가 다르다(파일에 든 셔플). 여기는 이름 집합",
                "question": b.question or b.manifest.get("question"), "visibility": visibility,      # 항목마다 질문이 다르면 매니페스트 요약 질문
                "published_at": dt.date.today().isoformat(), "type": b.type})
    sig = man.setdefault("task_signature", {})
    sig.setdefault("answer", "binary" if b.type == "binary" else f"choice({len(b.choices or [])})")
    sig.setdefault("language", "ko")
    classes = sorted({str(it.get("class")) for it in b.items if it.get("class")})
    man["classes"] = classes
    man["label_source_mix"] = {k: sum(1 for it in b.items if it.get("label_source") == k) for k in ("machine", "constructed", "judged", "outcome")}
    rp = find_results(b.name, root)
    if rp:
        (out / "results").mkdir(exist_ok=True)
        raw = json.loads(rp.read_text(encoding="utf-8"))
        man["experiment"] = _experiment_block(raw)
        by_id = {it["id"]: it for it in b.items}          # 구식 결과에 없는 class·label_source 를 항목에서 채운다
        for rec in raw.get("items", []):
            it = by_id.get(rec.get("id"))
            if it:
                rec.setdefault("class", it.get("class")); rec.setdefault("label_source", it.get("label_source"))
                rec.setdefault("target", it["target"]); rec.setdefault("n_options", len(it["choices"]))
        (out / "results" / rp.name).write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        man["results"] = [f"results/{rp.name}"]
        rep = build_report(b, load_results(rp, b.items))
        man["result_summary"] = {a: {"acc": s["acc"], "ci95": s["ci95"], "auroc": s["auroc"], "brier": s["brier"], "n": s["ok"],
                                     "prob_source": (raw.get("arms") or {}).get(a, {}).get("prob_source", "typed" if a == "jev" else "logprob"),
                                     "model": (raw.get("arms") or {}).get(a, {}).get("model", ARMS.get(a, {}).get("model", a)),
                                     "source_badge": "author-run"} for a, s in rep["summary"].items()}
    else:
        man["results"] = "pending"
    revq = root / "results" / "review" / f"{b.name}.json"
    if revq.exists():
        d = json.loads(revq.read_text(encoding="utf-8"))
        man.setdefault("review", {}).update({"checks_run": len(d.get("checks_run", [])), "flagged": len(d.get("flags", []))})
    sample = b.items if visibility == "full" else b.items[:5]
    hits = scan_items(sample, load_banned_terms())
    if hits:
        raise ToolError(f"게시 거부: 표본에 개인정보 히트 {len(hits)}")
    with (out / "samples.jsonl").open("w", encoding="utf-8") as f:
        for it in sample:
            f.write(json.dumps({k: v for k, v in it.items() if k != "metadata"}, ensure_ascii=False) + "\n")
    (out / "manifest.yaml").write_text(yaml.safe_dump(man, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return {"path": str(out.relative_to(root)), "results": man["results"], "n_samples": len(sample), "visibility": visibility}


@server.tool("bench_publish", "게시 묶음을 쓴다. target=local 은 registry/benches/<owner>/<slug>, target=github 는 gh 로그인 계정의 리포(기본 benchlet-benches)에 커밋·푸시하고 로컬엔 포인터를 남긴다. 결과 없이도 통과(results: pending). 개인정보 히트면 거부",
             _obj({"bench_id": S["str"], "visibility": {"type": "string", "enum": ["generator", "sample", "full"]},
                   "confirm": {"type": "boolean", "description": "사용자 확인을 받았으면 true"},
                   "target": {"type": "string", "enum": ["local", "github"]}, "repo": {"type": "string", "description": "github 대상 리포 이름 또는 owner/name. 기본 benchlet-benches"},
                   "private": S["bool"]}, ["bench_id"]))
def bench_publish(bench_id, visibility="sample", confirm=False, target="local", repo=None, private=False):
    if not confirm:
        raise ToolError("게시는 외부 노출이다. 사용자 확인 뒤 confirm=true 로 다시 부른다")
    root = _root()
    from .. import github as gh
    owner = gh.gh_login() or OWNER
    _ensure_owner_file(root, owner)
    r = publish_bundle(root, _bench(bench_id), visibility, owner)
    if target == "github":
        full = gh.ensure_repo(repo or gh.DEFAULT_REPO, private)
        b = _bench(bench_id)
        ptr = gh.push_bundle(root / r["path"], full, f"benches/{b.name}", f"publish {b.name} v{b.manifest.get('version', 1)} ({b.items_sha256[:12]})")
        (root / r["path"] / "pointer.yaml").write_text(yaml.safe_dump(ptr, allow_unicode=True, sort_keys=False), encoding="utf-8")
        r["github"] = ptr
    return r


def _ensure_owner_file(root: Path, owner: str) -> None:
    """작성자 레지스트리가 없으면 gh 프로필로 만든다. GitHub 계정이 곧 신원이다."""
    from .. import github as gh
    p = root / "registry" / "owners" / f"{owner}.yaml"
    if p.exists():
        return
    prof = gh.gh_profile() or {"login": owner}
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump({"handle": owner, "github": prof.get("html_url") or f"https://github.com/{owner}",
                                 "repo": f"https://github.com/{owner}/{gh.DEFAULT_REPO}", "name": prof.get("name") or owner,
                                 "bio": prof.get("bio") or ""}, allow_unicode=True, sort_keys=False), encoding="utf-8")


GALLERY_URL = "https://benchlet.vibestash.app/data.json"


def _remote_benches(url: str | None = None, cache_hours: float = 24.0, fetch=None) -> list:
    """공개 갤러리의 data.json 을 받아 레지스트리 매니페스트 꼴로 바꾼다. ~/.cache/benchlet/gallery.json 에 하루 캐시. 실패하면 빈 목록."""
    import os, time, urllib.request
    url = url or os.environ.get("BENCHLET_GALLERY_URL") or GALLERY_URL
    cache = Path(os.environ.get("BENCHLET_CACHE_DIR") or (Path.home() / ".cache" / "benchlet")) / "gallery.json"
    data = None
    if cache.exists() and time.time() - cache.stat().st_mtime < cache_hours * 3600:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except Exception:            # noqa: BLE001
            data = None
    if data is None:
        try:
            raw = fetch(url) if fetch else urllib.request.urlopen(url, timeout=20).read().decode("utf-8")
            data = json.loads(raw)
            cache.parent.mkdir(parents=True, exist_ok=True); cache.write_text(raw, encoding="utf-8")
        except Exception:            # noqa: BLE001
            return []
    out = []
    for b in data.get("benches") or []:
        out.append({"name": b.get("name"), "owner": b.get("owner"), "version": b.get("version", 1), "n": b.get("n"), "type": b.get("type"),
                    "question": b.get("question"), "choices": b.get("choices"), "task_signature": b.get("signature") or {},
                    "taxonomy": b.get("taxonomy") or {}, "keywords": b.get("keywords") or [], "domain": b.get("domain") or [],
                    "classes": b.get("classes") or [], "review": b.get("review") or {}, "items_sha256": b.get("items_sha256"),
                    "results": "available" if b.get("result_summary") else "pending", "result_summary": b.get("result_summary") or {},
                    "community": b.get("community") or {}, "source_results": b.get("source_results"), "pointer": b.get("pointer"),
                    "license": b.get("license"), "_path": f"remote:{b.get('owner')}/{b.get('name')}", "_remote": True})
    return out


def _registry_manifests(root: Path, include_remote: bool = True) -> list:
    """로컬 레지스트리 + (기본) 공개 갤러리. 같은 이름은 로컬이 우선."""
    out = []
    for p in sorted(registry_dir(root).glob("*/*/manifest.yaml")):
        m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        m["_path"] = str(p.parent.relative_to(root))
        out.append(m)
    if include_remote and os.environ.get("BENCHLET_OFFLINE") != "1":
        have = {(m.get("owner"), m.get("name")) for m in out}
        out += [m for m in _remote_benches() if (m.get("owner"), m.get("name")) not in have]
    return out


def _materialize_remote(root: Path, bench_id: str) -> Path:
    """remote:<owner>/<name> 을 포인터(리포·커밋·경로)에서 받아 registry/benches/<owner>/<name> 에 둔다."""
    import urllib.request
    owner, name = bench_id[len("remote:"):].split("/", 1)
    m = next((x for x in _remote_benches() if x.get("owner") == owner and x.get("name") == name), None)
    if not m or not m.get("pointer"):
        raise ToolError(f"갤러리에 {bench_id} 가 없거나 포인터가 없다")
    ptr = m["pointer"]
    d = registry_dir(root) / owner / name
    d.mkdir(parents=True, exist_ok=True)
    base = f"https://raw.githubusercontent.com/{ptr['repo']}/{ptr.get('commit') or 'main'}/{ptr['path']}/"
    for fn in ("manifest.yaml", "samples.jsonl"):
        try:
            (d / fn).write_bytes(urllib.request.urlopen(base + fn, timeout=30).read())
        except Exception as e:            # noqa: BLE001
            if fn == "manifest.yaml":
                raise ToolError(f"원격 벤치를 받지 못했다: {base}{fn} ({type(e).__name__})")
    (d / "pointer.yaml").write_text(yaml.safe_dump(ptr, allow_unicode=True), encoding="utf-8")
    return d


def _sig_key(sig: dict) -> tuple:
    return (sig.get("goal"), sig.get("answer"), sig.get("unit"))


@server.tool("bench_recommend", "과제 서명이 같은 게시 벤치들의 결과를 합쳐 팔별 평균 정확도와 근거 수를 낸다",
             _obj({"task_signature": {"type": "object", "description": "{goal, answer, unit} 중 있는 것"}}, ["task_signature"]))
def bench_recommend(task_signature):
    root = _root()
    agg = {}
    n_bench = 0
    for m in _registry_manifests(root):
        sig = m.get("task_signature") or {}
        if any(task_signature.get(k) and task_signature.get(k) != sig.get(k) for k in ("goal", "answer", "unit")):
            continue
        rs = m.get("result_summary")
        if not rs:
            continue
        n_bench += 1
        for arm, s in rs.items():
            if s.get("acc") is None:
                continue
            a = agg.setdefault(arm, {"model": s.get("model"), "accs": [], "prob_source": s.get("prob_source")})
            a["accs"].append(s["acc"])
    rows = [{"arm": k, "model": v["model"], "mean_acc": round(sum(v["accs"]) / len(v["accs"]), 3), "n_benches": len(v["accs"]),
             "prob_source": v["prob_source"]} for k, v in agg.items()]
    rows.sort(key=lambda r: -r["mean_acc"])
    return {"signature": task_signature, "n_benches": n_bench, "arms": rows,
            "note": "근거 수가 3 미만이면 추천이 아니라 참고다. 40~60건 벤치는 15pp 이상 차이만 믿는다"}


def _tokens(s: str) -> set:
    return set(re.findall(r"[가-힣A-Za-z0-9]{2,}", s or ""))


@server.tool("bench_taxonomy", "분류 체계(통제 어휘): goal·domain·input_kind·source_kind·language 와 키워드 정규형·동의어. 올릴 때와 찾을 때 이 어휘를 쓴다", _obj({}))
def bench_taxonomy():
    from ..taxonomy import load as _tload
    return _tload(_root())


@server.tool("bench_search", "갤러리 검색(로컬 레지스트리 + 공개 갤러리 benchlet.vibestash.app, 하루 캐시). 결과의 path 가 remote: 로 시작하면 bench_fork 가 받아 온다. query 는 자유어(동의어 확장), signature 는 {goal, answer, unit, language}, domain 은 분류 영역, keywords 는 정규형 키워드",
             _obj({"query": S["str"], "signature": {"type": "object"}, "domain": S["str"], "keywords": S["strs"], "limit": S["int"]}))
def bench_search(query=None, signature=None, domain=None, keywords=None, limit=10):
    from ..taxonomy import load as _tload, expand_query, normalize_keywords
    root = _root()
    tax = _tload(root)
    q = set()
    for t in expand_query(tax, query or ""):
        q |= _tokens(t)
    want_kw = set(normalize_keywords(tax, keywords or []))
    rows = []
    for m in _registry_manifests(root):
        sig = m.get("task_signature") or {}
        if signature and any(signature.get(k) and signature.get(k) != sig.get(k) for k in signature):
            continue
        tx = m.get("taxonomy") or {}
        if domain and domain not in (tx.get("domain") or []):
            continue
        if want_kw and not (want_kw & set(m.get("keywords") or [])):
            continue
        text = " ".join([m.get("name", ""), m.get("question") or "", " ".join(m.get("domain") or []), " ".join(m.get("classes") or []),
                         " ".join(m.get("keywords") or []), " ".join(tx.get("domain") or [])])
        score = len(q & _tokens(text)) if q else 0
        if q and not score:
            continue
        rows.append({"name": m["name"], "owner": m.get("owner"), "signature": sig, "n": m.get("n"), "question": (m.get("question") or "")[:80],
                     "results": "pending" if m.get("results") == "pending" else "available", "score": score, "path": m["_path"],
                     "review": m.get("review"), "taxonomy": tx, "keywords": m.get("keywords") or []})
    rows.sort(key=lambda r: (-r["score"], r["name"]))
    return {"n": len(rows), "benches": rows[:limit]}


@server.tool("bench_similar", "발견 후보(질문·서명)와 비슷한 게시 벤치. 있으면 「포크 / 새로 만들기」를 사용자에게 보인다",
             _obj({"question": S["str"], "signature": {"type": "object"}}, ["question"]))
def bench_similar(question, signature=None):
    r = bench_search(query=question, signature=None)
    out = []
    for b in r["benches"]:
        same_sig = bool(signature) and all(not signature.get(k) or signature.get(k) == (b["signature"] or {}).get(k) for k in ("goal", "answer", "unit"))
        out.append(dict(b, same_signature=same_sig))
    out.sort(key=lambda b: (-b["same_signature"], -b["score"]))
    return {"similar": out[:5], "choices": ["fork", "new"] if out else ["new"]}


@server.tool("bench_fork", "게시 벤치의 질문·선택지·클래스 표·매니페스트를 내 프로젝트로 가져온다. 원자료 경로는 비운다. 계보를 기록한다",
             _obj({"bench_id": {"type": "string", "description": "registry 경로 (bench_search 의 path)"}, "new_name": S["str"]}, ["bench_id", "new_name"]))
def bench_fork(bench_id, new_name):
    root = _root()
    src = _materialize_remote(root, bench_id) if str(bench_id).startswith("remote:") else root / bench_id
    if not (src / "manifest.yaml").exists():
        raise ToolError("레지스트리 경로가 아니다")
    m = yaml.safe_load((src / "manifest.yaml").read_text(encoding="utf-8"))
    r = bench_create(new_name, m.get("question") or m.get("guide"), m.get("choices"), m.get("type"), m.get("domain"), "")
    d = root / r["bench_id"]
    spec = yaml.safe_load((d / "bench.yaml").read_text(encoding="utf-8"))
    spec["forked_from"] = {"name": m.get("name"), "owner": m.get("owner"), "version": m.get("version"), "items_sha256": m.get("items_sha256")}
    spec["classes_hint"] = m.get("classes") or []
    spec["task_signature"] = m.get("task_signature") or spec.get("task_signature")
    spec["source"] = "(원자료 경로를 여기 적는다. 포크 원본의 원자료는 가져오지 않는다)"
    (d / "bench.yaml").write_text(yaml.safe_dump(spec, allow_unicode=True, sort_keys=False), encoding="utf-8")
    if (src / "samples.jsonl").exists():
        shutil.copy(src / "samples.jsonl", d / "samples-from-fork.jsonl")
    return {"bench_id": r["bench_id"], "forked_from": spec["forked_from"], "classes_hint": spec["classes_hint"],
            "note": "샘플 5건은 samples-from-fork.jsonl 에 참고용으로만 있다. 항목은 내 데이터로 만든다"}


@server.tool("bench_star", "벤치 작성자의 벤치 리포에 스타를 남긴다(gh 로그인 계정). 사용자가 분명히 원할 때만 confirm=true 로 부른다. 스타는 갤러리 신뢰 점수(작성자·벤치 리포 신호)와 유형별 추천 가중에 반영된다",
             _obj({"bench_id": {"type": "string", "description": "bench_search 의 path (registry 경로 또는 remote:owner/name)"}, "confirm": S["bool"]}, ["bench_id"]))
def bench_star(bench_id, confirm=False):
    from .. import github as gh
    root = _root()
    if str(bench_id).startswith("remote:"):
        owner, name = bench_id[len("remote:"):].split("/", 1)
        m = next((x for x in _remote_benches() if x.get("owner") == owner and x.get("name") == name), None)
        ptr = (m or {}).get("pointer") or {}
    else:
        pp = root / bench_id / "pointer.yaml"
        ptr = yaml.safe_load(pp.read_text(encoding="utf-8")) if pp.exists() else {}
        m = yaml.safe_load((root / bench_id / "manifest.yaml").read_text(encoding="utf-8")) if (root / bench_id / "manifest.yaml").exists() else {}
    repo = ptr.get("repo")
    if not repo:
        raise ToolError("이 벤치는 GitHub 포인터가 없어 스타를 남길 곳이 없다")
    me = gh.gh_login()
    if not me:
        raise ToolError("gh 로그인이 없다. `gh auth login` 뒤 다시")
    if repo.split("/")[0].lower() == me.lower():
        return {"repo": repo, "starred": False, "note": "내 리포에는 스타를 남기지 않는다"}
    if not confirm:
        return {"repo": repo, "starred": False, "needs_confirm": True,
                "note": f"작성자 {(m or {}).get('owner')} 의 벤치 리포 {repo} 에 스타를 남길지 사용자에게 묻고, 원하면 confirm=true 로 다시 부른다. 스타는 신뢰 점수와 추천 가중에 반영된다"}
    r = gh.star_repo(repo)
    return dict(r, note="갤러리 신뢰 점수(벤치 리포 스타, 최대 +1.5)와 유형별 추천 가중에 반영된다. 다음 사이트 빌드 때 읽힌다")


@server.tool("bench_registry_sync", "sources.yaml 의 작성자 리포들을 gh 로 받아 registry/benches 로 가져온다(형식·개인정보 검증 통과분만, 포인터 기록). 레지스트리 실행 결과는 보존",
             _obj({"repo": {"type": "string", "description": "특정 리포만 (owner/name)"}}))
def bench_registry_sync(repo=None):
    from .. import registry as R
    rows = R.sync(_root(), only=repo)
    return {"rows": rows, "synced": sum(r["status"] == "synced" for r in rows), "rejected": [r for r in rows if r["status"] == "rejected"]}


@server.tool("bench_run_pending", "결과 없는 게시 벤치에 기준 팔(기본 glm·qwen·deepseek·jev)을 한 번 돌려 결과를 붙인다(source_badge=registry-run). 백그라운드, run_id 로 폴링",
             _obj({"arms": S["strs"], "limit": S["int"], "skip_smoke": S["bool"]}))
def bench_run_pending(arms=None, limit=0, skip_smoke=False):
    from .. import registry as R
    from ..config import read_env_key
    root = _root()
    if not read_env_key("OPENROUTER_API_KEY"):
        raise ToolError("OPENROUTER_API_KEY 가 없다. 레지스트리 실행은 키를 가진 운영자가 한다")
    run_id = "reg-" + uuid.uuid4().hex[:8]
    st = RUNS[run_id] = {"status": "running", "pending": [m["name"] for _, m in R.pending(root)], "done": [], "error": None,
                         "started": dt.datetime.now().isoformat(timespec="seconds")}

    def work():
        try:
            st["done"] = R.run_pending(root, arms, limit, skip_smoke, progress=lambda *_: None)
            st["status"] = "done"
        except BaseException as e:                       # noqa: BLE001
            st["status"] = "error"; st["error"] = f"{type(e).__name__}: {e}"

    threading.Thread(target=work, daemon=True).start()
    return {"run_id": run_id, "pending": st["pending"]}


@server.tool("bench_submit_result", "내 실행 결과를 게시 벤치의 커뮤니티 점수로 제출한다(같은 판본 해시 필수). 제출자 = gh 로그인. 3건 이상·5pp 안이면 검증됨",
             _obj({"bench": S["str"], "results": {"type": "string", "description": "results/<bench>-run.json 경로"}, "github": S["bool"], "confirm": S["bool"]}, ["bench", "results"]))
def bench_submit_result(bench, results, github=False, confirm=False):
    if github and not confirm:
        raise ToolError("리포 푸시는 외부 노출이다. 사용자 확인 뒤 confirm=true")
    from .. import community as CM
    from .. import github as gh
    root = _root()
    run = json.loads((root / results).read_text(encoding="utf-8")) if not Path(results).is_absolute() else json.loads(Path(results).read_text(encoding="utf-8"))
    mps = sorted((root / "registry" / "benches").glob(f"*/{bench}/manifest.yaml"))
    if not mps:
        raise ToolError(f"게시된 벤치가 아니다: {bench}")
    man = yaml.safe_load(mps[-1].read_text(encoding="utf-8"))
    submitter = gh.gh_login() or "anonymous"
    try:
        pack = CM.build_submission(run, man, submitter)
    except ValueError as e:
        raise ToolError(str(e))
    files = [str(CM.write_submission(root, s_, bench, submitter).relative_to(root)) for s_ in pack["submissions"]]
    out = {"submitted": files, "submitter": submitter}
    if github:
        full = gh.ensure_repo(gh.DEFAULT_REPO, False)
        out["github"] = gh.push_bundle(root / "registry" / "community" / bench, full, f"community/{bench}", f"community results for {bench} by {submitter}")
    out["aggregate"] = CM.aggregate(CM.load_submissions(root, bench), owner=man.get("owner"), items_sha256=man.get("items_sha256"))
    return out


def main() -> int:
    server.serve()
    return 0
