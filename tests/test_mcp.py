"""MCP 서버 왕복: stdio JSON-RPC 로 initialize → tools/list → 툴 호출. 모델 호출 없음."""
import json
import os
import subprocess
import sys

import pytest


def rpc(proc, mid, method, params=None):
    proc.stdin.write(json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params or {}}) + "\n")
    proc.stdin.flush()
    while True:
        line = proc.stdout.readline()
        if not line:
            raise RuntimeError("server closed: " + proc.stderr.read())
        msg = json.loads(line)
        if msg.get("id") == mid:
            return msg


def call(proc, mid, name, args):
    r = rpc(proc, mid, "tools/call", {"name": name, "arguments": args})
    res = r["result"]
    return res.get("structuredContent") or res["content"][0]["text"], res.get("isError", False)


@pytest.fixture
def server(root, tmp_path):
    env = dict(os.environ, PYTHONPATH=str(root / "bench-core"), BENCHLET_ROOT=str(root), BENCHLET_BANNED_TERMS=str(tmp_path / "none"))
    proc = subprocess.Popen([sys.executable, "-m", "benchlet.cli", "mcp"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, env=env, cwd=str(root))
    yield proc
    proc.stdin.close(); proc.terminate()


def test_initialize_and_list(server):
    r = rpc(server, 1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "t", "version": "0"}})
    assert r["result"]["serverInfo"]["name"] == "benchlet"
    tools = rpc(server, 2, "tools/list")["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"bench_validate", "bench_review", "bench_plan", "bench_publish", "bench_search", "bench_similar", "bench_fork", "bench_models", "bench_registry_sync", "bench_run_pending"} <= names
    assert len(names) == 23


def test_validate_review_plan_models(server):
    out, err = call(server, 3, "bench_validate", {"bench_id": "sns-stale-schedule"})
    assert not err and out["ok"] and out["n"] == 48
    out, err = call(server, 4, "bench_review", {"bench_id": "guideline-compliance", "checks": [2, 5, 10]})
    assert not err and out["checks_run"] == [2, 5, 10] and out["flags"].get("strong", 0) >= 2
    out, err = call(server, 5, "bench_review_queue", {"bench_id": "guideline-compliance", "limit": 3})
    assert not err and len(out["flags"]) == 3
    out, err = call(server, 6, "bench_plan", {"candidates": [
        {"name": "a", "signature": {"goal": "compliance", "answer": "binary", "unit": "post", "prob_use": "accuracy_only"}, "grade": "core", "label_path": 1, "n_available": 300, "n_classes": 6},
        {"name": "b", "signature": {"goal": "derive", "answer": "binary", "unit": "record", "prob_use": "threshold"}, "grade": "aux", "label_path": 2, "n_classes": 3},
        {"name": "c", "signature": {"goal": "gate", "answer": "binary", "unit": "record"}, "grade": "later", "label_path": 3}], "budget_min": 60})
    assert not err and out["rows"][0]["n"] == 80 and out["rows"][1]["n"] == 60 and out["rows"][2]["recommended"] is False
    out, err = call(server, 7, "bench_models", {})
    assert not err and "qwen" in out["presets"] and out["verified_at"]
    out, err = call(server, 8, "bench_results", {"bench_id": "route-selection", "view": "disagreements"})
    assert not err and out["n"] >= 1


def test_create_add_publish_search_fork(server, root):
    import shutil
    name = "mcp-test-bench"
    for d in (root / "benches" / name, root / "registry" / "benches" / "ernestolee13" / name, root / "benches" / (name + "-fork")):
        shutil.rmtree(d, ignore_errors=True)
    try:
        out, err = call(server, 10, "bench_create", {"name": name, "question": "이 문장이 규칙을 위반하는가. 위반은 비난 어휘를 쓴 것이다", "choices": ["위반", "통과"], "domain": ["editorial-norm"]})
        assert not err and out["bench_id"] == f"benches/{name}"
        items = [{"input": f"규제 기관이 업체 {i}에 시정명령을 내렸다.", "target": 1, "evidence": "해당 없음", "class": "CLEAN"} for i in range(4)] + \
                [{"input": f"악질 업체 {i}가 시정명령을 받았다.", "target": 0, "evidence": "비난 어휘 「악질」", "class": "W1"} for i in range(4)]
        out, err = call(server, 11, "bench_add_items", {"bench_id": f"benches/{name}", "items": items})
        assert not err and out["total"] == 8
        out, err = call(server, 12, "bench_add_items", {"bench_id": f"benches/{name}", "items": [{"input": "연락 someone@example.com", "target": 0, "evidence": "e"}]})
        assert err and "개인정보" in out
        out, err = call(server, 13, "bench_publish", {"bench_id": f"benches/{name}"})
        assert err and "confirm" in out
        out, err = call(server, 14, "bench_publish", {"bench_id": f"benches/{name}", "confirm": True})
        assert not err and out["results"] == "pending" and (root / out["path"] / "manifest.yaml").exists()
        out, err = call(server, 15, "bench_search", {"query": "규칙 위반 비난"})
        assert not err and any(b["name"] == name for b in out["benches"])
        out, err = call(server, 16, "bench_similar", {"question": "이 요약이 편집 규범을 위반하는가", "signature": {"answer": "binary"}})
        assert not err and out["choices"][0] == "fork"
        out, err = call(server, 17, "bench_fork", {"bench_id": f"registry/benches/ernestolee13/{name}", "new_name": name + "-fork"})
        assert not err and out["forked_from"]["name"] == name
        out, err = call(server, 18, "bench_freeze", {"bench_id": f"benches/{name}"})
        assert not err and out["sha256"]
    finally:
        for d in (root / "benches" / name, root / "registry" / "benches" / "ernestolee13" / name, root / "benches" / (name + "-fork")):
            shutil.rmtree(d, ignore_errors=True)
        p = root / "labels" / "SHA256SUMS"
        p.write_text("".join(l for l in p.read_text().splitlines(True) if name not in l))
