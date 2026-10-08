"""GitHub 연결형 저장. 신원은 `gh` 로그인(계정 없는 v1 에서 GitHub 계정이 곧 작성자다).

게시 묶음을 사용자 자기 리포(`benchlet-benches` 기본)에 커밋·푸시하고, 로컬 레지스트리에는 포인터(리포·경로·커밋)만 남긴다.
전부 `gh`·`git` 서브프로세스다. 토큰을 코드가 다루지 않는다. 테스트는 runner 를 바꿔 끼운다.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

DEFAULT_REPO = "benchlet-benches"
CACHE = Path(os.environ.get("BENCHLET_REPO_CACHE", str(Path.home() / ".cache" / "benchlet" / "repos")))


def run(cmd: list, cwd: Path | None = None, check: bool = True) -> str:
    r = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:3])} 실패: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def gh_login(runner=run) -> str | None:
    try:
        return runner(["gh", "api", "user", "--jq", ".login"]) or None
    except Exception:            # noqa: BLE001
        return None


def gh_profile(runner=run) -> dict | None:
    try:
        raw = runner(["gh", "api", "user", "--jq", "{login: .login, name: .name, bio: .bio, html_url: .html_url}"])
        return json.loads(raw) if raw else None
    except Exception:            # noqa: BLE001
        return None


def ensure_repo(name: str, private: bool = False, runner=run) -> str:
    """owner/name 리포가 없으면 만든다. 반환: 'owner/name'."""
    login = gh_login(runner)
    if not login:
        raise RuntimeError("gh 로그인이 없다. `gh auth login` 뒤 다시")
    full = f"{login}/{name}" if "/" not in name else name
    try:
        runner(["gh", "repo", "view", full, "--json", "name"])
    except Exception:            # noqa: BLE001
        runner(["gh", "repo", "create", full, "--private" if private else "--public", "-d", "benchlet judgment mini-benchmarks (published bundles)"])
    return full


def push_bundle(bundle_dir: Path, repo_full: str, dest_path: str, message: str, runner=run, cache: Path = CACHE) -> dict:
    """묶음 폴더를 리포의 dest_path 로 복사해 커밋·푸시. 반환 {repo, path, commit, url}."""
    cache.mkdir(parents=True, exist_ok=True)
    local = cache / repo_full.replace("/", "__")
    if not (local / ".git").exists():
        shutil.rmtree(local, ignore_errors=True)
        runner(["gh", "repo", "clone", repo_full, str(local)])
    else:
        runner(["git", "pull", "--ff-only", "-q"], cwd=local, check=False)
    dest = local / dest_path
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(bundle_dir, dest)
    readme = local / "README.md"
    if not readme.exists():
        readme.write_text("# benchlet benches\n\n`benches/<slug>/manifest.yaml + samples.jsonl + results/`. 게시 도구: benchlet.\n", encoding="utf-8")
    runner(["git", "add", "-A"], cwd=local)
    status = runner(["git", "status", "--porcelain"], cwd=local, check=False)
    if status:
        runner(["git", "-c", "user.name=benchlet", "-c", "user.email=benchlet@users.noreply.github.com", "commit", "-q", "-m", message], cwd=local)
        runner(["git", "push", "-q"], cwd=local)
    commit = runner(["git", "rev-parse", "HEAD"], cwd=local, check=False)
    return {"repo": repo_full, "path": dest_path, "commit": commit,
            "url": f"https://github.com/{repo_full}/tree/{commit or 'main'}/{dest_path}"}


def star_repo(repo_full: str, runner=run) -> dict:
    """작성자 리포에 스타를 남긴다(gh 로그인 계정). 갤러리 신뢰 점수의 「벤치 리포 스타」에 반영된다."""
    runner(["gh", "api", "-X", "PUT", f"user/starred/{repo_full}"])
    return {"repo": repo_full, "starred": True}


def is_starred(repo_full: str, runner=run) -> bool:
    try:
        runner(["gh", "api", f"user/starred/{repo_full}"])
        return True
    except Exception:            # noqa: BLE001
        return False
