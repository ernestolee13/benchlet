"""정적 갤러리. registry/benches/*/*/manifest.yaml + samples.jsonl + results/*.json 을 읽어 한 파일 HTML 을 만든다.

    benchlet site build [--out site]
페이지 넷이 한 파일 안의 뷰다: 갤러리, 벤치 상세, 유형별 추천, 만들기 가이드. 계정·DB 없음(v1 정적).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import math
from collections import defaultdict
from pathlib import Path

import yaml

from .stats.metrics import wilson


def _load_registry(root: Path) -> list:
    out = []
    for mp in sorted((root / "registry" / "benches").glob("*/*/manifest.yaml")):
        m = yaml.safe_load(mp.read_text(encoding="utf-8")) or {}
        d = mp.parent
        samples = []
        sp = d / "samples.jsonl"
        if sp.exists():
            samples = [json.loads(l) for l in sp.read_text(encoding="utf-8").splitlines() if l.strip()]
        per_class = {}
        arms_meta = {}
        if isinstance(m.get("results"), list):
            for rp in m["results"]:
                f = d / rp
                if not f.exists():
                    continue
                raw = json.loads(f.read_text(encoding="utf-8"))
                arms_meta = raw.get("arms") or {}
                tab = defaultdict(lambda: defaultdict(lambda: [0, 0]))
                for rec in raw["items"]:
                    binary = rec.get("n_options", 2) == 2 and "target" in rec or "label" in rec and "target" not in rec
                    tgt = rec.get("target")
                    if tgt is None:
                        tgt = 0 if rec.get("label") == 1 else 1
                    for arm, a in rec["arms"].items():
                        if a.get("err"):
                            continue
                        if a.get("p_violation") is not None:
                            hit = int((a["p_violation"] >= 0.5) == (tgt == 0))
                        elif a.get("pred_index") is not None:
                            hit = int(a["pred_index"] == tgt)
                        elif a.get("choice") is not None and isinstance(m.get("choices"), list) and a["choice"] in m["choices"]:
                            hit = int(m["choices"].index(a["choice"]) == tgt)
                        else:
                            continue
                        c = rec.get("class") or "-"
                        tab[c][arm][0] += hit; tab[c][arm][1] += 1
                per_class = {c: {a: v for a, v in d2.items()} for c, d2 in tab.items()}
        from .community import load_submissions, aggregate
        subs = load_submissions(root, m.get("name"))
        community = {"n_submissions": len(subs), "n_submitters": len({x.get("submitter") for x in subs}),
                     "models": aggregate(subs, owner=m.get("owner"), items_sha256=m.get("items_sha256"))}
        pointer = None
        if (d / "pointer.yaml").exists():
            pointer = yaml.safe_load((d / "pointer.yaml").read_text(encoding="utf-8"))
        rs = m.get("result_summary") or {}
        for a, s in rs.items():
            if s.get("acc") is not None and s.get("n"):
                lo, hi = wilson(round(s["acc"] * s["n"]), s["n"])
                s["ci95"] = [lo, hi]
        out.append({"name": m.get("name"), "owner": m.get("owner"), "version": m.get("version", 1), "n": m.get("n"),
                    "experiment": m.get("experiment") or {}, "domain": m.get("domain") or [], "pointer": pointer, "community": community,
                    "taxonomy": m.get("taxonomy") or {}, "keywords": m.get("keywords") or [],
                    "type": m.get("type"), "question": m.get("question"), "choices": m.get("choices"),
                    "signature": m.get("task_signature") or {}, "classes": m.get("classes") or [],
                    "label_source_mix": m.get("label_source_mix") or {}, "visibility": m.get("visibility"),
                    "published_at": str(m.get("published_at") or ""), "results": m.get("results"),
                    "result_summary": rs, "per_class": per_class, "arms_meta": arms_meta, "review": m.get("review") or {},
                    "generator": m.get("generator") or {}, "source": m.get("source") or "", "license": m.get("license"),
                    "samples": samples, "path": str(d.relative_to(root)), "items_sha256": m.get("items_sha256"),
                    "forked_from": m.get("forked_from"), "source_results": m.get("source_results")})
    return out


def _cost_stat(root: Path) -> dict:
    """레지스트리 결과 전체에서 판정 1건(항목 × 모델) 평균 비용(USD). 원화는 1,400원/달러 고정 환산."""
    tot, n = 0.0, 0
    for p in (root / "registry" / "benches").glob("*/*/results/*.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except Exception:            # noqa: BLE001
            continue
        for it in d.get("items") or []:
            for a in (it.get("arms") or {}).values():
                if isinstance(a, dict) and a.get("cost") is not None and not a.get("err"):
                    tot += float(a["cost"]); n += 1
    usd = tot / n if n else 0.0
    return {"per_judgment_usd": usd, "per_judgment_krw": usd * 1400, "n_judgments": n}


def _model_counts(benches: list) -> dict:
    """갤러리에 등장한 서로 다른 모델 수. 직접 돌린 모델(arms_meta), 커뮤니티 제출 모델, 축약 시드의 원천 리더보드 모델을 합친다(이름 소문자 기준 중복 제거)."""
    def norm(x):
        return str(x or "").strip().lower()
    run, src, comm = set(), set(), set()
    for b in benches:
        for a in (b.get("arms_meta") or {}).values():
            if isinstance(a, dict) and a.get("model"):
                run.add(norm(a["model"]))
        for k, v in ((b.get("community") or {}).get("models") or {}).items():
            comm.add(norm((v or {}).get("model") or k))
        for m in ((b.get("source_results") or {}).get("models") or []):
            src.add(norm(m.get("model")))
    run.discard(""); src.discard(""); comm.discard("")
    return {"run": len(run), "community": len(comm), "source": len(src), "total": len(run | src | comm)}


def _gh_json(path: str) -> dict | None:
    """gh CLI 로 GitHub API 를 읽는다. gh 가 없거나 실패하면 None (빌드는 계속)."""
    import shutil, subprocess
    if not shutil.which("gh"):
        return None
    try:
        r = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=20)
        return json.loads(r.stdout) if r.returncode == 0 and r.stdout.strip() else None
    except Exception:            # noqa: BLE001
        return None


def _owners(root: Path) -> dict:
    """작성자 레지스트리 + 빌드 시점의 GitHub 공개 신호(팔로워, 공개 리포, 생성기 리포 스타, 벤치 리포 스타).
    신호는 카드 정렬과 추천 가중에 쓰이고 그대로 카드에 보인다. 값을 못 읽으면 0 으로 두고 fetched_at 을 비운다."""
    import datetime as dt
    out = {}
    for p in sorted((root / "registry" / "owners").glob("*.yaml")):
        o = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        h = o.get("handle") or p.stem
        gh = {"followers": 0, "public_repos": 0, "repo_stars": 0, "bench_repo_stars": 0, "fetched_at": None}
        u = _gh_json(f"users/{h}")
        if u:
            gh["followers"] = u.get("followers") or 0; gh["public_repos"] = u.get("public_repos") or 0; gh["fetched_at"] = dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
        for key, url in (("repo_stars", o.get("repo")), ("bench_repo_stars", o.get("bench_repo") or f"https://github.com/{h}/benchlet-benches")):
            m = re.search(r"github\.com/([^/]+)/([^/#?]+)", url or "")
            r = _gh_json(f"repos/{m.group(1)}/{m.group(2)}") if m else None
            if r:
                gh[key] = r.get("stargazers_count") or 0
        o["gh_stats"] = gh
        out[h] = o
    return out


def _guide(root: Path) -> dict:
    refs = next((d for d in (root / "skills" / "minibench-author" / "references", root / "skill" / "minibench-author" / "references") if d.exists()), root / "skills" / "minibench-author" / "references")
    def rd(name):
        p = refs / name
        return p.read_text(encoding="utf-8") if p.exists() else ""
    return {"rubric": rd("rubric.md"), "question": rd("question.md"), "format": rd("format.md"),
            "lessons": rd("lessons.md"), "traps": rd("traps.md"), "run_guide": rd("run-guide.md"), "generate": rd("generate.md")}


def _recall_summary(root: Path) -> str:
    p = root / "docs" / "REVIEW_RECALL.md"
    if not p.exists():
        return ""
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.startswith("**재현률"):
            return line.strip("* ")
    return ""


EN_DESCRIPTION = ("Small judgment benchmarks built from your own data. Pull 40 to 100 items from an approval gate, classifier, router or tool-call decision, "
                  "run general LLMs and judgment-only models like Jev under identical conditions, and see which model fits that decision. Shared through the author's own GitHub repo.")
EN_META = "Judgment mini-benchmarks from your own data: 40 to 100 items, cheap models and Jev-like judges compared under identical conditions, shared via your GitHub repo."


def _en_page(data: dict) -> str:
    """영어 랜딩(정적). 갤러리 UI 는 한국어지만 벤치 데이터와 도구는 영어로도 쓴다. SEO 용 별도 URL /en."""
    n = len(data["benches"]); n_items = sum(b.get("n") or 0 for b in data["benches"])
    models = data.get("models") or {}; cost = data.get("cost") or {}
    ex = next((b for b in data["benches"] if b["name"] == "editorial-norm"), None)
    rows = []
    if ex:
        for a, st in sorted((ex.get("result_summary") or {}).items(), key=lambda kv: -(kv[1].get("acc") or 0)):
            if st.get("acc") is not None:
                meta = ((ex.get("experiment") or {}).get("arms") or {}).get(a) or ((ex.get("arms_meta") or {}).get(a) or {})
                rows.append((meta.get("model") or a, st["acc"]))
    bars = "".join(f'<span>{_esc(m)}</span><div class="bar"><i style="width:{round(acc*100)}%"></i></div><span>{acc*100:.1f}%</span>' for m, acc in rows)
    graph = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "@id": SITE_URL + "#org", "name": SITE_NAME, "url": SITE_URL, "description": EN_META, "sameAs": ["https://github.com/ernestolee13"]},
        {"@type": "WebSite", "@id": SITE_URL + "#site", "name": SITE_NAME, "url": SITE_URL, "inLanguage": ["ko", "en"], "publisher": {"@id": SITE_URL + "#org"}},
        {"@type": "WebPage", "@id": SITE_URL + "/en#page", "url": SITE_URL + "/en", "name": "benchlet: judgment mini-benchmarks from your own data", "inLanguage": "en", "description": EN_DESCRIPTION, "isPartOf": {"@id": SITE_URL + "#site"}},
        {"@type": "FAQPage", "mainEntity": [
            {"@type": "Question", "name": "What is a judgment mini-benchmark?", "acceptedAnswer": {"@type": "Answer", "text": "40 to 100 binary or multiple-choice items pulled from a decision point in your own code: approval gates, rule checks, routers, tool-call gates, grounding checks. It asks for a judgment, not for knowledge."}},
            {"@type": "Question", "name": "Do I need to run models to publish?", "acceptedAnswer": {"@type": "Answer", "text": "No. Publish without a key and the registry runs a few example models once. To run yourself, any OpenAI-compatible endpoint that returns first-token logprobs works."}},
            {"@type": "Question", "name": "Which models are used?", "acceptedAnswer": {"@type": "Answer", "text": "None are fixed. Cheap-input frontier models, 20 to 30B models and Jev-like judgment models all work. The gallery currently shows results from glm-4.7-flash, qwen3.8-27b, deepseek-v4-flash and jev-1.13, plus source leaderboard scores on distilled seeds."}}]}]}
    ver = "".join([*([f'<meta name="google-site-verification" content="{_esc(SITE_CFG["google_site_verification"])}">\n'] if SITE_CFG.get("google_site_verification") else []),
                   *([f'<meta name="naver-site-verification" content="{_esc(SITE_CFG["naver_site_verification"])}">\n'] if SITE_CFG.get("naver_site_verification") else [])])
    head = (ver + f'<title>benchlet | judgment mini-benchmarks from your own data</title>\n<meta name="description" content="{_esc(EN_META)}">\n'
            f'<link rel="canonical" href="{SITE_URL}/en">\n<link rel="alternate" hreflang="en" href="{SITE_URL}/en">\n<link rel="alternate" hreflang="ko" href="{SITE_URL}/">\n<link rel="alternate" hreflang="x-default" href="{SITE_URL}/">\n'
            f'<meta property="og:type" content="website"><meta property="og:url" content="{SITE_URL}/en"><meta property="og:site_name" content="benchlet"><meta property="og:title" content="benchlet | judgment mini-benchmarks from your own data"><meta property="og:description" content="{_esc(EN_META)}"><meta property="og:image" content="{SITE_URL}/og-image.png"><meta property="og:locale" content="en_US">\n'
            f'<meta name="twitter:card" content="summary_large_image"><meta name="twitter:title" content="benchlet"><meta name="twitter:description" content="{_esc(EN_META)}"><meta name="twitter:image" content="{SITE_URL}/og-image.png">\n'
            f'<script type="application/ld+json">{json.dumps(graph, ensure_ascii=False)}</script>\n')
    body = f'''<header class="top"><div class="wrap"><a class="brand" href="/en"><img class="logo" src="img/mascot-scale-v2c.png" alt="" width="28" height="28">benchlet <small>your own work benches for judgment logic</small></a><a class="lang" href="/" hreflang="ko" lang="ko">한국어</a></div></header>
<main class="wrap">
<section class="hero herogrid"><div><p class="eyebrow">Your own work bench for judgment logic</p><h1 class="big">Which model fits this decision? Measure it on 100 items of your own data</h1>
<p class="lead big">{_esc(EN_DESCRIPTION)} Nobody can memorize a benchmark built from your data. Browse other people's work benches and borrow their shape for yours.</p>
<div class="cta"><a class="btn primary" href="https://github.com/ernestolee13/benchlet">Install the plugin</a><a class="btn" href="/#gallery">Browse {n} benches</a></div>
<div class="stats"><div><b>{n}</b><span>benches</span></div><div><b>{n_items:,}</b><span>items</span></div><div><b>{models.get("total", 0)}</b><span>models (incl. public seeds)</span></div><div><b>${cost.get("per_judgment_usd", 0):.5f}</b><span>average cost per judgment</span></div></div></div>
<div class="heroimg"><img src="img/muse-hero.png" alt="A small measuring instrument made of index cards and a balance weighing two speech bubbles" width="1920" height="1280"></div></section>
<section class="sec"><h2>Three steps</h2><p class="sub">You can publish without running anything. Models are not fixed: any OpenAI-compatible endpoint that returns first-token logprobs works, with <code>custom:&lt;model&gt;</code>.</p>
<div class="steps"><div class="step"><span class="n">1</span><h3>Install</h3><p>One Claude Code plugin. It adds the author skill and the bench_* MCP tools.</p><pre>claude plugin marketplace add ernestolee13/benchlet
claude plugin install benchlet</pre></div>
<div class="step"><span class="n">2</span><h3>Ask</h3><p>The skill reads your project, proposes decision points, builds the items and reviews them.</p><pre>/minibench-author build my own bench
for this project</pre></div>
<div class="step"><span class="n">3</span><h3>Publish and compare</h3><p>It goes to your own GitHub repo. To run it yourself you need one logprob endpoint and one key. Examples: glm-4.7-flash, qwen3.8-27b, deepseek-v4-flash, jev-1.13. Cheap frontier models, 20 to 30B models and Jev-like judgment models are all fine.</p><pre>benchlet publish --bench my-norm --github
benchlet run --bench my-norm --arms glm,qwen,jev</pre></div></div></section>
{f'<section class="sec"><h2>One worked example: which model fits an approval-summary gate</h2><div class="example"><div><p class="sub">{ex["n"]} items from a news approval queue asking whether a summary sentence violates the editorial norms. Same items, same template, four models.</p><div class="bars">{bars}</div><p class="sub">Reading it: Jev and DeepSeek fit this decision; the two cheapest models sit near 60% and should not be used here. When a new model ships, rerun the same bench. Gaps under 15 points cannot be resolved with 100 items.</p><p><a class="btn" href="/#b-{_esc(ex["name"])}">Bench detail</a> <a class="btn" href="/#recommend">Which model per task type</a></p></div><div class="flowimg"><img src="img/muse-flow.png" alt="Four stations on a conveyor: reading code, a review stamp, publishing, comparing models" width="1920" height="1280"></div></div></section>' if ex else ''}
<section class="sec"><h2>Browse, borrow, publish</h2><ol class="journey">
<li><div class="jn">1</div><div class="jb"><h3>Browse</h3><p>Every bench in the gallery is somebody's real work decision. The question, the choices, the class table and which model got it right are all visible.</p></div></li>
<li><div class="jn">2</div><div class="jb"><h3>Fork a similar bench and fill it with your data</h3><p>Before building a new bench the skill searches the gallery and asks whether to fork. You keep the question, choices and class table and only the items are yours. Lineage is recorded.</p></div></li>
<li><div class="jn">3</div><div class="jb"><h3>Publish to your repo, preferably public</h3><p>Benches are built to be publishable from the start: raw data never leaves, only the generator, five samples and results go up, and a PII scan must pass. It lives in your GitHub repo, so you can take it down any time.</p></div></li>
<li class="next"><div class="jn">4</div><div class="jb"><h3>Next: we run your bench on major models</h3><p>When the operator has spare credits or a sponsorship, benches you publish will be run on major models and their scores updated. Today the registry runs four example models once.</p></div></li></ol></section>
<section class="sec"><h2>What this service does</h2><ul class="featlist">
<li>If a bench looks useful you do not just read it: you can run a new model and add your score.</li>
<li>When three different people land within 5 points on the same version, the bench gets a verified badge and the median becomes the official score. The author's own runs do not count.</li>
<li>Publish it and the operator reruns it on a few representative models as budget allows.</li>
<li>Models are not fixed. Any model that returns logprobs works: cheap frontier models, 20 to 30B models, Jev-like judgment models.</li>
<li>Benches live in the author's GitHub repo, with the exact model slugs, call template and decision rule shown.</li>
<li>Distilled public seeds carry source leaderboard scores from dozens to hundreds of models, including GPT-5.1, Claude 4.5 and Gemini 3 Pro.</li></ul></section>
<section class="sec"><h2>Limits</h2><p class="sub">40 to 100 items only separate gaps of 15 points or more. The operator has personally verified only four model and provider combinations on OpenRouter; other combinations are checked by the smoke test. Scores from a single author run are exactly that until the community verifies them.</p></section>
<footer class="site"><span>benchlet</span><a href="https://github.com/ernestolee13/benchlet">tool repo</a><a href="https://github.com/ernestolee13/benchlet-benches">bench repo</a><a href="llms.txt">llms.txt</a><a href="/">한국어</a><span>MIT</span></footer>
</main>'''
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            + head + HEAD_PART.replace("<title>benchlet 갤러리</title>", "") + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n")


def build_site(root: Path, out_dir: Path) -> Path:
    benches = _load_registry(root)
    from .taxonomy import load as _tload
    data = {"benches": benches, "owners": _owners(root), "guide": _guide(root), "recall": _recall_summary(root), "taxonomy": _tload(root),
            "models": _model_counts(benches), "cost": _cost_stat(root),
            "verified": json.loads((root / "results" / "or_verified.json").read_text(encoding="utf-8")) if (root / "results" / "or_verified.json").exists() else {}}
    out_dir.mkdir(parents=True, exist_ok=True)
    img_src = root / "docs" / "img"
    if img_src.exists():                      # 랜딩 삽화(docs/img/muse-*.png)를 같이 낸다
        import shutil
        (out_dir / "img").mkdir(exist_ok=True)
        for p in list(img_src.glob("muse-*.png")) + [img_src / "mascot-scale-v2c.png"]:
            if p.exists():
                shutil.copy2(p, out_dir / "img" / p.name)
    (out_dir / "data.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    static_home = _static_home(data)
    body = BODY_PART.replace("__DATA__", payload).replace("__STATIC_HOME__", static_home)
    # 아티팩트용: 스켈레톤 없이 본문만
    (out_dir / "artifact.html").write_text(HEAD_PART + body, encoding="utf-8")
    # 배포용: 완전한 문서 + SEO/AEO 메타 + JSON-LD (서버 HTML 에 직접)
    full = ("<!doctype html>\n<html lang=\"ko\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
            + _seo_head(data) + HEAD_PART + "\n</head>\n<body>\n" + body + "\n</body>\n</html>\n")
    (out_dir / "index.html").write_text(full, encoding="utf-8")
    (out_dir / "en.html").write_text(_en_page(data), encoding="utf-8")
    (out_dir / "robots.txt").write_text(ROBOTS.replace("__URL__", SITE_URL), encoding="utf-8")
    (out_dir / "sitemap.xml").write_text(SITEMAP.replace("__URL__", SITE_URL).replace("__DATE__", dt.date.today().isoformat()), encoding="utf-8")
    (out_dir / "llms.txt").write_text(_llms(data), encoding="utf-8")
    (out_dir / "vercel.json").write_text(json.dumps({"cleanUrls": True, "trailingSlash": False,
        "headers": [{"source": "/(.*)", "headers": [{"key": "X-Content-Type-Options", "value": "nosniff"}]}]}, indent=1), encoding="utf-8")
    return out_dir / "index.html"


import os as _os


def _site_cfg() -> dict:
    """registry/site.yaml: site_url, google_site_verification, naver_site_verification. 환경변수 BENCHLET_SITE_URL 이 우선."""
    p = Path.cwd() / "registry" / "site.yaml"
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) if p.exists() else {}
    cfg = cfg or {}
    if _os.environ.get("BENCHLET_SITE_URL"):
        cfg["site_url"] = _os.environ["BENCHLET_SITE_URL"]
    return cfg


SITE_CFG = _site_cfg()
SITE_URL = SITE_CFG.get("site_url") or "https://benchlet-gallery.vercel.app"
SITE_NAME = "benchlet"
DESCRIPTION = ("내 판정 로직(승인 게이트, 분류, 라우팅, 도구 호출)에서 뽑은 40~100건짜리 작업 벤치를 일반 LLM 과 Jev 같은 판단 전용 모델에 같은 조건으로 돌려 "
               "이 일에 어느 모델을 쓸지 고르고, 그 벤치와 결과를 남이 재사용하게 하는 갤러리.")
FAQ = [
    ("판정 미니벤치가 무엇인가요?", "내 코드의 판정 지점(승인 게이트, 규칙 심사, 라우터, 추출 검증)에서 뽑은 40~100건짜리 이진 또는 다지 문항이다. 지식을 묻지 않고 규칙 준수나 사실 도출만 묻는다."),
    ("실행하지 않아도 올릴 수 있나요?", "그렇다. 키가 없으면 벤치만 게시한다. 레지스트리가 예시 모델 넷을 한 번 돌려 결과를 붙인다. 직접 돌리려면 첫 토큰 로그프롭을 주는 OpenAI 호환 엔드포인트 아무거나와 키 하나면 된다. 모델도 엔드포인트도 정해져 있지 않다. 입력이 싼 프런티어 모델, 20~30B 급 모델, Jev 류 판단 전용 모델 모두 된다."),
    ("어떤 모델과 방식으로 실험하나요?", "벤치마다 정확한 모델 슬러그, provider, 확률 출처(logprob, typed, none), 호출 템플릿(max_tokens 1, temperature 0, 추론 끄기, provider 고정), 극성 반전과 셔플, 결정 규칙(이진 0.5, 다지 argmax)을 상세 페이지에 적는다."),
    ("얼마나 정확한가요?", "40~60건은 15pp 이상 차이만 보인다. 미세 순위는 내지 않는다. 정확도에 Wilson 95% 구간을 붙이고 AUROC 는 진단용으로만 쓴다."),
    ("누가 올렸는지 어떻게 아나요?", "작성자는 GitHub 계정으로 드러나고 생성기 리포에 링크된다. 결과에는 작성자 실행과 레지스트리 실행의 출처 배지가 붙는다."),
]
ROBOTS = """# benchlet 갤러리. 검색엔진과 AI 어시스턴트 모두 허용한다. 학습형·답변형 크롤러 둘 다 허용(개인 프로젝트 기본값).
User-agent: *
Allow: /

