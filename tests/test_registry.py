"""레지스트리 수집기: 가짜 gh runner 로 sync 흐름과 registry-run 보존을 검증한다."""
import json
from pathlib import Path

import yaml

from benchlet import registry as R


def make_source_repo(cache: Path, repo: str, slug: str, with_pii=False):
    local = cache / repo.replace("/", "__")
    b = local / "benches" / slug
    b.mkdir(parents=True)
    (local / ".git").mkdir(exist_ok=True)
    (b / "manifest.yaml").write_text(yaml.safe_dump({"name": slug, "owner": repo.split("/")[0], "question": "q 위반하는가", "choices": ["위반", "통과"], "n": 2, "results": "pending", "visibility": "full"}, allow_unicode=True), encoding="utf-8")
    rows = [{"id": "a", "input": "x someone@example.com" if with_pii else "x", "target": 0, "choices": ["위반", "통과"], "question": "q"},
            {"id": "b", "input": "y", "target": 1, "choices": ["위반", "통과"], "question": "q"}]
    (b / "samples.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")


def runner_factory(log):
    def runner(cmd, cwd=None, check=True):
        log.append(cmd[:3])
        if cmd[:2] == ["git", "rev-parse"]:
            return "deadbeef"
        return ""
    return runner


def test_sync_imports_valid_and_rejects_pii(tmp_path, monkeypatch):
    root = tmp_path / "root"; (root / "registry").mkdir(parents=True)
    (root / "registry" / "sources.yaml").write_text("sources:\n  - repo: alice/benches\n", encoding="utf-8")
    cache = tmp_path / "cache"
    make_source_repo(cache, "alice/benches", "good")
    make_source_repo(cache, "alice/benches", "bad", with_pii=True)
    monkeypatch.setenv("BENCHLET_BANNED_TERMS", str(tmp_path / "none"))
    rows = R.sync(root, runner=runner_factory([]), cache=cache)
    st = {r["slug"]: r["status"] for r in rows}
    assert st == {"good": "synced", "bad": "rejected"}
    ptr = yaml.safe_load((root / "registry" / "benches" / "alice" / "good" / "pointer.yaml").read_text(encoding="utf-8"))
    assert ptr["repo"] == "alice/benches" and ptr["commit"] == "deadbeef"


def test_sync_preserves_registry_run(tmp_path, monkeypatch):
    root = tmp_path / "root"; (root / "registry").mkdir(parents=True)
    (root / "registry" / "sources.yaml").write_text("sources:\n  - repo: alice/benches\n", encoding="utf-8")
    cache = tmp_path / "cache"
    make_source_repo(cache, "alice/benches", "good")
    monkeypatch.setenv("BENCHLET_BANNED_TERMS", str(tmp_path / "none"))
    R.sync(root, runner=runner_factory([]), cache=cache)
    dest = root / "registry" / "benches" / "alice" / "good"
    (dest / "results").mkdir()
    (dest / "results" / "good-registry-run.json").write_text("{}", encoding="utf-8")
    m = yaml.safe_load((dest / "manifest.yaml").read_text(encoding="utf-8"))
    m["registry_run"] = {"date": "2026-09-30", "arms": ["qwen"]}
    m["result_summary"] = {"qwen": {"acc": 0.9, "source_badge": "registry-run"}}
    m["results"] = ["results/good-registry-run.json"]
    (dest / "manifest.yaml").write_text(yaml.safe_dump(m, allow_unicode=True), encoding="utf-8")
    R.sync(root, runner=runner_factory([]), cache=cache)      # 두 번째 동기화가 레지스트리 실행을 지우면 안 된다
    m2 = yaml.safe_load((dest / "manifest.yaml").read_text(encoding="utf-8"))
    assert (dest / "results" / "good-registry-run.json").exists()
    assert m2["registry_run"]["arms"] == ["qwen"] and m2["result_summary"]["qwen"]["source_badge"] == "registry-run"
    assert "results/good-registry-run.json" in m2["results"]
