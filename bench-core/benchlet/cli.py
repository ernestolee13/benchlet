"""benchlet validate | smoke | run | report | review | export | publish

실행은 게시의 조건이 아니다. 키가 없으면 validate → review → publish 만으로 끝난다(경로 0).
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import NAME, __version__
from .config import find_repo_root, load_banned_terms
from .schema import load_bench, validate_bench
from .schema.pii import scan_items


def _root(a) -> Path:
    return Path(a.root).resolve() if getattr(a, "root", None) else find_repo_root()


def cmd_validate(a) -> int:
    root = _root(a)
    rc = 0
    for spec in a.bench:
        try:
            b = load_bench(spec, root)
        except Exception as e:                      # noqa: BLE001
            print(f"{spec}: 로드 실패: {e}")
            rc = 1
            continue
        r = validate_bench(b, sha_file=root / "labels" / "SHA256SUMS")
        print(f"[{ 'PASS' if r.ok else 'FAIL'}] {b.name} ({b.path})")
        for line in r.summary_lines():
            print("   " + line)
        if not r.ok:
            rc = 1
    return rc


def cmd_smoke(a) -> int:
    from .runner.smoke import smoke_bench, render_smoke
    root = _root(a)
    b = load_bench(a.bench, root)
    arms = [x for x in a.arms.split(",") if x]
    v = smoke_bench(b, arms, repeats=a.repeats)
    print(render_smoke(v))
    if a.out:
        Path(a.out).write_text(json.dumps(v, ensure_ascii=False, indent=1), encoding="utf-8")
    usable = [k for k, x in v.items() if x["usable"]]
    if not usable:
        print("\n쓸 수 있는 조합이 없다. 실행하지 말고 게시만 해라(경로 0). 레지스트리가 기준 팔을 돌려 결과를 붙인다.")
        return 3
    if len(usable) < len(v):
        return 2
    return 0


def cmd_run(a) -> int:
    from .runner.run import run_bench, RunConfig, print_agg
    from .runner.smoke import smoke_bench, render_smoke
    root = _root(a)
    b = load_bench(a.bench, root)
    arms = [x for x in a.arms.split(",") if x]
    smoke = None
    modes = {}
    if not a.skip_smoke:
        print("스모크 (5건 · 3회 재현성 · 확률값 종류 수)")
        smoke = smoke_bench(b, arms)
        print(render_smoke(smoke))
        from .runner.smoke import polarity_suspect
        if polarity_suspect(smoke) and not a.force_polarity:
            print("중단: 극성·target 뒤집힘 의심. 고친 뒤 다시 돌리거나, 정말 모델 문제면 --force-polarity")
            return 4
        bad = [k for k, v in smoke.items() if not v["usable"]]
        modes = {k: v["mode"] for k, v in smoke.items()}
        if bad and not a.force:
            arms = [k for k in arms if k not in bad]
            print(f"못 쓰는 조합 제외: {bad}" + (" → 남은 팔 없음. 게시만 해라(경로 0)" if not arms else ""))
            if not arms:
                return 3
    out = Path(a.out) if a.out else root / "results" / f"{b.name}{a.suffix}-run.json"
    if a.merge and out.exists():
        from .runner.run import merge_results
        old = json.loads(out.read_text(encoding="utf-8"))
        res = run_bench(b, RunConfig(arms=arms, limit=a.limit, out=None, smoke=smoke, arm_modes=modes, concurrency=a.concurrency))
        res = merge_results(old, res)
        out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        res = run_bench(b, RunConfig(arms=arms, limit=a.limit, out=out, smoke=smoke, arm_modes=modes, concurrency=a.concurrency))
    print_agg(res)
    print(f"\n기록 {out}")
    return 0


def cmd_report(a) -> int:
    from .review.results import load_results, find_results
    from .stats.report import build_report, render_report
    root = _root(a)
    rc = 0
    for spec in a.bench:
        b = load_bench(spec, root)
        p = find_results(b.name, root, a.results)
        if not p:
            print(f"{b.name}: 결과 파일이 없다 (results: pending). 실행은 선택이다")
            rc = 1
            continue
        rep = build_report(b, load_results(p, b.items))
        print(render_report(rep))
        print()
    return rc


def cmd_review(a) -> int:
    from .review import run_checks, render_markdown
    from .review.results import load_results, find_results
    root = _root(a)
    b = load_bench(a.bench, root)
    res = None
    p = find_results(b.name, root, a.results)
    if p:
        res = load_results(p, b.items)
    checks = [int(x) for x in a.checks.split(",")] if a.checks else None
    rules = None
    if a.rules:
        rules = json.loads(Path(a.rules).read_text(encoding="utf-8")) if a.rules.endswith(".json") else __import__("yaml").safe_load(Path(a.rules).read_text(encoding="utf-8"))
    rep = run_checks(b, res, checks, rules=rules)
    md = render_markdown(rep)
    print(md)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        Path(a.out).with_suffix(".json").write_text(json.dumps(rep.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


def cmd_export(a) -> int:
    from .export import to_inspect_jsonl, to_lm_eval_yaml, to_hf_eval_yaml
    from .review.results import find_results
    root = _root(a)
    b = load_bench(a.bench, root)
    out = Path(a.out) if a.out else root / "export" / b.name
    if a.format == "inspect":
        p = to_inspect_jsonl(b, out / f"{b.name}.inspect.jsonl")
    elif a.format == "lm-eval":
        p = to_lm_eval_yaml(b, out)
    else:
        rp = find_results(b.name, root, None)
        results = json.loads(rp.read_text(encoding="utf-8")) if rp else None
        p = to_hf_eval_yaml(b, out / "eval.yaml", results)
    print(f"내보냄 {p}")
    return 0


def cmd_list(a) -> int:
    """로컬 벤치 목록(tasks/, tasks/retired, tasks/parked, benches/, registry). 갤러리 조회 전 중복을 본다."""
    root = _root(a)
    rows = []
    for p in sorted(root.glob("tasks/*.jsonl")) + sorted(root.glob("tasks/retired/*.jsonl")) + sorted(root.glob("tasks/parked/*.jsonl")) + sorted(root.glob("benches/*/bench.yaml")):
        try:
            b = load_bench(str(p), root)
        except Exception as e:                      # noqa: BLE001
            rows.append((str(p.relative_to(root)), "?", "?", f"로드 실패: {e}")); continue
        q = (b.question or "(질문 여럿)").strip().splitlines()[0][:50]
        rows.append((str(p.relative_to(root)), str(len(b.items)), b.type, q))
    print(f"{'경로':44} {'n':>4} {'유형':10} 질문")
    for r in rows:
        print(f"{r[0]:44} {r[1]:>4} {r[2]:10} {r[3]}")
    reg = sorted(root.glob("registry/benches/*/*/manifest.yaml"))
    if reg:
        print(f"\n레지스트리(게시됨) {len(reg)}개: " + ", ".join(p.parent.name for p in reg))
    return 0


def cmd_manifest(a) -> int:
    """항목 파일에서 매니페스트를 만든다(질문·선택지·n·해시·서명 골격). 손으로 YAML 을 쓰다 콜론에 죽지 않게."""
    import yaml
    root = _root(a)
    b = load_bench(a.bench, root)
    p = b.path.with_name(b.path.stem + ".manifest.yaml")
    if p.exists() and not a.force:
        print(f"이미 있다: {p} (--force 로 덮어씀)"); return 1
    man = {"name": b.name, "version": 1,
           "task_signature": {"goal": a.goal or "", "answer": "binary" if b.type == "binary" else f"choice({len(b.choices or [])})",
                              "prob_use": "accuracy_only", "label": max(set(it.get("label_source") for it in b.items), key=[it.get("label_source") for it in b.items].count),
                              "unit": a.unit or "", "language": "ko", "n": len(b.items)},
           "question": b.question, "choices": b.choices, "generator": {"script": a.generator or "", "seed": a.seed},
           "source": a.source or "", "visibility": "sample", "items_sha256": b.items_sha256,
           "review": {"checks_run": 0, "human_reviewed_fraction": 0.0, "flagged": 0, "decided": 0}, "license": "CC-BY-4.0"}
    p.write_text(yaml.safe_dump(man, allow_unicode=True, sort_keys=False, width=1000), encoding="utf-8")
    print(f"매니페스트 {p.relative_to(root)} (goal·unit·source 는 채워라)")
    return 0


def cmd_site(a) -> int:
    from .site import build_site
    root = _root(a)
    p = build_site(root, Path(a.out) if a.out else root / "site")
    print(f"사이트 {p}")
    return 0


def cmd_registry(a) -> int:
    from . import registry as R
    root = _root(a)
    if a.action == "sync":
        rows = R.sync(root, only=a.repo)
        for r in rows:
            print(f"{r['status']:9} {r['repo']:40} {r['slug'] or '-':32} {r['reason']}")
        return 0 if any(r["status"] == "synced" for r in rows) else 1
    if a.action == "pending":
        for mp, m in R.pending(root):
            print(f"{m['name']:32} n={m.get('n')} visibility={m.get('visibility')} owner={m.get('owner')}")
        return 0
    if a.action == "run-pending":
        arms = [x for x in a.arms.split(",") if x] if a.arms else None
        rows = R.run_pending(root, arms, a.limit, a.skip_smoke)
        for r in rows:
            print(f"{r['status']:9} {r['bench']:32} {r['reason']}")
        return 0
    return 1


def cmd_taxonomy(a) -> int:
    """taxonomy apply: registry/taxonomy_labels.yaml 의 레이블을 매니페스트에 넣는다. check: 모든 벤치의 레이블을 어휘로 검사한다."""
    import yaml
    from . import taxonomy as T
    root = _root(a)
    tax = T.load(root)
    if a.action == "apply":
        labels = yaml.safe_load((root / "registry" / "taxonomy_labels.yaml").read_text(encoding="utf-8")) or {}
        n = 0
        for slug, lab in labels.items():
            for cand in [root / "tasks" / f"{slug}.manifest.yaml", root / "benches" / slug / "bench.yaml",
                         *[p for p in (root / "benches").glob("*/bench.yaml") if (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("name") == slug]]:
                if cand.exists():
                    T.apply_file(root, cand, lab, tax); n += 1; break
            else:
                print(f"매니페스트 없음: {slug}")
        print(f"레이블 적용 {n}개")
        return 0
    bad = 0
    for p in sorted(root.glob("tasks/*.manifest.yaml")) + sorted(root.glob("benches/*/bench.yaml")):
        m = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        w = T.check_labels(tax, T.labels_of(m))
        if w:
            bad += 1; print(f"{m.get('name') or p}: " + "; ".join(w))
    print(f"어휘 밖 또는 미기재 {bad}개")
    return 1 if bad else 0


def cmd_star(a) -> int:
    """벤치 작성자의 벤치 리포에 스타를 남긴다. 신뢰 점수와 추천 가중에 반영된다."""
    from .mcp.server import bench_star
    r = bench_star(a.bench_id, confirm=a.yes)
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0 if r.get("starred") or r.get("needs_confirm") else 1


def cmd_submit(a) -> int:
    """내 실행 결과를 게시 벤치의 커뮤니티 점수로 제출한다. 로컬 registry/community 에 쓰고 --github 면 내 리포 community/<slug>/ 에 푸시한다."""
    import yaml
    from . import community as CM
    from . import github as gh
    root = _root(a)
    run = json.loads(Path(a.results).read_text(encoding="utf-8"))
    mp = None
    for cand in sorted((root / "registry" / "benches").glob(f"*/{a.bench}/manifest.yaml")):
        mp = cand
    if not mp:
        print(f"게시된 벤치가 아니다: {a.bench} (registry sync 먼저)"); return 1
    man = yaml.safe_load(mp.read_text(encoding="utf-8"))
    submitter = gh.gh_login() or a.submitter or "anonymous"
    try:
        pack = CM.build_submission(run, man, submitter)
    except ValueError as e:
        print(str(e)); return 1
    written = [CM.write_submission(root, s, a.bench, submitter) for s in pack["submissions"]]
    print(f"제출 {len(written)}건 → registry/community/{a.bench}/ ({submitter})")
    if a.github:
        full = gh.ensure_repo(a.repo or gh.DEFAULT_REPO, False)
        ptr = gh.push_bundle(root / "registry" / "community" / a.bench, full, f"community/{a.bench}", f"community results for {a.bench} by {submitter}")
        print(f"GitHub: {ptr['url']}")
    agg = CM.aggregate(CM.load_submissions(root, a.bench), owner=man.get("owner"), items_sha256=man.get("items_sha256"))
    for k, v in agg.items():
        print(f"  {k}: {v['status']} (중앙값 {v['median_acc']*100:.1f}%)")
    return 0


def cmd_distill(a) -> int:
    """공개 벤치 정오 행렬에서 n 건을 골라 항목 파일로 쓴다. --items 는 항목 id 를 키로 가진 확장 형식 jsonl(전체)."""
    from .distill import load_matrix, distill, render
    root = _root(a)
    mx = load_matrix(Path(a.matrix))
    r = distill(mx, n=a.n, seed=a.seed, iters=a.iters)
    print(render(r))
    if a.items and a.out:
        by_id = {}
        for line in Path(a.items).read_text(encoding="utf-8").splitlines():
            if line.strip():
                it = json.loads(line); by_id[str(it["id"])] = it
        out = Path(a.out); out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as f:
            for iid in r["selected"]:
                it = by_id.get(iid)
                if not it:
                    continue
                it = dict(it); it.setdefault("metadata", {})["source_difficulty"] = r["difficulty"][iid]
                f.write(json.dumps(it, ensure_ascii=False) + "\n")
        rep = dict(r); rep.pop("selected_idx", None)
        out.with_suffix(".distill.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"항목 {out} · 보고 {out.with_suffix('.distill.json')}")
    return 0


def cmd_mcp(a) -> int:
    from .mcp.server import main as serve
    return serve()


def cmd_publish(a) -> int:
    """게시 묶음을 만든다(로컬). manifest.yaml + samples.jsonl + results/ (없으면 pending). 개인정보 히트가 있으면 거부."""
    import yaml
    from .review.results import find_results
    root = _root(a)
    b = load_bench(a.bench, root)
    if a.registry or a.github:
        from .mcp.server import bench_publish
        from .mcp.protocol import ToolError
        try:
            r = bench_publish(str(b.path), a.visibility, confirm=True, target="github" if a.github else "local", repo=a.repo, private=a.private)
        except (ToolError, RuntimeError) as e:
            print(str(e)); return 1
        print(f"게시 {r['path']} (results: {r['results']}, 표본 {r['n_samples']}). 실행은 선택이다")
        if r.get("github"):
            print(f"GitHub: {r['github']['url']}")
        return 0
    r = validate_bench(b, sha_file=root / "labels" / "SHA256SUMS")
    if not r.ok:
        print("게시 거부: validate 실패")
        for line in r.summary_lines():
            print("   " + line)
        return 1
    out = Path(a.out) if a.out else root / "publish" / b.name
    out.mkdir(parents=True, exist_ok=True)
    man = dict(b.manifest)
    man.setdefault("name", b.name)
    man.setdefault("version", 1)
    man["items_sha256"] = b.items_sha256
    man["n"] = len(b.items)
    man["choices"] = b.choices
    man["question"] = b.question or man.get("question")      # 항목마다 질문이 다르면 매니페스트의 요약 질문을 둔다
    man.setdefault("visibility", "sample")
    rp = find_results(b.name, root, None)
    if rp:
        (out / "results").mkdir(exist_ok=True)
        shutil.copy(rp, out / "results" / rp.name)
        man["results"] = [f"results/{rp.name}"]
    else:
        man["results"] = "pending"
    (out / "manifest.yaml").write_text(yaml.safe_dump(man, allow_unicode=True, sort_keys=False), encoding="utf-8")
    sample = b.items[:5] if man["visibility"] != "full" else b.items
    with (out / "samples.jsonl").open("w", encoding="utf-8") as f:
        for it in sample:
            f.write(json.dumps({k: v for k, v in it.items() if k != "metadata"}, ensure_ascii=False) + "\n")
    hits = scan_items(sample, load_banned_terms())
    if hits:
        print(f"게시 거부: 표본에 개인정보 히트 {len(hits)}")
        return 1
    print(f"게시 묶음 {out} (results: {man['results']}). 실행은 선택이다. 레지스트리 PR 은 2단계")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog=NAME, description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", action="version", version=f"{NAME} {__version__}")
    ap.add_argument("--root", help="리포 루트(기본: tasks/ 또는 .git 을 찾아 올라간다)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="최소·확장·구식 형식 검증, 극성·글자 접두·중복 해시·개인정보 스캔")
    p.add_argument("bench", nargs="+"); p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("smoke", help="5건 스모크 · 3회 재현성 · 확률값 종류 수 (전량 전에 강제)")
    p.add_argument("--bench", required=True); p.add_argument("--arms", default="qwen,jev")
    p.add_argument("--repeats", type=int, default=3); p.add_argument("--out"); p.set_defaults(fn=cmd_smoke)

    p = sub.add_parser("run", help="전량 실행 (스모크 먼저)")
    p.add_argument("--bench", required=True); p.add_argument("--arms", default="qwen,jev")
    p.add_argument("--limit", type=int, default=0); p.add_argument("--out"); p.add_argument("--suffix", default="")
    p.add_argument("--concurrency", type=int, default=6, help="항목 단위 동시 호출 수 (기본 6, 1 이면 순차)")
    p.add_argument("--merge", action="store_true", help="기존 결과 파일이 있으면 이번 팔만 덮어쓰고 나머지 팔은 유지한다 (같은 판본일 때만)")
    p.add_argument("--skip-smoke", action="store_true"); p.add_argument("--force", action="store_true", help="스모크에 걸린 조합도 돌린다")
    p.add_argument("--force-polarity", action="store_true", help="전 팔이 뻔한 항목을 다 틀려도(극성 뒤집힘 의심) 전량을 돌린다")
    p.set_defaults(fn=cmd_run)

    p = sub.add_parser("report", help="정확도·Wilson·클래스별·AUROC·Brier·McNemar")
    p.add_argument("bench", nargs="+"); p.add_argument("--results"); p.set_defaults(fn=cmd_report)

    p = sub.add_parser("review", help="검수 검사 v0 → 플래그 큐")
    p.add_argument("--bench", required=True); p.add_argument("--results"); p.add_argument("--checks", help="예: 1,2,5")
    p.add_argument("--rules", help="검사 8 매처 파일(yaml|json) {선택지: [정규식]}"); p.add_argument("--out")
    p.set_defaults(fn=cmd_review)

    p = sub.add_parser("export", help="inspect | lm-eval | hf")
    p.add_argument("--bench", required=True); p.add_argument("--format", choices=["inspect", "lm-eval", "hf"], default="inspect")
    p.add_argument("--out"); p.set_defaults(fn=cmd_export)

    p = sub.add_parser("publish", help="게시 묶음 생성(결과 없이도 통과, results: pending). --registry 면 registry/benches/<owner>/<slug> 에 쓴다")
    p.add_argument("--bench", required=True); p.add_argument("--out"); p.add_argument("--registry", action="store_true")
    p.add_argument("--visibility", choices=["generator", "sample", "full"], default="sample")
    p.add_argument("--github", action="store_true", help="gh 로그인 계정의 리포(기본 benchlet-benches)에 커밋·푸시하고 포인터를 남긴다")
    p.add_argument("--repo"); p.add_argument("--private", action="store_true"); p.set_defaults(fn=cmd_publish)

    p = sub.add_parser("whoami", help="gh 로그인(작성자 신원) 확인")
    p.set_defaults(fn=lambda a: (print(__import__("benchlet.github", fromlist=["gh_login"]).gh_login() or "gh 로그인 없음 (gh auth login)"), 0)[1])

    p = sub.add_parser("list", help="로컬 벤치 목록 (중복 확인용)")
    p.set_defaults(fn=cmd_list)

    p = sub.add_parser("manifest", help="항목 파일에서 .manifest.yaml 골격 생성")
    p.add_argument("--bench", required=True); p.add_argument("--goal"); p.add_argument("--unit"); p.add_argument("--generator")
    p.add_argument("--seed", type=int, default=20260930); p.add_argument("--source"); p.add_argument("--force", action="store_true")
    p.set_defaults(fn=cmd_manifest)

    p = sub.add_parser("site", help="정적 갤러리 생성 (registry → site/index.html)")
    p.add_argument("action", choices=["build"]); p.add_argument("--out"); p.set_defaults(fn=cmd_site)

    p = sub.add_parser("registry", help="sync (sources.yaml 리포에서 벤치 수집) | pending | run-pending (기준 팔 실행)")
    p.add_argument("action", choices=["sync", "pending", "run-pending"]); p.add_argument("--repo"); p.add_argument("--arms")
    p.add_argument("--limit", type=int, default=0); p.add_argument("--skip-smoke", action="store_true"); p.set_defaults(fn=cmd_registry)

    p = sub.add_parser("taxonomy", help="분류 체계: apply (레이블 파일 → 매니페스트) | check (어휘 검사)")
    p.add_argument("action", choices=["apply", "check"]); p.set_defaults(fn=cmd_taxonomy)

    p = sub.add_parser("star", help="벤치 작성자의 벤치 리포에 스타 (registry/benches/<owner>/<name> 또는 remote:<owner>/<name>)")
    p.add_argument("bench_id"); p.add_argument("--yes", action="store_true", help="확인 없이 스타"); p.set_defaults(fn=cmd_star)
    p = sub.add_parser("submit", help="내 실행 결과를 게시 벤치의 커뮤니티 점수로 제출 (3건 이상 일치하면 검증됨)")
    p.add_argument("--bench", required=True); p.add_argument("--results", required=True); p.add_argument("--github", action="store_true")
    p.add_argument("--repo"); p.add_argument("--submitter"); p.set_defaults(fn=cmd_submit)

    p = sub.add_parser("distill", help="공개 벤치 정오 행렬(모델×항목)에서 n 건 축약 (난이도 층화 + 교환 탐색, 검증 모델 보고)")
    p.add_argument("--matrix", required=True); p.add_argument("--items"); p.add_argument("--out")
    p.add_argument("--n", type=int, default=100); p.add_argument("--seed", type=int, default=20261003); p.add_argument("--iters", type=int, default=4000)
    p.set_defaults(fn=cmd_distill)

    p = sub.add_parser("mcp", help="MCP stdio 서버 기동 (bench_* 툴 18개)")
    p.set_defaults(fn=cmd_mcp)

    a = ap.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