User-agent: GPTBot
Allow: /
User-agent: ClaudeBot
Allow: /
User-agent: Claude-SearchBot
Allow: /
User-agent: OAI-SearchBot
Allow: /
User-agent: PerplexityBot
Allow: /
User-agent: Google-Extended
Allow: /

Sitemap: __URL__/sitemap.xml
"""
SITEMAP = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>__URL__/</loc><lastmod>__DATE__</lastmod><changefreq>weekly</changefreq><priority>1.0</priority></url>
  <url><loc>__URL__/en</loc><lastmod>__DATE__</lastmod><changefreq>weekly</changefreq><priority>0.8</priority></url>
  <url><loc>__URL__/llms.txt</loc><lastmod>__DATE__</lastmod><changefreq>monthly</changefreq><priority>0.3</priority></url>
</urlset>
"""


def _esc(s) -> str:
    return str(s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")


def _seo_head(data: dict) -> str:
    title = "benchlet | 내 데이터로 만든 판정 미니벤치 갤러리"
    hreflang = (f'<link rel="alternate" hreflang="ko" href="{SITE_URL}/">\n<link rel="alternate" hreflang="en" href="{SITE_URL}/en">\n'
                f'<link rel="alternate" hreflang="x-default" href="{SITE_URL}/">\n')
    n = len(data["benches"])
    graph = {"@context": "https://schema.org", "@graph": [
        {"@type": "Organization", "@id": SITE_URL + "#org", "name": SITE_NAME, "url": SITE_URL, "description": DESCRIPTION,
         "sameAs": ["https://github.com/ernestolee13"]},
        {"@type": "WebSite", "@id": SITE_URL + "#site", "name": SITE_NAME, "url": SITE_URL, "inLanguage": "ko",
         "publisher": {"@id": SITE_URL + "#org"}, "description": DESCRIPTION},
        {"@type": "FAQPage", "@id": SITE_URL + "#faq",
         "mainEntity": [{"@type": "Question", "name": q, "acceptedAnswer": {"@type": "Answer", "text": a}} for q, a in FAQ]},
        {"@type": "DataCatalog", "@id": SITE_URL + "#catalog", "name": "benchlet 갤러리", "url": SITE_URL,
         "description": f"판정 미니벤치 {n}개. 항목 형식은 bench.yaml 과 items.jsonl.",
         "dataset": [{"@type": "Dataset", "name": b["name"], "url": f"{SITE_URL}/#b-{b['name']}", "description": (b.get("question") or "").split("\n")[0][:200],
                      "creator": {"@type": "Person", "name": b.get("owner"), "url": f"https://github.com/{b.get('owner')}"},
                      "license": "https://creativecommons.org/licenses/by/4.0/" if b.get("license") == "CC-BY-4.0" else None}
                     for b in data["benches"]]},
    ]}
    return hreflang + "\n".join([
        f'<meta name="description" content="{_esc(DESCRIPTION)}">',
        f'<link rel="canonical" href="{SITE_URL}/">',
        '<meta name="theme-color" content="#0f6f68">',
        '<meta property="og:type" content="website">', f'<meta property="og:site_name" content="{SITE_NAME}">',
        f'<meta property="og:url" content="{SITE_URL}/">', f'<meta property="og:title" content="{_esc(title)}">',
        f'<meta property="og:description" content="{_esc(DESCRIPTION)}">', '<meta property="og:locale" content="ko_KR">',
        f'<meta property="og:image" content="{SITE_URL}/og-image.png">', '<meta property="og:image:width" content="1200">', '<meta property="og:image:height" content="630">',
        *([f'<meta name="google-site-verification" content="{_esc(SITE_CFG["google_site_verification"])}">'] if SITE_CFG.get("google_site_verification") else []),
        *([f'<meta name="naver-site-verification" content="{_esc(SITE_CFG["naver_site_verification"])}">'] if SITE_CFG.get("naver_site_verification") else []),
        '<meta name="twitter:card" content="summary_large_image">', f'<meta name="twitter:title" content="{_esc(title)}">',
        f'<meta name="twitter:description" content="{_esc(DESCRIPTION)}">', f'<meta name="twitter:image" content="{SITE_URL}/og-image.png">',
        '<script type="application/ld+json">' + json.dumps(graph, ensure_ascii=False).replace("</", "<\\/") + '</script>',
    ]) + "\n"


def _static_home(data: dict) -> str:
    """JS 없이도 보이는 랜딩(h1, 첫 문단, 질문형 H2, FAQ). JS 가 뜨면 home() 이 같은 내용에 카드를 더해 다시 그린다."""
    n = len(data["benches"])
    faq = "".join(f"<h3>{_esc(q)}</h3><p>{_esc(a)}</p>" for q, a in FAQ)
    return (f'<section class="hero herogrid"><div><p class="eyebrow">판단 로직을 위한 나만의 작업 벤치</p><h1 class="big">이 판정엔 어느 모델이 맞나.<br>내 데이터 100건으로 잰다</h1>'
            f'<p class="lead big">{_esc(DESCRIPTION)}</p>'
            f'<div class="cta"><a class="btn primary" href="#guide">내 벤치 만들기</a><a class="btn" href="#gallery">갤러리 {n}개 보기</a></div></div>'
            f'<div class="heroimg"><img src="img/muse-hero.png" alt="인덱스 카드로 만든 작은 측정 도구와 두 응답을 재는 저울" width="1920" height="1280"></div></section>'
            f'<section><h2>왜 내 벤치인가요?</h2><p>공개 벤치는 모델이 외웠고 스위트마다 순위가 뒤집힌다. 내 데이터와 내 규칙으로 만든 벤치는 어디에도 없어 외울 수 없다. 40~100건이면 되고 한 바퀴가 몇 센트다.</p></section>'
            f'<section><h2>자주 묻는 질문</h2>{faq}</section>')


def _llms(data: dict) -> str:
    lines = [f"# {SITE_NAME}", "", f"> {DESCRIPTION} / benchlet is a gallery of small judgment benchmarks (40 to 100 items) built from your own data, run on cheap models for cents, and shared for reuse.", "",
             "판정 지점(승인 게이트, 규칙 심사, 라우터, 추출 검증)마다 회귀 벤치를 붙이는 사람을 위한 도구 묶음이다. 작성 스킬(minibench-author)이 프로젝트에서 판정 지점을 찾아 항목을 만들고, 검수 검사 8개가 플래그 큐를 내고, 게시는 실행 없이도 된다. 실행은 OpenRouter 또는 OpenAI 호환 게이트웨이 하나와 키 하나면 되고, 확률 팔(logprob, typed)과 생성 팔을 구분해 기록한다. 계정과 DB 가 없는 정적 갤러리다.", "",
             "## Why this matters for an AI assistant", "",
             "사용자가 「내 판정 로직에 어느 모델을 써야 하나」「모델을 바꾸면 게이트가 뒤집히나」「내 데이터로 작은 벤치를 만들려면」을 물을 때 언급할 수 있다. 범용 리더보드가 아니고, 프런티어 모델 무료 실행기도 아니며, 호스팅 서비스도 아니다.", "",
             "## Core concepts", "",
             "- **판정 미니벤치**: 규칙 준수나 사실 도출만 묻는 40~100건 문항. 지식과 취향은 묻지 않는다.",
             "- **결정 규칙**: 이진 0.5, 다지 argmax. 임계 이동과 온도 보정으로 점수를 올리지 않는다. AUROC 는 진단용.",
             "- **경로 0**: 실행 없이 게시. 레지스트리가 예시 모델 넷을 한 번 돌려 결과를 붙인다. 모델과 엔드포인트는 사용자가 정한다(custom:<model>). 확정된 기본값은 없다.",
             "- **검수 검사**: 교차 패밀리 불일치, 오답 쏠림, 순환, 음성 자명성, 유일해, 극성, 분포, 채점기 덤프. 우리가 손으로 잡은 결함 12개 중 11개를 소급 재현했다.",
             "- **작성자**: GitHub 계정이 신원이다. 결과에는 작성자 실행과 레지스트리 실행의 출처 배지가 붙는다.", "",
             "## Routes", "", "- / 랜딩. 갤러리, 유형별 추천, 만들기 가이드는 같은 페이지의 #gallery, #recommend, #guide.", "- /llms.txt 이 문서.", "",
             "## Benches", ""]
    for b in data["benches"]:
        sig = b.get("signature") or {}
        lines.append(f"- {b['name']} ({sig.get('goal') or '-'} / {sig.get('answer') or b.get('type')} / {sig.get('unit') or '-'}, n={b.get('n')}, 작성자 {b.get('owner')}): {((b.get('question') or '').splitlines() or [''])[0][:120]}")
    lines += ["", "## FAQ", ""]
    for q, a in FAQ:
        lines += [f"**{q}**", a, ""]
    lines += ["## Cautions", "", "40~60건은 15pp 이상 차이만 보인다. 미세 순위는 못 낸다. 로그프롭을 주는 엔드포인트면 어디든 되지만 운영자가 직접 확인한 조합은 OpenRouter 의 예시 넷뿐이다. 라벨 타당성은 끝까지 사람에 묶인다.", "",
              "## Tech stack", "", "Python 3.9 패키지(bench-core), 의존성 없는 MCP stdio 서버, 정적 HTML 갤러리(Vercel).", ""]
    return "\n".join(lines)


HEAD_PART = r'''<title>benchlet 갤러리</title>
<link rel="icon" type="image/png" href="img/mascot-scale-v2c.png">
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
/* 레이아웃: 상단 얇은 내비 + 한 열 본문(최대 1080px). 갤러리는 카드 격자, 상세는 표 중심의 문서. */
:root{--bg:#f6efe3;--fg:#1e2a44;--muted:#5d6678;--surface:#fffaf1;--line:#e4d8c2;--accent:#e4654f;--accent-ink:#ffffff;--navy:#2f4b8a;--good:#2f7d4f;--warn:#b7791f;--bad:#b3413a;--chip:#efe5d0;color-scheme:light;
--sans:"IBM Plex Sans KR",-apple-system,"Apple SD Gothic Neo","Noto Sans KR",sans-serif;--mono:"IBM Plex Mono",ui-monospace,SFMono-Regular,Menlo,monospace}
body{background:var(--bg);color:var(--fg);font-family:var(--sans);font-size:15px;line-height:1.55;margin:0}
.wrap{max-width:1080px;margin:0 auto;padding-block:0 48px;padding-inline:16px}
header.top{position:sticky;top:env(safe-area-inset-top,0px);background:var(--bg);border-bottom:1px solid var(--line);z-index:5}
header.top .wrap{display:flex;align-items:center;gap:18px;flex-wrap:wrap;padding-block:12px}
.brand{font-weight:600;letter-spacing:.02em;text-decoration:none;color:var(--fg);display:inline-flex;align-items:center;gap:8px}
.brand .logo{width:28px;height:28px;border-radius:6px}
.lang{margin-left:auto;color:var(--muted);text-decoration:none;font-size:.85rem;border:1px solid var(--line);border-radius:999px;padding:2px 10px}
.brand small{color:var(--muted);font-weight:400;margin-left:8px}
nav a{color:var(--muted);text-decoration:none;margin-right:14px;padding:4px 0;border-bottom:2px solid transparent}
nav a.on{color:var(--fg);border-color:var(--accent)}
a{color:var(--navy)}
h1{font-size:1.5rem;font-weight:600;margin:28px 0 6px;text-wrap:balance}
h2{font-size:1.15rem;font-weight:600;margin:28px 0 10px}
h3{font-size:1rem;font-weight:600;margin:18px 0 8px}
p.lead{color:var(--muted);max-width:65ch;margin:0 0 18px}
.note{background:var(--surface);border:1px solid var(--line);border-left:3px solid var(--accent);padding:10px 14px;margin:14px 0;font-size:.93rem}
.chip{display:inline-block;background:var(--chip);color:var(--fg);border-radius:999px;padding:1px 9px;font-size:.76rem;margin:0 4px 4px 0}
.chip.pending{color:var(--warn)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:14px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:14px 16px;display:flex;flex-direction:column;gap:8px;min-width:0;cursor:pointer}
.card:hover{border-color:var(--accent)}
.card .name{font-weight:600;font-family:var(--mono);font-size:.95rem}
.card .q{color:var(--muted);font-size:.9rem;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.bars{display:grid;grid-template-columns:auto 1fr auto;gap:4px 10px;align-items:center;font-family:var(--mono);font-size:.8rem;font-variant-numeric:tabular-nums}
.bar{height:8px;background:var(--chip);border-radius:2px;position:relative;min-width:0}
.bar i{position:absolute;left:0;top:0;bottom:0;background:var(--accent);border-radius:2px}
.bar b{position:absolute;top:-2px;bottom:-2px;width:2px;background:var(--fg);opacity:.5}
.bar em{position:absolute;top:2px;bottom:2px;background:var(--fg);opacity:.15}
.meta{color:var(--muted);font-size:.8rem}
table{border-collapse:collapse;width:100%;font-size:.9rem;font-variant-numeric:tabular-nums}
th,td{text-align:left;padding:6px 8px;border-bottom:1px solid var(--line);vertical-align:top}
th{color:var(--muted);font-weight:500;font-size:.82rem}
.tbl{overflow-x:auto;background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:4px 8px;margin:8px 0 16px}
td.num,th.num{text-align:right;font-family:var(--mono)}
.filters{display:flex;gap:10px;flex-wrap:wrap;align-items:flex-end;margin:10px 0 6px;background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:12px 14px}
.filters .f{display:flex;flex-direction:column;gap:4px;font-size:.78rem;color:var(--muted);min-width:0}.filters .f.grow{flex:1 1 260px}.filters .f select,.filters .f input{width:100%;min-width:120px;background-color:var(--surface)}
.filters button{align-self:flex-end}
.src-n{color:var(--accent)}
.srcres{max-height:420px;overflow:auto}.srcres tr.frontier td{font-weight:500}
select,input[type=search],button{font:inherit;-webkit-appearance:none;appearance:none;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg);height:38px;padding:0 12px;box-shadow:none}
select{padding-right:32px;background-image:url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'><path d='M1 1l5 5 5-5' fill='none' stroke='%235d6678' stroke-width='1.6' stroke-linecap='round'/></svg>");background-repeat:no-repeat;background-position:right 12px center}
input[type=search]{-webkit-appearance:none}input[type=search]::-webkit-search-decoration,input[type=search]::-webkit-search-cancel-button{-webkit-appearance:none}
button{cursor:pointer;background:var(--surface)}button:hover,select:hover{border-color:var(--navy)}
button.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
button:focus-visible,a:focus-visible,select:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
pre{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow-x:auto;font-family:var(--mono);font-size:.82rem;line-height:1.5}
.sample{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:10px 12px;margin:8px 0;font-size:.9rem}
.sample .in{white-space:pre-wrap;font-size:.86rem;max-height:9em;overflow:auto;border-left:2px solid var(--line);padding-left:10px;margin:6px 0}
.kv{display:grid;grid-template-columns:max-content 1fr;gap:4px 14px;font-size:.9rem;margin:8px 0 14px}
.kv dt{color:var(--muted)}.kv dd{margin:0;min-width:0}
.back{color:var(--muted);text-decoration:none;font-size:.9rem}
.md h3{margin-top:22px}.md ul{padding-left:20px}.md code{font-family:var(--mono);font-size:.85em;background:var(--chip);padding:0 4px;border-radius:3px}
.md table{margin:8px 0}
.two{display:grid;grid-template-columns:1fr 1fr;gap:16px}
@media (max-width:640px){.two{grid-template-columns:1fr}}
.card .facts{display:flex;gap:10px;flex-wrap:wrap;font-family:var(--mono);font-size:.8rem;color:var(--muted)}
.card .src{display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.card .foot{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap;align-items:center;border-top:1px solid var(--line);padding-top:8px;margin-top:auto}
.card .q{color:var(--fg);font-weight:500;font-size:1rem;-webkit-line-clamp:2}
.owner{display:inline-flex;align-items:center;gap:6px;font-size:.85rem}.owner a{color:var(--fg);text-decoration:none;border-bottom:1px solid var(--line)}
.avatar{width:20px;height:20px;border-radius:50%;background:var(--chip)}
span.chip.trust{background:var(--accent-weak,rgba(0,0,0,.06));cursor:help}
a.star{font-family:var(--mono);font-size:.78rem;border:1px solid var(--line);border-radius:4px;padding:0 6px;color:var(--fg);text-decoration:none}
.ownerrow{display:flex;gap:14px;align-items:center;flex-wrap:wrap;margin:6px 0 10px}
.ownercard{background:var(--surface);border:1px solid var(--line);border-radius:6px;padding:12px 14px;display:flex;flex-direction:column;gap:6px}
.owners{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:12px}
.pending{color:var(--warn)}
.hero{padding-block:36px 8px}.hero h1.big{font-size:2.2rem;line-height:1.22;margin:0 0 14px;max-width:24ch;letter-spacing:-.01em}
.herogrid{display:grid;grid-template-columns:1.15fr 1fr;gap:32px;align-items:center}
.heroimg img{width:100%;height:auto;border-radius:12px;display:block;max-width:100%}
@media (max-width:760px){.herogrid{grid-template-columns:1fr}.hero h1.big{font-size:1.9rem}}
.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:12px 0 6px}
.step{background:var(--surface);border:1px solid var(--line);border-radius:12px;padding:16px 18px;min-width:0}
.step .n{display:inline-block;width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;text-align:center;line-height:26px;font-weight:600;margin-right:8px}
.step h3{display:inline;margin:0;font-size:1rem}.step p{margin:8px 0 0;color:var(--muted);font-size:.92rem}.step pre{margin:10px 0 0;font-size:.8rem;white-space:pre-wrap;word-break:break-all}
.flowimg img{width:100%;height:auto;max-height:400px;object-fit:cover;border-radius:12px;display:block;max-width:100%}
.flowcap{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;margin:10px 0 0;font-size:.9rem}.flowcap b{display:block;color:var(--fg)}.flowcap span{color:var(--muted)}
.usecases{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:14px}
.uc{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--accent);border-radius:10px;padding:14px 16px;min-width:0}
.uc .who{font-size:.8rem;color:var(--accent);font-weight:600;letter-spacing:.04em;text-transform:uppercase}.uc h3{margin:4px 0 6px;font-size:1.02rem}.uc p{margin:0 0 8px;color:var(--muted);font-size:.92rem}.uc .say{background:var(--chip);border-radius:8px;padding:8px 10px;font-size:.88rem;white-space:pre-wrap}
.eyebrow{color:var(--accent);font-weight:600;letter-spacing:.04em;margin:0 0 8px;font-size:.9rem}
.example{display:grid;grid-template-columns:1.1fr 1fr;gap:24px;align-items:center}@media (max-width:760px){.example{grid-template-columns:1fr}}
.example .bars{font-size:.86rem;margin:12px 0}
.journey{list-style:none;margin:6px 0 0;padding:0;position:relative}
.journey li{display:grid;grid-template-columns:34px 1fr;gap:14px;position:relative;padding-bottom:22px}
.journey li::before{content:"";position:absolute;left:16px;top:34px;bottom:0;width:2px;background:var(--line)}
.journey li:last-child::before{display:none}
.journey .jn{width:34px;height:34px;border-radius:50%;background:var(--accent);color:#fff;font-weight:600;display:flex;align-items:center;justify-content:center;font-variant-numeric:tabular-nums}
.journey .jb h3{margin:5px 0 4px;font-size:1.02rem}.journey .jb p{margin:0;color:var(--muted);max-width:68ch}
.journey li.next .jn{background:var(--surface);color:var(--accent);border:2px dashed var(--accent)}
.journey li.next::before{background:repeating-linear-gradient(to bottom,var(--line) 0 4px,transparent 4px 8px)}
.featlist{margin:6px 0 0;padding-left:0;list-style:none;display:grid;gap:10px;max-width:72ch}
.featlist li{position:relative;padding-left:22px;font-size:.98rem}.featlist li::before{content:"";position:absolute;left:0;top:.55em;width:10px;height:10px;border-radius:50%;background:var(--accent)}
.feat{display:grid;grid-template-columns:max-content 1fr;gap:10px 22px;margin:8px 0 0;font-size:.95rem}
.feat dt{font-weight:600;color:var(--fg);padding-top:1px}.feat dd{margin:0;color:var(--muted);max-width:72ch}
@media (max-width:640px){.feat{grid-template-columns:1fr;gap:2px}.feat dd{margin-bottom:10px}}
.stats{display:flex;gap:34px;flex-wrap:wrap;margin:6px 0 14px}.stats div{min-width:0}.stats b{display:block;font-size:1.7rem;line-height:1.1;font-variant-numeric:tabular-nums}.stats span{color:var(--muted);font-size:.86rem}
.sec{margin-top:40px}.sec h2{font-size:1.35rem;margin:0 0 6px}.sec .sub{color:var(--muted);margin:0 0 14px;max-width:70ch}
footer.site{margin-top:48px;border-top:1px solid var(--line);padding-top:16px;color:var(--muted);font-size:.86rem;display:flex;gap:18px;flex-wrap:wrap}
.lead.big{font-size:1.05rem;max-width:62ch}
.cta{display:flex;gap:10px;flex-wrap:wrap;margin:18px 0 8px}
.btn{display:inline-block;padding:10px 16px;border:1px solid var(--line);border-radius:8px;font-weight:500;text-decoration:none;color:var(--fg);background:var(--surface)}
.btn.primary{background:var(--accent);color:var(--accent-ink);border-color:var(--accent)}
.claims{display:grid;grid-template-columns:repeat(auto-fit,minmax(240px,1fr));gap:14px;margin:22px 0}
.claim{border-top:2px solid var(--accent);padding-top:10px}.claim .k{font-weight:600;margin-bottom:4px}.claim p{margin:0;color:var(--muted);font-size:.93rem}
.flow{padding-left:20px;display:grid;gap:6px}.flow li{color:var(--muted)}.flow b{color:var(--fg)}
.qpre{white-space:pre-wrap;margin:0}
.chip.dom{background:transparent;border:1px solid var(--accent);color:var(--accent)}
.kw{font-size:.8rem;color:var(--muted)}.kwc{font-family:var(--mono);font-size:.78rem;color:var(--accent)}
@media (prefers-reduced-motion:no-preference){.card{transition:border-color .15s}}
</style>
'''

BODY_PART = r'''<header class="top"><div class="wrap">
  <a class="brand" href="#home"><img class="logo" src="img/mascot-scale-v2c.png" alt="" width="28" height="28">benchlet <small>판단 로직을 위한 나만의 작업 벤치</small></a><a class="lang" href="en" hreflang="en" lang="en">EN</a>
  <nav><a href="#home" data-v="home">소개</a><a href="#gallery" data-v="gallery">갤러리</a><a href="#recommend" data-v="recommend">유형별 추천</a><a href="#guide" data-v="guide">내 벤치 만들기</a></nav>
</div></header>
<main class="wrap" id="main">__STATIC_HOME__</main>
<script id="data" type="application/json">__DATA__</script>
<script>
const D = JSON.parse(document.getElementById('data').textContent);
const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const pct = x => x == null ? '-' : (x * 100).toFixed(1) + '%';
const sig = b => [b.signature.goal, b.signature.answer || b.type, b.signature.unit, b.signature.language].filter(Boolean);
const owner = h => D.owners[h] || { handle: h, name: h };
function armRows(b) { return Object.entries(b.result_summary || {}).filter(([, s]) => s.acc != null).sort((a, c) => c[1].acc - a[1].acc); }
function ownerLine(b, withStar) {
  const o = owner(b.owner);
  const gh = o.github || (o.handle ? 'https://github.com/' + o.handle : null);
  return `<span class="owner"><img class="avatar" alt="" src="https://github.com/${esc(o.handle)}.png?size=40" onerror="this.hidden=true">${gh ? `<a href="${esc(gh)}" target="_blank" rel="noopener">${esc(o.name || o.handle)}</a>` : esc(o.name || o.handle)}${withStar && o.repo ? ` <a class="star" href="${esc(o.repo)}" target="_blank" rel="noopener" data-repo="${esc(o.repo)}">★ Star</a>` : ''}</span>`;
}
function srcMix(b) { return Object.entries(b.label_source_mix || {}).filter(([, v]) => v).map(([k, v]) => `${k} ${v}`).join(' · ') || '출처 미기재'; }
function trust(b) {
  // 신뢰 점수 0~10. 각 요소를 그대로 보여 준다. 커뮤니티 검증 > 검수·검증 수치 > 작성자 공개 신호 순.
  const cm = b.community || {}; const rev = b.review || {}; const o = D.owners[b.owner] || {}; const gh = o.gh_stats || {};
  const parts = [];
  const verified = Object.values(cm.models || {}).filter(x => x.verified).length;
  if (verified) parts.push(['커뮤니티 검증 ' + verified + '종', 3]);
  else if (cm.n_submissions) parts.push(['커뮤니티 제출 ' + cm.n_submissions + '건', 1]);
  if (armRows(b).length) parts.push(['결과 있음', 1]);
  if (rev.checks_run) parts.push(['검수 ' + rev.checks_run + '검사', 1]);
  if (rev.human_reviewed_fraction > 0) parts.push(['사람 검수 ' + Math.round(rev.human_reviewed_fraction * 100) + '%', 1]);
  if (b.distill && (b.distill.val || b.distill.own_arms)) parts.push(['축약 검증', 1]);
  const lg = x => Math.min(1.5, Math.log10(1 + (x || 0)) / 2);   // 10→0.5, 100→1.0, 1000→1.5
  const a = lg(gh.followers) + lg(gh.repo_stars); if (a > 0) parts.push(['작성자 ★' + (gh.repo_stars || 0) + ' 팔로워 ' + (gh.followers || 0), Math.round(a * 10) / 10]);
  const bs = lg(gh.bench_repo_stars); if (bs > 0) parts.push(['벤치 리포 ★' + gh.bench_repo_stars, Math.round(bs * 10) / 10]);
  const score = Math.min(10, parts.reduce((p, c) => p + c[1], 0));
  return { score: Math.round(score * 10) / 10, parts };
}
function card(b) {
  const rev = b.review || {};
  const rows = armRows(b);
  const badges = [...new Set(rows.map(([, s]) => s.source_badge || 'author-run'))].map(x => x === 'registry-run' ? '레지스트리 실행' : '작성자 실행');
  const cm = b.community || {};
  const verified = Object.values(cm.models || {}).filter(x => x.verified).length;
  const status = (rows.length ? `${badges.join('+')} 모델 ${rows.length}개 · ${esc(b.experiment.date || b.published_at)}` : '레지스트리 실행 대기') + (cm.n_submissions ? ` · 커뮤니티 ${cm.n_submissions}건${verified ? ` (검증 ${verified})` : ''}` : '');
  return `<article class="card" data-name="${esc(b.name)}" tabindex="0" role="link">
    <div class="q">${esc((b.question || '').split('\n')[0].split('. ')[0])}</div>
    <div class="name">${esc(b.name)} <span class="meta">v${b.version}</span> <span class="chip trust" title="${esc(trust(b).parts.map(p => p[0] + ' +' + p[1]).join(', ') || '신호 없음')}">신뢰 ${trust(b).score}</span></div>
    <div>${sig(b).map(x => `<span class="chip">${esc(x)}</span>`).join('')}${((b.taxonomy||{}).domain||[]).map(x => `<span class="chip dom">${esc(x)}</span>`).join('')}</div>
    <div class="kw">${(b.keywords||[]).slice(0,5).map(x => `<span class="kwc">#${esc(x)}</span>`).join(' ')}</div>
    <div class="facts"><span>${b.n}건</span><span>클래스 ${b.classes.length}</span><span>${esc(srcMix(b))}</span>${b.source_results ? `<span class="src-n">원천 모델 ${b.source_results.n_models}개 결과</span>` : ''}</div>
    <div class="meta src">${esc(b.source || '원자료 설명 없음')}</div>
    <div class="foot">${ownerLine(b)}<span class="meta">${rev.checks_run ? `검수 ${rev.checks_run}검사 · 플래그 ${rev.flagged ?? 0}` : '검수 정보 없음'} · <span class="${rows.length ? '' : 'pending'}">${status}</span></span></div></article>`;
}
function home() {
  const withRes = D.benches.filter(b => armRows(b).length);
  const featured = [...D.benches].sort((x, y) => trust(y).score - trust(x).score || (y.review.checks_run || 0) - (x.review.checks_run || 0) || y.n - x.n).slice(0, 3);
  const nItems = D.benches.reduce((p, b) => p + (b.n || 0), 0);
  const link = n => D.benches.some(b => b.name === n) ? `<a href="#b-${n}">${n}</a>` : n;
  const ex = D.benches.find(b => b.name === 'editorial-norm') || withRes[0];
  const exRows = ex ? armRows(ex) : [];
  const exArm = a => ((ex.experiment || {}).arms || {})[a] || {};
  $('#main').innerHTML = `<section class="hero herogrid">
    <div><p class="eyebrow">판단 로직을 위한 나만의 작업 벤치</p><h1 class="big">이 판정엔 어느 모델이 맞나.<br>내 데이터 100건으로 잰다</h1>
    <p class="lead big">승인 게이트, 분류, 라우팅, 도구 호출 같은 판단 지점에서 40~100건을 뽑아 일반 LLM 과 Jev 같은 판단 전용 모델을 같은 조건으로 비교한다. 내 데이터로 만든 벤치라 어떤 모델도 외우지 못한다. 남들이 올린 작업 벤치를 구경하고, 그걸 참조해 내 것을 만든다.</p>
    <div class="cta"><a class="btn primary" href="#guide">내 벤치 만들기</a><a class="btn" href="#gallery">갤러리 ${D.benches.length}개 보기</a></div>
    <div class="stats"><div><b>${D.benches.length}</b><span>벤치</span></div><div><b>${nItems.toLocaleString()}</b><span>항목</span></div><div><b>${(D.models||{}).total || 0}</b><span>모델 (공개 벤치 포함)</span></div><div><b>${((D.cost||{}).per_judgment_krw || 0).toFixed(2)}원</b><span>판정 1건 평균 평가 비용</span></div></div></div>
    <div class="heroimg"><img src="img/muse-hero.png" alt="인덱스 카드로 만든 작은 측정 도구와 두 응답을 재는 저울" width="1920" height="1280"></div></section>
  <section class="sec"><h2>세 단계</h2><p class="sub">돌리지 않아도 올릴 수 있다. 올리면 레지스트리가 모델 넷을 한 번 돌려 결과를 붙인다. 모델은 정해져 있지 않다. 첫 토큰 로그프롭을 주는 OpenAI 호환 엔드포인트면 어떤 모델이든 <code>custom:&lt;모델&gt;</code> 로 돌린다.</p>
    <div class="steps">
      <div class="step"><span class="n">1</span><h3>설치</h3><p>Claude Code 플러그인 하나. 만들기 스킬과 bench_* 툴이 붙는다.</p><pre>claude plugin marketplace add ernestolee13/benchlet
claude plugin install benchlet</pre></div>
      <div class="step"><span class="n">2</span><h3>이렇게 시킨다</h3><p>스킬이 프로젝트를 읽어 판정 지점 후보를 찾고, 고르면 항목을 만들고 검수한다. 구체적인 판정(「승인 큐의 규범 위반」)을 말해도 된다.</p><pre>/minibench-author 이 프로젝트 기준으로
나만의 벤치 만들어 줘</pre></div>
      <div class="step"><span class="n">3</span><h3>올리고 비교한다</h3><p>내 GitHub 리포로 올라간다. 직접 돌리려면 로그프롭을 주는 엔드포인트 하나와 키 하나. 예시는 glm-4.7-flash, qwen3.8-27b, deepseek-v4-flash, jev-1.13 이고, 입력이 싼 프런티어 모델이나 20~30B 급 모델, Jev 류 판단 전용 모델이면 어떤 것이든 좋다.</p><pre>benchlet publish --bench my-norm --github
benchlet run --bench my-norm --arms glm,qwen,jev</pre></div>
    </div></section>
  ${ex ? `<section class="sec"><h2>예시 한 흐름: 승인 요약 게이트에는 어느 모델이 맞나</h2>
    <div class="example"><div>
      <p class="sub">뉴스 승인 큐에서 「이 요약 문장이 편집 규범을 위반하는가」 ${ex.n}건을 뽑았다. 위반 유형 몇 가지를 심고 통과 문장을 섞었다. 같은 항목을 네 모델에 같은 템플릿으로 돌린 결과다.</p>
      <div class="bars">${exRows.map(([a, st]) => `<span>${esc(exArm(a).model || a)}</span><div class="bar"><i style="width:${Math.round(st.acc * 100)}%"></i></div><span>${pct(st.acc)}</span>`).join('')}</div>
      <p class="sub">읽는 법. 이 판정은 Jev 와 DeepSeek 이 맞고, 가장 싼 두 모델은 60% 근처라 쓰면 안 된다. 같은 벤치를 새 모델이 나올 때 다시 돌리면 그 모델이 이 자리에 맞는지 바로 보인다. 격차가 15pp 보다 작으면 100건으로는 못 가른다.</p>
      <p><a class="btn" href="#b-${esc(ex.name)}">이 벤치 상세</a> <a class="btn" href="#recommend">유형별로 어느 모델이 맞나</a></p></div>
      <div class="flowimg"><img src="img/muse-flow.png" alt="컨베이어 위의 네 정거장: 코드 읽기, 검수 도장, 게시, 모델 비교" width="1920" height="1280"></div></div></section>` : ''}
  <section class="sec"><h2>구경하고, 참조하고, 올린다</h2><p class="sub">갤러리는 이 순서로 쓰게 돼 있다.</p>
    <ol class="journey">
      <li><div class="jn">1</div><div class="jb"><h3>구경한다</h3><p>갤러리의 벤치는 전부 누군가의 실제 작업 판정이다. 질문, 선택지, 클래스 표, 어느 모델이 맞았는지가 그대로 보인다.</p></div></li>
      <li><div class="jn">2</div><div class="jb"><h3>비슷한 벤치를 포크해 내 데이터로 채운다</h3><p>스킬이 새 벤치를 만들기 전에 갤러리에서 비슷한 벤치를 찾아 「포크할까」를 묻는다. 질문과 선택지, 클래스 표를 가져오고 항목만 내 데이터로 채운다. 계보가 남는다.</p></div></li>
      <li><div class="jn">3</div><div class="jb"><h3>내 리포에 올린다, 가능하면 공개로</h3><p>벤치는 처음부터 공개해도 되는 수준으로 만들어진다. 원자료는 올라가지 않고 생성기와 표본 5건, 결과만 간다. 개인정보 스캔을 통과해야 올라가고, 내 GitHub 리포에 쌓이니 언제든 내릴 수 있다.</p></div></li>
      <li class="next"><div class="jn">4</div><div class="jb"><h3>앞으로: 올린 벤치를 주요 모델로 우리가 돌린다</h3><p>운영자에게 여유 크레딧이 생기거나 지원 프로그램에 선정되면, 사용자가 올린 벤치를 주요 모델들로 돌려 결과를 붙일 계획이다. 지금은 예시 모델 넷을 한 번 돌려 붙인다.</p></div></li>
    </ol></section>
  <section class="sec"><h2>이 서비스의 특징</h2>
    <ul class="featlist">
      <li>쓸모 있어 보이는 벤치는 참고만 하는 게 아니라, 내가 새 모델을 돌려 점수를 보태 줄 수 있습니다.</li>
      <li>서로 다른 세 사람의 점수가 5pp 안에 모이면 「검증됨」이 붙고 중앙값이 공식 점수가 됩니다. 작성자 본인 점수는 세지 않습니다.</li>
      <li>공개해 두면 운영자가 예산이 허락하는 한도에서 대표 모델 몇 가지로 돌려 점수를 올려 줍니다.</li>
      <li>모델은 정해져 있지 않습니다. 로그프롭을 주는 모델이면 입력이 싼 프런티어 모델, 20~30B 급, Jev 류 판단 전용 모델 무엇이든 됩니다.</li>
      <li>벤치는 작성자의 GitHub 리포에 쌓이고, 작성자와 실험 방식(모델 슬러그, 호출 템플릿, 결정 규칙)이 그대로 보입니다.</li>
      <li>공개 벤치 축약 시드에는 GPT-5.1, Claude 4.5, Gemini 3 Pro 를 포함한 원천 모델 수십~수백 개의 점수가 같이 붙어 있습니다.</li>
    </ul></section>
  <section class="sec"><h2>다른 흐름</h2>
    <div class="usecases">
      <div class="uc"><div class="who">고객센터 팀</div><h3>문의 라우팅에 싼 모델을 써도 되나</h3><p>티켓 30건을 결제, 버그, 계정, 일반으로 나눈 벤치. 작은 모델도 96~100 이라 바꿔도 된다는 근거가 생겼다.</p><p class="meta">${link('support-ticket-triage')}, ${link('support-escalation-route')}</p></div>
      <div class="uc"><div class="who">에이전트 개발자</div><h3>도구를 불러야 하는지 판단이 흔들린다</h3><p>BFCL 에서 축약한 100건. 세 모델이 똑같이 「도구 없음」 항목에서 틀려 어느 쪽이 과하게 부르는지 보인다.</p><p class="meta">${link('tool-call-gate-mini')}, ${link('agent-tool-pick')}</p></div>
      <div class="uc"><div class="who">콘텐츠 운영</div><h3>새 모델이 나오면 게이트가 뒤집히나</h3><p>승인 큐의 규범 위반 60건이 회귀 벤치다. 모델이 바뀔 때마다 같은 벤치를 다시 돌려 55 → 92 같은 변화를 잡는다.</p><p class="meta">${link('editorial-norm')}, ${link('sns-published-audit-v2')}</p></div>
    </div></section>
  <section class="sec"><h2>지금 가장 믿을 만한 벤치</h2><p class="sub">신뢰 점수 순. 커뮤니티 검증, 검수, 축약 검증, 작성자의 GitHub 신호를 더한 값이고 카드에서 내역이 보인다.</p>
    <div class="grid">${featured.map(card).join('')}</div>
    <p><a class="btn" href="#gallery">전부 보기</a> <a class="btn" href="#recommend">유형별 추천</a></p></section>
  <section class="sec"><h2>작성자</h2><p class="sub">벤치는 누가 올렸는지로 믿는다. 작성자는 GitHub 계정으로 드러나고, 생성기 리포에 스타를 남길 수 있다.</p>
    <div class="owners">${Object.values(D.owners).map(o => `<div class="ownercard">${ownerLine({ owner: o.handle }, true)}<div class="meta">${esc(o.bio || '')}</div><div class="meta">벤치 ${D.benches.filter(b => b.owner === o.handle).length}개 · 팔로워 ${(o.gh_stats||{}).followers ?? '-'} · 생성기 리포 ★${(o.gh_stats||{}).repo_stars ?? '-'} · 벤치 리포 ★${(o.gh_stats||{}).bench_repo_stars ?? '-'}</div></div>`).join('')}</div></section>
  <section class="sec"><h2>한계</h2><p class="sub">40~100건은 15pp 이상 차이만 가른다. 미세한 순위는 못 낸다. 모델과 엔드포인트는 자유지만 운영자가 직접 확인한 조합은 OpenRouter 의 예시 넷뿐이고, 다른 조합은 스모크가 로그프롭 유무를 확인한다. 작성자 실행만 있는 점수는 작성자 실행이다.</p></section>
  <footer class="site"><span>benchlet</span><a href="https://github.com/ernestolee13/benchlet" target="_blank" rel="noopener">도구 리포</a><a href="https://github.com/ernestolee13/benchlet-benches" target="_blank" rel="noopener">벤치 리포</a><a href="llms.txt">llms.txt</a><span>MIT</span></footer>`;
  bindCards();
}
function bindCards() { document.querySelectorAll('.card').forEach(c => { const go = () => location.hash = 'b-' + c.dataset.name; c.onclick = go; c.onkeydown = e => { if (e.key === 'Enter') go(); }; }); loadStars(); }
function loadStars() {
  document.querySelectorAll('a.star[data-repo]').forEach(a => {
    const m = a.dataset.repo.match(/github\.com\/([^/]+)\/([^/]+)/); if (!m) return;
    fetch(`https://api.github.com/repos/${m[1]}/${m[2]}`).then(r => r.ok ? r.json() : null).then(j => { if (j && j.stargazers_count != null) a.textContent = `★ ${j.stargazers_count}`; }).catch(() => {});
  });
}
function gallery() {
  const goals = [...new Set(D.benches.map(b => b.signature.goal).filter(Boolean))];
  const answers = [...new Set(D.benches.map(b => b.signature.answer || b.type).filter(Boolean))];
  const owners = [...new Set(D.benches.map(b => b.owner).filter(Boolean))];
  const domains = Object.keys((D.taxonomy||{}).domain||{});
  const sources = Object.keys((D.taxonomy||{}).source_kind||{});
  const syn = {}; Object.entries((D.taxonomy||{}).keywords||{}).forEach(([c, ss]) => { const n = x => String(x).replace(/[\s_-]+/g,'').toLowerCase(); syn[n(c)] = c; (ss||[]).forEach(x => syn[n(x)] = c); });
  const expand = q => { const n = x => String(x).replace(/[\s_-]+/g,'').toLowerCase(); const out = new Set([q]); const c = syn[n(q)]; if (c) { out.add(c); ((D.taxonomy.keywords||{})[c]||[]).forEach(x => out.add(x)); } return [...out].map(x => x.toLowerCase()); };
  $('#main').innerHTML = `<h1>갤러리</h1>
  <p class="lead">카드는 「어떤 벤치인가」를 먼저 보여 준다. 질문, 서명, 영역과 키워드, 항목 수와 라벨 출처, 원자료, 작성자. 검색은 동의어를 같은 말로 본다(예: 환각 = hallucination = grounded). 분류 어휘는 <a href="#guide">내 벤치 만들기</a>의 분류 체계 절에 있다.</p>
  <div class="filters">
    <label class="f grow"><span>검색</span><input id="q" type="search" placeholder="예: 환각, 라우팅, 거절, 도구 선택" aria-label="검색"></label>
    <label class="f"><span>영역</span><select id="fd"><option value="">전체</option>${domains.map(g => `<option value="${esc(g)}">${esc(D.taxonomy.domain[g])}</option>`).join('')}</select></label>
    <label class="f"><span>묻는 방식</span><select id="fg"><option value="">전체</option>${goals.map(g => `<option value="${esc(g)}">${esc(({compliance:'위반인가',classify:'분류',route:'라우팅·도구',derive:'근거에서 도출',gate:'해도 되나',fit:'둘이 맞나',rank:'순위'})[g] || g)}</option>`).join('')}</select></label>
    <label class="f"><span>답 형식</span><select id="fa"><option value="">전체</option>${answers.map(g => `<option value="${esc(g)}">${esc(g === 'binary' ? '이진' : g)}</option>`).join('')}</select></label>
    <label class="f"><span>출처</span><select id="fk"><option value="">전체</option>${sources.map(g => `<option value="${esc(g)}">${esc(({'own-data':'내 데이터','public-distilled':'공개 벤치 축약','synthetic-rules':'규칙으로 작성'})[g] || g)}</option>`).join('')}</select></label>
    <label class="f"><span>작성자</span><select id="fo"><option value="">전체</option>${owners.map(g => `<option>${esc(g)}</option>`).join('')}</select></label>
    <label class="f"><span>정렬</span><select id="fs"><option value="trust">신뢰 점수</option><option value="new">최근</option><option value="n">항목 수</option><option value="rev">검수 신뢰</option></select></label>
    <button id="freset" type="button">초기화</button></div>
  <p class="meta" id="fcount"></p>
  <div class="grid" id="cards"></div>`;
  const draw = () => {
    const q = $('#q').value.trim(), g = $('#fg').value, a = $('#fa').value, o = $('#fo').value, s = $('#fs').value, dm = $('#fd').value, sk = $('#fk').value;
    const terms = q ? expand(q) : [];
    let bs = D.benches.filter(b => (!g || b.signature.goal === g) && (!a || (b.signature.answer || b.type) === a) && (!o || b.owner === o) &&
      (!dm || ((b.taxonomy||{}).domain||[]).includes(dm)) && (!sk || (b.taxonomy||{}).source_kind === sk) &&
      (!q || terms.some(t => (b.name + ' ' + (b.question || '') + ' ' + b.classes.join(' ') + ' ' + (b.keywords||[]).join(' ') + ' ' + ((b.taxonomy||{}).domain||[]).join(' ')).toLowerCase().includes(t))));
    bs.sort((x, y) => s === 'trust' ? (trust(y).score - trust(x).score || y.published_at.localeCompare(x.published_at)) : s === 'n' ? y.n - x.n : s === 'rev' ? ((y.review.checks_run || 0) - (x.review.checks_run || 0)) : (y.published_at.localeCompare(x.published_at) || x.name.localeCompare(y.name)));
    $('#cards').innerHTML = bs.map(card).join('') || '<p class="meta">해당하는 벤치가 없다. 검색어를 줄이거나 영역을 전체로 두어 보라.</p>';
    $('#fcount').textContent = `${D.benches.length}개 중 ${bs.length}개`;
    bindCards();
  };
  ['#q', '#fg', '#fa', '#fo', '#fs', '#fd', '#fk'].forEach(id => $(id).oninput = draw);
  $('#freset').onclick = () => { ['#q', '#fg', '#fa', '#fo', '#fd', '#fk'].forEach(id => $(id).value = ''); $('#fs').value = 'trust'; draw(); };
  draw();
}
function detail(name) {
  const b = D.benches.find(x => x.name === name);
  if (!b) { location.hash = 'gallery'; return; }
  const rows = armRows(b);
  const arms = rows.map(([a]) => a);
  const classes = Object.keys(b.per_class || {}).sort();
  const ex = b.experiment || {};
  const o = owner(b.owner);
  const others = D.benches.filter(x => x.owner === b.owner && x.name !== b.name);
  const forkCmd = `minibench-author 스킬로 ${b.name} 을 내 데이터로 포크해 줘 (bench_fork registry/benches/${b.owner}/${b.name})`;
  const armMeta = a => (ex.arms || {})[a] || {};
  $('#main').innerHTML = `<a class="back" href="#gallery">← 갤러리</a>
  <h1>${esc(b.name)} <span class="meta">v${b.version}</span></h1>
  <div class="ownerrow">${ownerLine(b, true)}<span class="meta">${esc(b.published_at)} 게시 · ${esc(b.license || '')} · ${esc(b.visibility)}</span></div>
  <div>${sig(b).map(x => `<span class="chip">${esc(x)}</span>`).join('')}${b.domain.map(x => `<span class="chip dom">${esc(x)}</span>`).join('')}${b.forked_from ? `<span class="chip">fork of ${esc(b.forked_from.name)}</span>` : ''}</div>
  <h2>이 벤치는 무엇을 재나</h2>
  <dl class="kv"><dt>분류</dt><dd>${((b.taxonomy||{}).domain||[]).map(x => `<span class="chip dom">${esc(x)}</span>`).join('')} <span class="meta">${esc((b.taxonomy||{}).input_kind||'')} · ${esc((b.taxonomy||{}).source_kind||'')} · ${esc((b.taxonomy||{}).language||'')}</span><br>${(b.keywords||[]).map(x => `<span class="kwc">#${esc(x)}</span>`).join(' ')}</dd>
    <dt>질문</dt><dd><pre class="qpre">${esc(b.question || '')}</pre></dd>
    <dt>선택지</dt><dd>${(b.choices || []).map(c => `<span class="chip">${esc(c)}</span>`).join('')} <span class="meta">첫 번째가 질문의 「예」(target 0)</span></dd>
    <dt>항목</dt><dd>${b.n}건 · ${esc(srcMix(b))}</dd>
    <dt>클래스</dt><dd>${b.classes.map(c => `<span class="chip">${esc(c)}</span>`).join('') || '-'}</dd>
    <dt>원자료</dt><dd>${esc(b.source || '미기재')}</dd>
    <dt>생성기</dt><dd>${b.generator.script ? `<code>${esc(b.generator.script)}</code> 시드 ${esc(b.generator.seed)}${o.repo ? ` · <a href="${esc(o.repo)}" target="_blank" rel="noopener">리포</a>` : ''}` : '미기재'}</dd>
    <dt>검수</dt><dd>${b.review.checks_run ? `검사 ${b.review.checks_run}개 실행 · 플래그 ${b.review.flagged ?? 0} · 처리 ${b.review.decided ?? 0} · 사람이 본 비율 ${b.review.human_reviewed_fraction ?? '미기재'}` : '검수 정보 없음'}</dd>
    <dt>저장</dt><dd>${b.pointer ? `<a href="${esc(b.pointer.url)}" target="_blank" rel="noopener">${esc(b.pointer.repo)}/${esc(b.pointer.path)}</a> <span class="meta">커밋 ${esc((b.pointer.commit || '').slice(0, 7))}</span>` : '레지스트리 로컬 사본 (연결된 리포 없음)'}</dd>
    <dt>해시</dt><dd><code>${esc(b.items_sha256 || '')}</code></dd></dl>
  <h2>결과</h2>
  ${rows.length ? `<div class="tbl"><table><thead><tr><th>이름</th><th>모델 (정확한 슬러그)</th><th>provider</th><th>prob_source</th><th class="num">정확도</th><th class="num">Wilson 95%</th><th class="num">AUROC(진단)</th><th class="num">Brier</th><th class="num">$/M 입력</th><th>출처</th></tr></thead><tbody>
  ${rows.map(([a, s]) => { const m = armMeta(a); return `<tr><td>${esc(a)}</td><td><code>${esc(m.model || s.model || '')}</code></td><td>${esc(m.provider || '-')}</td><td>${esc(m.prob_source || s.prob_source || '')}</td><td class="num">${pct(s.acc)}</td><td class="num">${s.ci95 ? `[${(s.ci95[0] * 100).toFixed(0)}, ${(s.ci95[1] * 100).toFixed(0)}]` : '-'}</td><td class="num">${s.auroc == null ? 'N/A' : s.auroc.toFixed(2)}</td><td class="num">${s.brier == null ? 'N/A' : s.brier.toFixed(3)}</td><td class="num">${m.in_per_m ?? '-'}</td><td>${esc(s.source_badge || '')}</td></tr>`; }).join('')}
  </tbody></table></div>
  <p class="meta">n=${b.n} 에서 볼 수 있는 격차는 대략 ${Math.round(196 * Math.sqrt(Math.max(1, Math.round(b.n * 0.3))) / b.n)}pp 다. 그보다 작은 차이는 순위로 읽지 않는다. AUROC 가 높은데 정확도가 낮으면 임계를 옮기지 말고 질문을 고친다.</p>
  ${classes.length ? `<h3>클래스별 (맞음/n)</h3><div class="tbl"><table><thead><tr><th>클래스</th>${arms.map(a => `<th class="num">${esc(a)}</th>`).join('')}</tr></thead><tbody>
  ${classes.map(c => `<tr><td>${esc(c)}</td>${arms.map(a => { const v = (b.per_class[c] || {})[a]; return `<td class="num">${v ? v[0] + '/' + v[1] : '-'}</td>`; }).join('')}</tr>`).join('')}</tbody></table></div>` : ''}
  <h2>어떻게 실험했나</h2>
  <dl class="kv"><dt>실행일</dt><dd>${esc(ex.date || '-')}</dd><dt>러너</dt><dd>${esc(ex.runner || '-')} · 템플릿 ${esc(ex.template || '-')}</dd>
    <dt>호출</dt><dd>${ex.protocol ? esc(JSON.stringify(ex.protocol.logprob_call)) : '-'}<br><span class="meta">${ex.protocol ? esc(ex.protocol.provider_pin) : ''}</span></dd>
    <dt>이진</dt><dd>${ex.protocol ? esc(ex.protocol.binary) : '-'}</dd><dt>다지</dt><dd>${ex.protocol ? esc(ex.protocol.multiclass) : '-'}</dd>
    <dt>typed</dt><dd>${ex.protocol ? esc(ex.protocol.typed) : '-'}</dd><dt>라벨 질량</dt><dd>${ex.protocol ? esc(ex.protocol.label_mass) + '. ' + esc(ex.protocol.renormalize) : '-'}</dd>
    <dt>결정 규칙</dt><dd>${ex.protocol ? esc(ex.protocol.decision_rule) : '-'}</dd></dl>
  ${Object.keys(ex.arms || {}).length ? `<div class="tbl"><table><thead><tr><th>이름</th><th>모델</th><th>provider</th><th>패밀리</th><th>모드</th><th>엔드포인트</th><th>스모크</th></tr></thead><tbody>
  ${Object.entries(ex.arms).map(([a, m]) => `<tr><td>${esc(a)}</td><td><code>${esc(m.model)}</code></td><td>${esc(m.provider || '-')}</td><td>${esc(m.family || '-')}</td><td>${esc(m.mode)} / ${esc(m.prob_source)}</td><td>${esc(m.base_url || '-')}</td><td>${m.smoke ? `${m.smoke.usable ? '사용 가능' : '못 씀'} · 편차 ${m.smoke.spread == null ? '-' : m.smoke.spread.toFixed(3)} · 확률값 ${m.smoke.distinct_p ?? '-'}종 · 5건 ${m.smoke.smoke_acc ?? '-'}` : '기록 없음'}</td></tr>`).join('')}</tbody></table></div>` : ''}`
  : '<div class="note"><span class="chip pending">레지스트리 실행 대기</span> 결과가 아직 없다. 게시된 벤치는 레지스트리가 예시 모델 넷을 한 번 돌려 결과를 붙인다.</div>'}
  ${b.source_results ? `<h2>원천 리더보드 모델의 이 ${b.n}건 정확도 <span class="meta">참고</span></h2>
  <p class="meta">${esc(b.source_results.source)}. ${esc(b.source_results.note)} 모델 ${b.source_results.n_models}개 중 프런티어 계열 ${b.source_results.n_frontier}개. 「전체」는 원천 벤치 전체 항목에서의 정확도이고 「이 벤치」는 그중 여기 고른 항목만의 정확도다.</p>
  <div class="tbl srcres"><table><thead><tr><th>모델</th><th class="num">이 벤치</th><th class="num">전체</th></tr></thead><tbody>
  ${b.source_results.models.map(m => `<tr class="${m.frontier ? 'frontier' : ''}"><td><code>${esc(m.model)}</code></td><td class="num">${pct(m.acc_subset)}</td><td class="num">${pct(m.acc_full)}</td></tr>`).join('')}</tbody></table></div>` : ''}
  <h2>커뮤니티 점수</h2>
  <p class="meta">다른 사람이 같은 판본(해시 동일)에 새 모델을 돌려 제출한 결과. 제출자가 서로 다른 3건 이상이 5pp 안에 모이면 「검증됨」이고 공식 점수는 중앙값이다. 작성자 본인 제출은 세지 않는다. 제출: <code>benchlet submit --bench ${esc(b.name)} --results results/${esc(b.name)}-run.json --github</code></p>
  ${Object.keys((b.community || {}).models || {}).length ? `<div class="tbl"><table><thead><tr><th>모델</th><th>provider</th><th class="num">중앙값</th><th class="num">범위</th><th class="num">제출</th><th>상태</th></tr></thead><tbody>
  ${Object.entries(b.community.models).map(([k, v]) => `<tr><td><code>${esc(v.model || k)}</code></td><td>${esc(v.provider || '-')}</td><td class="num">${pct(v.median_acc)}</td><td class="num">${pct(v.min_acc)} ~ ${pct(v.max_acc)}</td><td class="num">${v.n_submissions}</td><td>${v.verified ? '<span class="chip">검증됨</span>' : esc(v.status)}</td></tr>`).join('')}</tbody></table></div>` : '<p class="meta">아직 제출이 없다.</p>'}
  <h2>표본 ${b.samples.length}건</h2>
  ${b.samples.map(s => `<div class="sample"><div><code>${esc(s.id)}</code> <span class="chip">${esc(s.class || '-')}</span> 정답 <b>${esc((b.choices || [])[s.target] ?? s.target)}</b> <span class="meta">${esc(s.label_source || '')}</span></div><div class="in">${esc(s.input)}</div>${s.evidence ? `<div class="meta">근거: ${esc(s.evidence)}</div>` : ''}</div>`).join('')}
  <h2>작성자</h2><div class="ownercard">${ownerLine(b, true)}<div class="meta">${esc(o.bio || '')}</div>${b.pointer && b.pointer.repo ? `<div class="meta">피드백: <a href="https://github.com/${esc(b.pointer.repo)}/issues/new?title=${encodeURIComponent('[' + b.name + '] ')}" target="_blank" rel="noopener">벤치 리포에 이슈 남기기</a> · 쓸모 있었으면 <a href="https://github.com/${esc(b.pointer.repo)}" target="_blank" rel="noopener">스타</a>. 스타는 신뢰 점수와 추천 가중에 반영된다. Claude Code 에서는 <code>benchlet star remote:${esc(b.owner)}/${esc(b.name)}</code></div>` : ''}${others.length ? `<div class="meta">이 작성자의 다른 벤치: ${others.map(x => `<a href="#b-${esc(x.name)}">${esc(x.name)}</a>`).join(', ')}</div>` : ''}</div>
  <h2>내 데이터로 포크</h2>
  <p class="meta">스킬 호출 문장을 복사해 Claude Code 에 붙인다. 생성기·질문·선택지·클래스 표를 가져오고 원자료 경로는 비워 둔다. 포크 관계는 매니페스트에 남아 계보로 보인다.</p>
  <pre id="fork">${esc(forkCmd)}</pre><button class="primary" id="copy">복사</button> <span class="meta" id="copied"></span>`;
  $('#copy').onclick = () => { navigator.clipboard.writeText(forkCmd).then(() => $('#copied').textContent = '복사됨').catch(() => { const r = document.createRange(); r.selectNodeContents($('#fork')); getSelection().removeAllRanges(); getSelection().addRange(r); $('#copied').textContent = '선택됨. 복사해라'; }); };
  loadStars();
}
function recommend() {
  const groups = {};
  D.benches.forEach(b => { const rows = armRows(b); if (!rows.length) return; const k = [b.signature.goal || '(goal 미기재)', b.signature.answer || b.type].join(' / ');
    const g = groups[k] = groups[k] || { benches: [], arms: {} };
    const w = 1 + trust(b).score / 5;   // 신뢰 점수 가중(1~3배). 근거 수는 가중 없이 센다
    g.benches.push(b.name); rows.forEach(([a, s]) => { const m = (b.experiment.arms || {})[a] || {}; const e = (g.arms[a] = g.arms[a] || { accs: [], ws: [], model: m.model || s.model, provider: m.provider, ps: m.prob_source || s.prob_source }); e.accs.push(s.acc); e.ws.push(w); }); });
  $('#main').innerHTML = `<h1>유형별 추천</h1><p class="lead">과제 서명이 같은 벤치들의 결과를 합쳐 「이 유형엔 이 모델」을 근거 수와 함께 낸다. 평균은 벤치의 신뢰 점수(커뮤니티 검증, 검수, 축약 검증, 작성자 공개 신호)로 가중한다. 근거 수가 3 미만이면 추천이 아니라 참고다.</p>
  ${Object.entries(groups).map(([k, g]) => { const rows = Object.entries(g.arms).map(([a, v]) => [a, v.accs.reduce((p, c, i) => p + c * v.ws[i], 0) / v.ws.reduce((p, c) => p + c, 0), v.accs.length, v.model, v.ps, v.provider]).sort((x, y) => y[1] - x[1]);
    return `<h2>${esc(k)} <span class="meta">벤치 ${g.benches.length}개: ${g.benches.map(n => `<a href="#b-${esc(n)}">${esc(n)}</a>`).join(', ')}</span></h2><div class="tbl"><table><thead><tr><th>이름</th><th>모델</th><th>provider</th><th>prob_source</th><th class="num">평균 정확도</th><th class="num">근거 수</th></tr></thead><tbody>
    ${rows.map(r => `<tr><td>${esc(r[0])}</td><td><code>${esc(r[3] || '')}</code></td><td>${esc(r[5] || '-')}</td><td>${esc(r[4] || '')}</td><td class="num">${pct(r[1])}</td><td class="num">${r[2]}</td></tr>`).join('')}</tbody></table></div>`; }).join('') || '<p class="meta">결과가 붙은 벤치가 없다.</p>'}
  <h2>예시 모델과 확인된 로그확률 조합 (OpenRouter, ${esc(D.verified.verified_at || '')})</h2><p class="meta">확정된 기본값은 없다. 지금 갤러리 결과에 쓴 예시가 이 넷이고, 입력이 싼 프런티어 모델이나 20~30B 급 모델, Jev 류 판단 전용 모델이면 무엇이든 바꿔 쓸 수 있다. 로그프롭을 주는 OpenAI 호환 엔드포인트면 어떤 모델이든 <code>benchlet run --arms custom:&lt;모델&gt;</code> 에 <code>BENCHLET_BASE_URL</code>, <code>BENCHLET_API_KEY</code> 로 돌릴 수 있고, 스모크가 로그프롭·재현성·라벨 질량을 먼저 확인한다.</p>
  <div class="tbl"><table><thead><tr><th>모델</th><th>provider</th><th class="num">$/M 입력</th><th>패밀리</th><th>비고</th></tr></thead><tbody>
  ${(D.verified.verified_working || []).map(v => `<tr><td><code>${esc(v.model)}</code></td><td>${esc(v.provider)}</td><td class="num">${v.in_per_m}</td><td>${esc(v.family)}</td><td>${esc(v.note || '')}</td></tr>`).join('')}</tbody></table></div>
  <p class="meta">운영자가 직접 확인한 조합은 이 넷뿐이다. 새 모델은 스모크로 확인하고 쓰면 된다. 다른 엔드포인트와 모델은 「내 벤치 만들기」의 실행 요건 8개를 사용자의 에이전트가 확인한다.</p>`;
}
function md(s) {
  const lines = s.split('\n'); let out = '', inCode = false, inList = false, inTable = false;
  const inline = t => esc(t).replace(/`([^`]+)`/g, '<code>$1</code>').replace(/\*\*([^*]+)\*\*/g, '<b>$1</b>');
  const close = () => { if (inList) { out += '</ul>'; inList = false; } if (inTable) { out += '</tbody></table></div>'; inTable = false; } };
  for (const l of lines) {
    if (l.startsWith('```')) { if (inCode) { out += '</pre>'; inCode = false; } else { close(); out += '<pre>'; inCode = true; } continue; }
    if (inCode) { out += esc(l) + '\n'; continue; }
    if (/^\|/.test(l)) { if (/^\|\s*-/.test(l)) continue; const cells = l.split('|').slice(1, -1).map(c => c.trim()); if (!inTable) { close(); inTable = true; out += `<div class="tbl"><table><thead><tr>${cells.map(c => `<th>${inline(c)}</th>`).join('')}</tr></thead><tbody>`; } else out += `<tr>${cells.map(c => `<td>${inline(c)}</td>`).join('')}</tr>`; continue; }
    if (/^#{1,3} /.test(l)) { close(); const lv = l.match(/^#+/)[0].length; out += `<h${lv + 1}>${inline(l.replace(/^#+ /, ''))}</h${lv + 1}>`; continue; }
    if (/^[-*] /.test(l)) { if (inTable) close(); if (!inList) { out += '<ul>'; inList = true; } out += `<li>${inline(l.slice(2))}</li>`; continue; }
    if (/^\d+\. /.test(l)) { if (inTable) close(); if (!inList) { out += '<ul>'; inList = true; } out += `<li>${inline(l.replace(/^\d+\. /, ''))}</li>`; continue; }
    if (!l.trim()) { close(); continue; }
    close(); out += `<p>${inline(l)}</p>`;
  }
  close(); if (inCode) out += '</pre>'; return out;
}
function guide() {
  const g = D.guide;
  $('#main').innerHTML = `<h1>내 벤치 만들기</h1>
  <p class="lead">벤치는 손으로 만드는 게 아니라 에이전트에게 시킨다. 플러그인을 설치하고 Claude Code 에서 판정 지점을 한 문장으로 말하면, 스킬이 프로젝트를 읽어 후보를 찾고 항목을 만들고 검수하고 게시까지 묻는다.</p>
  <div class="steps"><div class="step"><span class="n">1</span><h3>설치</h3><pre>claude plugin marketplace add ernestolee13/benchlet
claude plugin install benchlet</pre></div>
  <div class="step"><span class="n">2</span><h3>한 문장</h3><pre>/minibench-author 이 프로젝트 기준으로
나만의 벤치 만들어 줘</pre></div>
  <div class="step"><span class="n">3</span><h3>에이전트가 묻는 것</h3><p>비슷한 공개 벤치를 포크할지, 라벨 경로와 항목 수, 어디에 올릴지(로컬 / GitHub 비공개 / 공개), 쓸모 있었던 벤치 작성자에게 스타를 남길지.</p></div></div>
  <h2>아래는 그때 에이전트가 따르는 기준이다</h2>
  <p class="meta">스킬의 references 와 같은 내용이다. 손으로 만들어도 이 형식과 기준이어야 올라간다. 무엇을 왜 묻는지 알고 싶을 때 읽는다.</p>
  <h2>분류 체계 (올릴 때와 찾을 때 같은 말)</h2>
  <p class="meta">다섯 축을 매니페스트 <code>taxonomy</code> 와 <code>keywords</code> 에 적는다. 영역(domain)은 아래 목록에서 고르고, 키워드는 시작 목록의 정규형을 먼저 쓴다. 어휘 밖이면 validate 가 경고하고 taxonomy.yaml 에 제안한다.</p>
  <div class="tbl"><table><thead><tr><th>영역</th><th>뜻</th><th>벤치 수</th></tr></thead><tbody>${Object.entries((D.taxonomy||{}).domain||{}).map(([k, v]) => `<tr><td><code>${esc(k)}</code></td><td>${esc(v)}</td><td>${D.benches.filter(b => ((b.taxonomy||{}).domain||[]).includes(k)).length}</td></tr>`).join('')}</tbody></table></div>
  <div class="tbl"><table><thead><tr><th>키워드 정규형</th><th>동의어</th></tr></thead><tbody>${Object.entries((D.taxonomy||{}).keywords||{}).map(([k, v]) => `<tr><td>${esc(k)}</td><td class="meta">${esc((v||[]).join(', '))}</td></tr>`).join('')}</tbody></table></div>
  <div class="md"><h2>형식 계약</h2>${md(g.format)}<h2>질문 작성 규칙</h2>${md(g.question)}<h2>채우기</h2>${md(g.generate)}<h2>자가 점검표</h2>${md(g.rubric)}<h2>우리가 잡은 결함 12개</h2>${md(g.lessons)}<h2>실행 요건 (어느 게이트웨이든)</h2>${md(g.run_guide)}<h2>로그확률 함정</h2>${md(g.traps)}</div>`;
}
function route() {
  const h = (location.hash || '#home').slice(1);
  document.querySelectorAll('nav a').forEach(a => a.classList.toggle('on', a.dataset.v === (h.startsWith('b-') ? 'gallery' : h)));
  if (h.startsWith('b-')) detail(h.slice(2)); else if (h === 'gallery') gallery(); else if (h === 'recommend') recommend(); else if (h === 'guide') guide(); else home();
  window.scrollTo(0, 0);
}
window.addEventListener('hashchange', route); route();
</script>
'''
