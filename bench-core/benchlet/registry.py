"""레지스트리 수집기와 경로 0 실행기 (PRD 10-1 「게시 이후」).

- sources.yaml: 갤러리가 읽어 오는 작성자 리포 목록. 작성자는 자기 리포에 benches/<slug>/ 로 게시하고, 여기 한 줄을 PR 로 더한다.
- sync: 각 리포를 gh 로 받아 benches/*/ 묶음을 registry/benches/<owner>/<slug>/ 로 가져오고 pointer.yaml 을 남긴다. 검증(validate 형식·개인정보) 통과분만.
- run-pending: 결과 없는 게시 벤치에 기준 팔을 한 번 돌려 결과를 붙인다(source_badge=registry-run). 작성자 실행과는 따로 표시한다.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
from pathlib import Path

import yaml

from .github import run as gh_run, CACHE
from .schema.pii import scan_items
from .config import load_banned_terms

BASELINE_ARMS = ["glm", "qwen", "deepseek", "jev"]


def sources_path(root: Path) -> Path:
    return root / "registry" / "sources.yaml"


def load_sources(root: Path) -> list:
    p = sources_path(root)
    if not p.exists():
        return []
    d = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return d.get("sources") or []


def _bundle_ok(bundle: Path) -> tuple:
    """묶음이 형식에 맞는지: manifest.yaml + samples.jsonl, 표본에 개인정보 없음."""
    man = bundle / "manifest.yaml"
    smp = bundle / "samples.jsonl"
    if not man.exists() or not smp.exists():
        return False, "manifest.yaml 또는 samples.jsonl 없음"
    try:
        m = yaml.safe_load(man.read_text(encoding="utf-8")) or {}
        rows = [json.loads(l) for l in smp.read_text(encoding="utf-8").splitlines() if l.strip()]
    except Exception as e:                       # noqa: BLE001
        return False, f"파싱 실패 {type(e).__name__}"
    for k in ("name", "question", "choices", "n"):
        if not m.get(k):
            return False, f"manifest 에 {k} 없음"
    hits = scan_items(rows, load_banned_terms())
    if hits:
        return False, f"표본 개인정보 히트 {len(hits)}"
    return True, "ok"


def sync(root: Path, runner=gh_run, cache: Path = CACHE, only: str | None = None) -> list:
    """sources.yaml 의 리포를 받아 레지스트리로 가져온다. 반환: [{repo, slug, status, reason}]"""
    out = []
    cache.mkdir(parents=True, exist_ok=True)
    for src in load_sources(root):
        repo = src["repo"] if isinstance(src, dict) else str(src)
        if only and only != repo:
            continue
        owner = repo.split("/")[0]
        local = cache / repo.replace("/", "__")
        try:
            if not (local / ".git").exists():
                shutil.rmtree(local, ignore_errors=True)
                runner(["gh", "repo", "clone", repo, str(local)])
            else:
                runner(["git", "pull", "--ff-only", "-q"], cwd=local, check=False)
            commit = runner(["git", "rev-parse", "HEAD"], cwd=local, check=False)
        except Exception as e:                   # noqa: BLE001
            out.append({"repo": repo, "slug": None, "status": "error", "reason": f"clone 실패 {type(e).__name__}"})
            continue
        cdir = local / "community"
        if cdir.is_dir():
            n_c = 0
            for slug_dir in sorted(p for p in cdir.iterdir() if p.is_dir()):
                dest_c = root / "registry" / "community" / slug_dir.name
                dest_c.mkdir(parents=True, exist_ok=True)
                for f in slug_dir.glob("*.json"):
                    try:
                        s_ = json.loads(f.read_text(encoding="utf-8"))
                    except json.JSONDecodeError:
                        continue
                    if s_.get("submitter") != owner:
                        continue          # 남의 이름으로 낸 제출은 받지 않는다(리포 주인 = 제출자)
                    shutil.copy(f, dest_c / f.name); n_c += 1
            if n_c:
                out.append({"repo": repo, "slug": "(community)", "status": "synced", "reason": f"커뮤니티 제출 {n_c}건"})
        bdir = local / "benches"
        if not bdir.is_dir():
            out.append({"repo": repo, "slug": None, "status": "skip", "reason": "benches/ 없음"})
            continue
        for bundle in sorted(p for p in bdir.iterdir() if p.is_dir()):
            ok, why = _bundle_ok(bundle)
            if not ok:
                out.append({"repo": repo, "slug": bundle.name, "status": "rejected", "reason": why})
                continue
            m = yaml.safe_load((bundle / "manifest.yaml").read_text(encoding="utf-8")) or {}
            dest = root / "registry" / "benches" / (m.get("owner") or owner) / bundle.name
            kept = _stash_registry_run(dest)          # 레지스트리 실행 결과는 작성자 리포에 없으므로 보존한다
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(bundle, dest)
            _restore_registry_run(dest, kept)
            m = yaml.safe_load((dest / "manifest.yaml").read_text(encoding="utf-8")) or {}
            ptr = {"repo": repo, "path": f"benches/{bundle.name}", "commit": commit,
                   "url": f"https://github.com/{repo}/tree/{commit or 'main'}/benches/{bundle.name}",
                   "synced_at": dt.datetime.now().isoformat(timespec="seconds")}
            (dest / "pointer.yaml").write_text(yaml.safe_dump(ptr, allow_unicode=True, sort_keys=False), encoding="utf-8")
            out.append({"repo": repo, "slug": bundle.name, "status": "synced", "reason": f"n={m.get('n')} results={'pending' if m.get('results') == 'pending' else 'yes'}"})
    return out


def _stash_registry_run(dest: Path) -> dict:
    """기존 묶음의 registry-run 결과 파일과 매니페스트의 레지스트리 실행 필드를 챙겨 둔다."""
    if not dest.exists():
        return {}
    kept = {"files": {}, "manifest": {}}
    for f in (dest / "results").glob("*-registry-run.json") if (dest / "results").exists() else []:
        kept["files"][f.name] = f.read_bytes()
    mp = dest / "manifest.yaml"
    if mp.exists():
        m = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
        kept["manifest"] = {"registry_run": m.get("registry_run"),
                            "result_summary": {a: s for a, s in (m.get("result_summary") or {}).items() if s.get("source_badge") == "registry-run"},
                            "experiment": m.get("experiment") if (m.get("registry_run")) else None}
    return kept


def _restore_registry_run(dest: Path, kept: dict) -> None:
    if not kept or not kept.get("files") and not kept.get("manifest", {}).get("registry_run"):
        return
    (dest / "results").mkdir(exist_ok=True)
    for name, data in kept["files"].items():
        (dest / "results" / name).write_bytes(data)
    mp = dest / "manifest.yaml"
    m = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
    km = kept["manifest"]
    if km.get("registry_run"):
        m["registry_run"] = km["registry_run"]
        res = m.get("results") if isinstance(m.get("results"), list) else []
        res += [f"results/{n}" for n in kept["files"] if f"results/{n}" not in res]
        m["results"] = res or "pending"
        rs = m.get("result_summary") or {}
        # 작성자 결과와 레지스트리 결과가 같은 팔 키로 겹치면 레지스트리 쪽은 접미사로 구분한다
        for a, s in km["result_summary"].items():
            rs[a if a not in rs else f"{a} (registry)"] = s
        m["result_summary"] = rs
        if not m.get("experiment") and km.get("experiment"):
            m["experiment"] = km["experiment"]
        mp.write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")


def pending(root: Path) -> list:
    """결과 없는 게시 벤치 목록 [(manifest_path, manifest)]"""
    out = []
    for mp in sorted((root / "registry" / "benches").glob("*/*/manifest.yaml")):
        m = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
        if m.get("results") == "pending" or not m.get("results"):
            out.append((mp, m))
    return out


def run_pending(root: Path, arms: list | None = None, limit: int = 0, skip_smoke: bool = False, progress=print) -> list:
    """기준 팔로 결과 없는 게시 벤치를 돌린다. 항목은 묶음의 samples(visibility=full) 또는 원 항목 파일이 로컬에 있을 때 그것."""
    from .schema import load_bench
    from .runner.run import run_bench, RunConfig
    from .runner.smoke import smoke_bench
    from .stats.report import build_report
    from .review.results import load_results
    arms = arms or BASELINE_ARMS
    done = []
    for mp, m in pending(root):
        bundle = mp.parent
        # 항목 원천: 로컬 원본이 있으면 그것, 없으면 visibility=full 인 samples
        try:
            b = load_bench(m["name"], root)
            source = "local-items"
        except FileNotFoundError:
            if m.get("visibility") != "full":
                done.append({"bench": m["name"], "status": "skip", "reason": "전체 항목이 없다(visibility=sample). 작성자 리포의 items 가 필요"})
                continue
            b = load_bench(str(bundle / "samples.jsonl"), root)
            source = "bundle-samples"
        if b.items_sha256 != m.get("items_sha256") and source == "local-items":
            done.append({"bench": m["name"], "status": "skip", "reason": "로컬 항목 해시가 게시 해시와 다르다"})
            continue
        use = list(arms)
        modes, smoke = {}, None
        if not skip_smoke:
            smoke = smoke_bench(b, use, progress=False)
            bad = [k for k, v in smoke.items() if not v["usable"]]
            modes = {k: v["mode"] for k, v in smoke.items()}
            use = [k for k in use if k not in bad]
            if not use:
                done.append({"bench": m["name"], "status": "unusable", "reason": f"스모크 실패 {bad}"}); continue
        out = bundle / "results" / f"{m['name']}-registry-run.json"
        res = run_bench(b, RunConfig(arms=use, limit=limit, out=out, progress=False, smoke=smoke, arm_modes=modes))
        rep = build_report(b, load_results(out, b.items))
        raw = json.loads(out.read_text(encoding="utf-8"))
        m["results"] = [f"results/{out.name}"]
        m["result_summary"] = {a: {"acc": s["acc"], "ci95": s["ci95"], "auroc": s["auroc"], "brier": s["brier"], "n": s["ok"],
                                   "prob_source": raw["arms"][a]["prob_source"], "model": raw["arms"][a]["model"],
                                   "source_badge": "registry-run"} for a, s in rep["summary"].items()}
        from .mcp.server import _experiment_block
        m["experiment"] = _experiment_block(raw)
        m["experiment"]["runner"] = "benchlet (registry-run, 기준 팔)"
        m["registry_run"] = {"date": dt.date.today().isoformat(), "arms": use, "items_source": source, "excluded": [k for k in arms if k not in use]}
        mp.write_text(yaml.safe_dump(m, allow_unicode=True, sort_keys=False), encoding="utf-8")
        done.append({"bench": m["name"], "status": "done", "reason": " ".join(f"{a}={res['agg'][a]['hit']}/{res['agg'][a]['ok']}" for a in use)})
        progress(f"registry-run {m['name']}: {done[-1]['reason']}")
    return done
