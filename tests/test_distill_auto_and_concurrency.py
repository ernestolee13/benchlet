"""distill 의 auto 방법 선택(적합 모델 수 임계)과 러너의 항목 병렬 실행(순서 보존·집계 동일)."""
import random

from benchlet.distill import distill
from benchlet.runner import run as R
from benchlet.schema import load_bench
from tests.test_distill import synth


def test_auto_picks_random_when_few_fit_models():
    r = distill(synth(M=60, N=400), n=40, seed=5, iters=200)          # 모델 60 < 100
    assert r["method_key"] == "random" and r["alt"]["method"] == "swap search"
    assert r["selected"] and r["alt"]["val"]["mae"] >= 0


def test_auto_picks_swap_when_many_fit_models():
    r = distill(synth(M=160, N=500), n=40, seed=5, iters=200)         # 모델 160 >= 100
    assert r["method_key"] == "stratified" and r["alt"]["method"] == "stratified random"


def test_explicit_threshold_override():
    r = distill(synth(M=60, N=400), n=40, seed=5, iters=200, swap_min_models=10)
    assert r["method_key"] == "stratified"


def _fake_call_arm(client, arm, item, template, mode):
    rng = random.Random(item["id"] + arm["key"])
    if item["type"] == "binary":
        return {"p_violation": 0.9 if (item["target"] == 0) ^ (rng.random() < 0.2) else 0.1, "ms": 1, "cost": 0.0, "in_tok": 1, "err": None}
    pred = item["target"] if rng.random() < 0.8 else (item["target"] + 1) % len(item["choices"])
    return {"pred_index": pred, "probs": None, "ms": 1, "cost": 0.0, "in_tok": 1, "err": None, "order": list(range(len(item["choices"])))}


def test_concurrent_run_matches_sequential(root, monkeypatch):
    monkeypatch.setattr(R, "make_client", lambda arm: type("C", (), {"host": "fake"})())
    monkeypatch.setattr(R, "call_arm", _fake_call_arm)
    b = load_bench("route-selection", root)
    seq = R.run_bench(b, R.RunConfig(arms=["glm", "qwen"], limit=20, progress=False, concurrency=1))
    par = R.run_bench(b, R.RunConfig(arms=["glm", "qwen"], limit=20, progress=False, concurrency=5))
    assert [r["id"] for r in par["items"]] == [r["id"] for r in seq["items"]]
    assert par["agg"] == seq["agg"]
    assert list(par["agg"]) == ["glm", "qwen"]


def test_merge_results_replaces_only_new_arms():
    old = {"items_sha256": "x", "arms": {"glm": {"model": "a"}, "qwen": {"model": "b"}}, "agg": {"glm": {"hit": 1}, "qwen": {"hit": 2}},
           "items": [{"id": "i1", "arms": {"glm": {"p_violation": 0.1}, "qwen": {"p_violation": 0.2}}}], "date": "2026-10-01"}
    new = {"items_sha256": "x", "arms": {"qwen": {"model": "b2"}}, "agg": {"qwen": {"hit": 9}},
           "items": [{"id": "i1", "arms": {"qwen": {"p_violation": 0.9}}}], "date": "2026-10-05"}
    m = R.merge_results(old, new)
    assert m["arms"]["glm"]["model"] == "a" and m["arms"]["qwen"]["model"] == "b2"
    assert m["agg"] == {"glm": {"hit": 1}, "qwen": {"hit": 9}}
    assert m["items"][0]["arms"] == {"glm": {"p_violation": 0.1}, "qwen": {"p_violation": 0.9}}
    assert m["merged_runs"] == [{"date": "2026-10-05", "arms": ["qwen"]}]
    import pytest
    with pytest.raises(ValueError):
        R.merge_results(old, dict(new, items_sha256="y"))



def test_remote_benches_and_star(tmp_path, monkeypatch):
    from benchlet.mcp import server as M
    from benchlet import github as gh
    monkeypatch.setenv("BENCHLET_CACHE_DIR", str(tmp_path))
    data = {"benches": [{"name": "x-mini", "owner": "someone", "version": 1, "n": 100, "type": "binary", "question": "이 요청을 거절해야 하나",
                         "signature": {"goal": "gate", "answer": "binary"}, "taxonomy": {"domain": ["content-moderation"]}, "keywords": ["거절"],
                         "result_summary": {"glm": {"acc": 0.9}}, "pointer": {"repo": "someone/benchlet-benches", "commit": "abc", "path": "benches/x-mini"}}]}
    rows = M._remote_benches(fetch=lambda url: json.dumps(data))
    assert rows[0]["_path"] == "remote:someone/x-mini" and rows[0]["results"] == "available" and rows[0]["task_signature"]["goal"] == "gate"
    assert (tmp_path / "gallery.json").exists()          # 캐시
    calls = []
    def fake_run(cmd, cwd=None, check=True):
        calls.append(cmd); return "ok"
    r = gh.star_repo("someone/benchlet-benches", runner=fake_run)
    assert r["starred"] and calls[0][:3] == ["gh", "api", "-X"] and "user/starred/someone/benchlet-benches" in calls[0]


import json
