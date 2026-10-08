import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "bench-core"))
sys.path.insert(0, str(ROOT / "src"))

import pytest  # noqa: E402


@pytest.fixture(scope="session")
def root() -> Path:
    return ROOT


import pytest as _pytest

_NEEDS_TASKS_MODULES = {"test_review_recall.py", "test_runner_offline.py", "test_schema.py"}
_NEEDS_TASKS_TESTS = {"test_concurrent_run_matches_sequential", "test_exports", "test_cli_validate_and_publish_without_results", "test_validate_review_plan_models"}


def pytest_collection_modifyitems(config, items):
    """내 데이터 벤치(tasks/)와 그 결과가 없는 공개 리포에서는 그걸 읽는 테스트를 건너뛴다."""
    root = Path(__file__).resolve().parents[1]
    if (root / "tasks").exists():
        return
    mark = _pytest.mark.skip(reason="tasks/ 없음 (공개 리포에는 내 데이터 벤치가 없다)")
    for it in items:
        if it.fspath.basename in _NEEDS_TASKS_MODULES or it.name.split("[")[0] in _NEEDS_TASKS_TESTS:
            it.add_marker(mark)
