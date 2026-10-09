"""실행. 팔마다 같은 항목을 같은 템플릿으로. 이진은 극성 반전 2회 평균, 다지는 결정론적 셔플 후 원 인덱스로 복원.

결과 레코드는 구식 run.py 와 호환된다(items[].arms[arm].p_violation | pred_index, agg). 여기에 arms_meta·smoke 가 붙는다.
"""
from __future__ import annotations

import concurrent.futures as cf
import datetime as dt
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from ..config import read_env_key, OPENROUTER_DECISIONS_URL
from ..schema.load import Bench
from .arms import resolve_arms
from .client import ChatClient, AnthropicClient, LETTERS
from .templates import build, shuffled_order, generic_label


@dataclass
class RunConfig:
    arms: list
    limit: int = 0
    out: Path | None = None
    progress: bool = True
    smoke: dict | None = None
    arm_modes: dict = field(default_factory=dict)     # 스모크가 정한 강등 (key → 'generative')
    concurrency: int = 6                               # 항목 단위 동시 호출 수. 1 이면 순차


def make_client(arm: dict) -> ChatClient:
    key = read_env_key(arm["api_key_env"])
    if not key:
        sys.exit(f"{arm['api_key_env']} 가 없다 (환경변수 또는 ~/.config/benchlet/env). 키가 없으면 실행하지 말고 게시만 해라(경로 0)")
    if not arm.get("base_url"):
        sys.exit("BENCHLET_BASE_URL 이 없다 (custom: 팔)")
    if arm.get("preset") == "anthropic":
        return AnthropicClient(arm["base_url"], key, {})
    return ChatClient(arm["base_url"], key, arm.get("extra_body") or {})


def effective_mode(item: dict, mode: str) -> str:
    """선택지가 글자 수(LETTERS)를 넘으면 typed 를 빼고 전부 라벨 팔이다."""
    if mode != "typed" and len(item["choices"]) > len(LETTERS):
        return "label"
    return mode


def call_arm(client: ChatClient, arm: dict, item: dict, template: str, mode: str) -> dict:
    """항목 하나·팔 하나. 반환 레코드는 구식 결과 형식."""
    binary_t, choice_t, jev_t = build(template)
    n = len(item["choices"])
    mode = effective_mode(item, mode)
    if mode == "label":
        system, user = generic_label(item)
        r = client.label_choice(arm["model"], system, user, item["choices"], arm.get("in_per_m", 0))
        return {"pred_index": r["pred_index"], "probs": None, "ms": r["ms"], "cost": r["cost"], "in_tok": r["in_tok"],
                "err": r["err"], "prob_source": "none", "provider": r.get("provider"), "order": None,
                "raw_text": r.get("raw_text"), "answer_format": r.get("answer_format"), "cache_read": r.get("cache_read")}
    if mode == "typed":
        state, questions, key = jev_t(item)
        r = client.decisions(OPENROUTER_DECISIONS_URL, arm["model"], state, questions, arm.get("in_per_m", 0))
        out = {"ms": r["ms"], "in_tok": r["in_tok"], "cost": r["cost"], "model": r.get("model"), "err": r["err"],
               "raw": r["answers"].get(key)}
        ans = r["answers"].get(key) or {}
        if item["type"] == "binary":
            out["p_violation"] = ans.get("noul")
            if out["p_violation"] is None and not out["err"]:
                out["err"] = "noul 없음"
        else:
            c = ans.get("choice")
            out["choice"] = c
            out["probabilities"] = ans.get("probabilities")
            out["pred_index"] = item["choices"].index(c) if c in item["choices"] else None
            if out["pred_index"] is None and not out["err"]:
                out["err"] = "choice 없음"
        return out
    if item["type"] == "binary":
        if mode == "generative":
            r1 = client.generate_choice(arm["model"], binary_t(item, False), 2, arm.get("in_per_m", 0))
            r2 = client.generate_choice(arm["model"], binary_t(item, True), 2, arm.get("in_per_m", 0))
            votes = []
            if r1["pred_index"] is not None:
                votes.append(1.0 if r1["pred_index"] == 0 else 0.0)
            if r2["pred_index"] is not None:
                votes.append(1.0 if r2["pred_index"] == 1 else 0.0)
            p = sum(votes) / len(votes) if votes else None
            return {"p_violation": p, "ms": r1["ms"] + r2["ms"], "cost": r1["cost"] + r2["cost"],
                    "in_tok": r1["in_tok"] + r2["in_tok"], "err": r1["err"] or r2["err"], "prob_source": "none",
                    "provider": r1.get("provider")}
        r1 = client.logprob_choice(arm["model"], binary_t(item, False), 2, arm.get("in_per_m", 0))
        r2 = client.logprob_choice(arm["model"], binary_t(item, True), 2, arm.get("in_per_m", 0))
        p = None
        if r1.get("probs") and r2.get("probs"):
            p = (r1["probs"][0] + r2["probs"][1]) / 2
        return {"p_violation": p, "ms": r1["ms"] + r2["ms"], "cost": r1["cost"] + r2["cost"],
                "in_tok": r1["in_tok"] + r2["in_tok"], "err": r1["err"] or r2["err"],
                "mass": [r1.get("mass"), r2.get("mass")], "provider": r1.get("provider"),
                "reasoning_tokens": [r1.get("reasoning_tokens"), r2.get("reasoning_tokens")]}
    order = shuffled_order(item, template)
    prompt = choice_t(item, order)
    if mode == "generative":
        r = client.generate_choice(arm["model"], prompt, n, arm.get("in_per_m", 0))
        pred = order[r["pred_index"]] if r["pred_index"] is not None else None
        return {"pred_index": pred, "probs": None, "ms": r["ms"], "cost": r["cost"], "in_tok": r["in_tok"],
                "err": r["err"], "prob_source": "none", "provider": r.get("provider"), "order": order}
    r = client.logprob_choice(arm["model"], prompt, n, arm.get("in_per_m", 0))
    probs = None
    pred = None
    if r.get("probs"):
        probs = [0.0] * n
        for pos, orig in enumerate(order):
            probs[orig] = r["probs"][pos]
        pred = max(range(n), key=lambda i: probs[i])
    return {"pred_index": pred, "probs": probs, "ms": r["ms"], "cost": r["cost"], "in_tok": r["in_tok"],
            "err": r["err"], "mass": r.get("mass"), "provider": r.get("provider"),
            "reasoning_tokens": r.get("reasoning_tokens"), "order": order}


