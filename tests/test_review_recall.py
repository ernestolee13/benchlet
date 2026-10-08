"""결함 12개 소급 재현: docs/REVIEW_RECALL.md 와 같은 코드(benchlet.review.recall)로 판정한다."""
import pytest

from benchlet.review import recall
from benchlet.review.checks import run_checks
from benchlet.schema import load_bench

EXPECTED = {1: True, 2: True, 3: True, 4: True, 5: True, 6: False, 7: True, 8: True, 9: True, 10: True, 11: True, 12: True}


@pytest.fixture(scope="module")
def rows(root):
    return {r["no"]: r for r in recall.run_all(root)}


@pytest.mark.parametrize("no", sorted(EXPECTED))
def test_defect_recall_matches_table(rows, no):
    assert rows[no]["caught"] is EXPECTED[no], rows[no]["detail"]


def test_recall_rate_at_least_11_of_12(rows):
    assert sum(1 for k, r in rows.items() if isinstance(k, int) and r["caught"]) >= 11


def test_check2_all_arms_zero_flags_soft_rule(root):
    from benchlet.review.results import load_results
    b = load_bench("guideline-compliance", root)
    rep = run_checks(b, load_results(root / "results" / "guide-run.json", b.items), [2])
    assert any("P4-register" in f.message and f.strength == "strong" for f in rep.flags)


def test_check7_flags_obvious_negatives_only_when_present(root):
    b = load_bench("t3-text-grounded", root)
    rep = run_checks(b, None, [7])
    assert any(f.data.get("acc") == 1.0 for f in rep.flags)
    b2 = load_bench("sns-stale-schedule", root)
    rep2 = run_checks(b2, None, [7])
    assert not any(f.strength == "strong" for f in rep2.flags if f.check == 7)


def test_check5_flags_same_script_verifier(root):
    rep = run_checks(load_bench("sns-numbers-sourced", root), None, [5])
    assert any(f.strength == "strong" and "같은 코드 경로" in f.message for f in rep.flags)
    rep2 = run_checks(load_bench("sns-published-audit", root), None, [5])
    assert not any(f.strength == "strong" for f in rep2.flags)


def test_check8_skipped_without_rules(root):
    rep = run_checks(load_bench("route-selection", root), None, [8])
    assert 8 in rep.skipped and 8 not in rep.checks_run


def test_check11_dump_has_20_rows(root):
    rep = run_checks(load_bench("editorial-norm", root), None, [11])
    sec = rep.sections["검사 11 채점기·검증기 표본 덤프 (20건)"]
    assert sec.count("\n| norm-") == 20
