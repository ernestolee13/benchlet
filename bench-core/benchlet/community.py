"""커뮤니티 결과 제출과 신뢰 점수화.

- submit: 내 실행 결과(results/<bench>-run.json)를 게시 벤치에 「커뮤니티 실행」으로 낸다. 묶음은 제출자 리포 `community/<slug>/<submitter>__<arm>.json`
  (항목 해시가 게시 해시와 같아야 하고, 개별 항목 응답 전문이 들어간다).
- aggregate: 같은 벤치·같은 모델 키에 제출이 3건 이상 쌓이고 제출자가 서로 다르며 정확도 범위가 5pp 안이면 「검증됨」. 공식 점수는 중앙값.
  그 전에는 「제출 n건, 검증 대기」. 작성자 본인 제출은 세지 않는다(자기 벤치에 자기 점수).
"""
from __future__ import annotations

import datetime as dt
import json
import statistics
from pathlib import Path

import yaml

VERIFY_MIN = 3
VERIFY_SPREAD = 0.05


def model_key(arm_meta: dict, arm: str) -> str:
    m = (arm_meta or {}).get("model") or arm
    p = (arm_meta or {}).get("provider") or ""
    return f"{m}@{p}" if p else m


def build_submission(run: dict, bench_manifest: dict, submitter: str) -> dict:
    """run = benchlet 결과 파일. 벤치 해시 일치 확인 뒤 팔별 제출 레코드를 만든다."""
    if run.get("items_sha256") and bench_manifest.get("items_sha256") and run["items_sha256"] != bench_manifest["items_sha256"]:
        raise ValueError(f"항목 해시 불일치: 결과 {run['items_sha256'][:12]} vs 게시 {bench_manifest['items_sha256'][:12]}. 같은 판본에 제출해야 한다")
    arms = run.get("arms") or {}
    subs = []
    for arm, agg in (run.get("agg") or {}).items():
        meta = arms.get(arm, {})
        per_item = [{"id": it["id"], "target": it.get("target"), **{k: v for k, v in it["arms"].get(arm, {}).items() if k in ("p_violation", "pred_index", "choice", "err")}}
                    for it in run.get("items", []) if arm in it.get("arms", {})]
        subs.append({"bench": bench_manifest.get("name"), "bench_version": bench_manifest.get("version", 1), "items_sha256": run.get("items_sha256"),
                     "submitter": submitter, "date": dt.date.today().isoformat(), "arm": arm, "model_key": model_key(meta, arm),
                     "model": meta.get("model"), "provider": meta.get("provider"), "prob_source": meta.get("prob_source"), "base_url": meta.get("base_url"),
                     "n": agg.get("ok"), "hit": agg.get("hit"), "acc": (agg["hit"] / agg["ok"]) if agg.get("ok") else None,
                     "template": run.get("template"), "smoke": meta.get("smoke"), "per_item": per_item, "source_badge": "community-run"})
    return {"submissions": subs}


def write_submission(root: Path, sub: dict, slug: str, submitter: str) -> Path:
    d = root / "registry" / "community" / slug
    d.mkdir(parents=True, exist_ok=True)
    key = sub["model_key"].replace("/", "_").replace("@", "_at_")
    p = d / f"{submitter}__{key}.json"
    p.write_text(json.dumps(sub, ensure_ascii=False, indent=1), encoding="utf-8")
    return p


def load_submissions(root: Path, slug: str) -> list:
    d = root / "registry" / "community" / slug
    out = []
    if d.exists():
        for p in sorted(d.glob("*.json")):
            try:
                s = json.loads(p.read_text(encoding="utf-8")); s["_file"] = p.name; out.append(s)
            except json.JSONDecodeError:
                continue
    return out


def aggregate(subs: list, owner: str | None = None, items_sha256: str | None = None) -> dict:
    """모델 키마다 {n_submissions, submitters, median_acc, spread, verified, status}. 작성자 본인 제출과 다른 판본은 뺀다."""
    by = {}
    for s in subs:
        if owner and s.get("submitter") == owner:
            continue
        if items_sha256 and s.get("items_sha256") and s["items_sha256"] != items_sha256:
            continue
        if s.get("acc") is None:
            continue
        by.setdefault(s["model_key"], []).append(s)
    out = {}
    for k, lst in by.items():
        # 제출자마다 최신 1건
        latest = {}
        for s in sorted(lst, key=lambda x: x.get("date", "")):
            latest[s["submitter"]] = s
        accs = [s["acc"] for s in latest.values()]
        spread = max(accs) - min(accs) if accs else 0
        verified = len(latest) >= VERIFY_MIN and spread <= VERIFY_SPREAD
        out[k] = {"model": lst[0].get("model"), "provider": lst[0].get("provider"), "prob_source": lst[0].get("prob_source"),
                  "n_submissions": len(latest), "submitters": sorted(latest), "median_acc": statistics.median(accs), "min_acc": min(accs), "max_acc": max(accs),
                  "spread": spread, "verified": verified,
                  "status": "검증됨" if verified else (f"제출 {len(latest)}건, 검증 대기 (3건 이상·범위 5pp 안이면 검증)" if spread <= VERIFY_SPREAD else f"제출 {len(latest)}건, 불일치 (범위 {spread*100:.1f}pp)")}
    return out