def run_bench(bench: Bench, cfg: RunConfig) -> dict:
    arms = resolve_arms(cfg.arms)
    clients = {a["key"]: make_client(a) for a in arms}
    items = bench.items[: cfg.limit] if cfg.limit else bench.items
    out, agg = [], {}
    if cfg.progress:
        print(f"{bench.name} · 항목 {len(items)} · 팔 {[a['key'] for a in arms]} · 템플릿 {bench.template}", flush=True)
    def one(it: dict) -> dict:
        binary = it["type"] == "binary"
        rec = {"id": it["id"], "target": it["target"], "label": int(it["target"] == 0) if binary else it["target"],
               "class": it.get("class"), "label_source": it.get("label_source"), "cluster": it.get("cluster"),
               "n_options": len(it["choices"]), "arms": {}}
        for a in arms:
            mode = cfg.arm_modes.get(a["key"], a["mode"])
            rec["arms"][a["key"]] = call_arm(clients[a["key"]], a, it, bench.template, mode)
        return rec

    def tally(it: dict, rec: dict) -> None:
        binary = it["type"] == "binary"
        for a in arms:
            r = rec["arms"][a["key"]]
            s = agg.setdefault(a["key"], {"n": 0, "ok": 0, "hit": 0, "ms": 0, "cost": 0.0})
            s["n"] += 1; s["ms"] += r.get("ms") or 0; s["cost"] += r.get("cost") or 0
            if not r.get("err"):
                if binary and r.get("p_violation") is not None:
                    s["ok"] += 1; s["hit"] += int((r["p_violation"] >= 0.5) == (it["target"] == 0))
                elif not binary and r.get("pred_index") is not None:
                    s["ok"] += 1; s["hit"] += int(r["pred_index"] == it["target"])

    def show(n: int, it: dict, rec: dict) -> None:
        if not cfg.progress:
            return
        binary = it["type"] == "binary"
        line = " ".join(f"{k}:" + ("ERR" if v.get("err") else (f"{v['p_violation']:.2f}" if binary else str(v.get("pred_index"))))
                        for k, v in rec["arms"].items())
        print(f"[{n:3}/{len(items)}] {it['id']:22} 정답={it['target']}  {line}", flush=True)

    # 팔 순서는 agg 의 키 순서를 정하므로 먼저 등록한다
    for a in arms:
        agg.setdefault(a["key"], {"n": 0, "ok": 0, "hit": 0, "ms": 0, "cost": 0.0})
    workers = max(1, int(cfg.concurrency or 1))
    # 라벨 팔 중 프롬프트 캐시를 쓰는 팔(Anthropic)은 첫 호출을 순차로 한 번 해 캐시를 만든다. 병렬 첫 호출이 전부 캐시 없이 나가는 걸 막는다
    def mode_of(a: dict) -> str:
        m = cfg.arm_modes.get(a["key"], a["mode"])
        return effective_mode(items[0], m) if items else m
    warm = {}
    for a in arms:
        if items and a.get("preset") == "anthropic" and mode_of(a) == "label" and workers > 1:
            r = call_arm(clients[a["key"]], a, items[0], bench.template, "label")
            warm[a["key"]] = {"cost": r.get("cost"), "err": r.get("err")}
    if workers == 1:
        for n, it in enumerate(items, 1):
            rec = one(it); tally(it, rec); show(n, it, rec); out.append(rec)
    else:
        # 항목 순서를 보존한다. 완료 순서대로 진행 표시만 한다
        out = [None] * len(items)
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(one, it): (n, it) for n, it in enumerate(items, 1)}
            for fut in cf.as_completed(futs):
                n, it = futs[fut]
                rec = fut.result()
                out[n - 1] = rec; tally(it, rec); show(n, it, rec)
    result = {
        "task": bench.name, "bench": f"{bench.name}@{bench.manifest.get('version', 1)}",
        "items_sha256": bench.items_sha256, "template": bench.template,
        "date": dt.date.today().isoformat(),
        "arms": {a["key"]: {"model": a["model"], "provider": a.get("provider"), "family": a["family"],
                            "mode": mode_of(a),
                            "prob_source": {"logprob": "logprob", "typed": "typed", "generative": "none", "label": "none"}[mode_of(a)],
                            "base_url": clients[a["key"]].host, "in_per_m": a.get("in_per_m"),
                            "smoke": (cfg.smoke or {}).get(a["key"]), "cache_warm": warm.get(a["key"])} for a in arms},
        "items": out, "agg": agg,
    }
    if cfg.out:
        cfg.out.parent.mkdir(parents=True, exist_ok=True)
        cfg.out.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    return result


