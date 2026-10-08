"""GitHub 연결형 게시: gh·git 을 가짜 runner 로 바꿔 흐름만 검증한다(네트워크 없음)."""
from pathlib import Path

from benchlet import github as gh


def fake_runner_factory(log, repo_exists=True):
    def runner(cmd, cwd=None, check=True):
        log.append((cmd[:3], str(cwd) if cwd else None))
        if cmd[:3] == ["gh", "api", "user"]:
            return "tester" if "--jq" in cmd and cmd[-1] == ".login" else '{"login":"tester","name":"Tester","bio":"","html_url":"https://github.com/tester"}'
        if cmd[:3] == ["gh", "repo", "view"]:
            if repo_exists:
                return '{"name":"x"}'
            raise RuntimeError("not found")
        if cmd[:3] == ["gh", "repo", "clone"]:
            d = Path(cmd[4]); (d / ".git").mkdir(parents=True); return ""
        if cmd[:2] == ["git", "status"]:
            return " M x"
        if cmd[:2] == ["git", "rev-parse"]:
            return "abc1234def"
        return ""
    return runner


def test_ensure_repo_creates_when_missing():
    log = []
    full = gh.ensure_repo("benchlet-benches", runner=fake_runner_factory(log, repo_exists=False))
    assert full == "tester/benchlet-benches"
    assert any(c[0][:3] == ["gh", "repo", "create"] for c in log)


def test_push_bundle_copies_commits_pushes(tmp_path):
    log = []
    bundle = tmp_path / "bundle"; bundle.mkdir(); (bundle / "manifest.yaml").write_text("name: x\n")
    r = gh.push_bundle(bundle, "tester/benchlet-benches", "benches/x", "publish x", runner=fake_runner_factory(log), cache=tmp_path / "cache")
    assert r["commit"] == "abc1234def" and r["url"].endswith("/benches/x")
    assert (tmp_path / "cache" / "tester__benchlet-benches" / "benches" / "x" / "manifest.yaml").exists()
    cmds = [c[0] for c in log]
    assert ["git", "commit", "-q"] not in cmds and any(c[:2] == ["git", "push"] for c in cmds) and any(c[:2] == ["git", "commit"] or c[:3] == ["git", "-c", "user.name=benchlet"] for c in cmds)
