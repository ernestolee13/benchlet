"""경로와 환경 설정. 키 값은 절대 로그·리포·메시지에 쓰지 않는다."""
from __future__ import annotations

import os
import re
from pathlib import Path

def _default_env_file() -> Path:
    """키 파일. BENCHLET_ENV_FILE 환경변수가 있으면 그 경로, 없으면 ~/.config/benchlet/env"""
    return Path(os.environ.get("BENCHLET_ENV_FILE") or (Path.home() / ".config" / "benchlet" / "env"))


ENV_FILE = _default_env_file()
BANNED_TERMS_FILE = Path(os.environ.get(
    "BENCHLET_BANNED_TERMS", str(Path.home() / ".config" / "benchlet" / "banned_terms.txt")))
PACKAGE_DIR = Path(__file__).resolve().parent
VERIFIED_TABLE = PACKAGE_DIR / "data" / "or_verified.json"

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
OPENROUTER_DECISIONS_URL = "https://openrouter.ai/api/alpha/decisions"


def find_repo_root(start: Path | None = None) -> Path:
    """tasks/ 나 .git 이 있는 가장 가까운 상위 디렉터리. 없으면 cwd."""
    p = (start or Path.cwd()).resolve()
    for cand in [p] + list(p.parents):
        if (cand / "tasks").is_dir() or (cand / ".git").exists():
            return cand
    return p


def read_env_key(name: str, env_file: Path = ENV_FILE) -> str | None:
    """환경변수 → env 파일 순으로 키를 읽는다. 값은 돌려주기만 하고 어디에도 쓰지 않는다."""
    v = os.environ.get(name)
    if v:
        return v
    if not env_file.exists():
        return None
    pat = re.compile(r"\s*(?:export\s+)?" + re.escape(name) + r"\s*=\s*[\"']?([^\"'\s]+)")
    for line in env_file.read_text().splitlines():
        m = pat.match(line)
        if m:
            return m.group(1)
    return None


def load_banned_terms(path: Path = BANNED_TERMS_FILE) -> list[str]:
    """사용자 금지어. 로컬 파일에만 두고 리포에는 넣지 않는다."""
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            out.append(s)
    return out