def merge_results(old: dict, new: dict) -> dict:
    """같은 벤치(items_sha256 동일)의 기존 결과에 새 실행의 팔만 덮어쓴다. 다른 팔의 항목·집계는 그대로 둔다."""
    if old.get("items_sha256") != new.get("items_sha256"):
        raise ValueError("items_sha256 이 다르다. 다른 판본의 결과에는 합칠 수 없다")
    arms = set(new["arms"])
    out = dict(old)
    out["arms"] = {**old.get("arms", {}), **new["arms"]}
    out["agg"] = {**old.get("agg", {}), **new["agg"]}
    by_id = {it["id"]: it for it in new["items"]}
    merged = []
    for it in old["items"]:
        rec = dict(it); rec["arms"] = {k: v for k, v in it["arms"].items() if k not in arms}
        if it["id"] in by_id:
            rec["arms"].update(by_id[it["id"]]["arms"])
        merged.append(rec)
    out["items"] = merged
    out["date"] = new.get("date", old.get("date"))
    out.setdefault("merged_runs", []).append({"date": new.get("date"), "arms": sorted(arms)})
    return out


def print_agg(result: dict) -> None:
    print("\n" + "=" * 70)
    print(f"{'팔':10} {'성공':>7} {'정확도':>8} {'평균ms':>8} {'비용/1k판정':>12}  prob_source")
    for k, s in result["agg"].items():
        acc = s["hit"] / s["ok"] if s["ok"] else 0
        ps = (result.get("arms") or {}).get(k, {}).get("prob_source", "")
        print(f"{k:10} {s['ok']:3}/{s['n']:<3} {acc * 100:7.1f}% {s['ms'] / max(s['n'], 1):8.0f} {s['cost'] / max(s['n'], 1) * 1000:11.4f}$  {ps}")
