import math

from benchlet.stats import wilson, auroc, brier, mcnemar_exact, best_surface_feature, surface_features


def test_wilson_basic():
    lo, hi = wilson(30, 40)
    assert 0.59 < lo < 0.61 and 0.85 < hi < 0.87


def test_auroc_and_brier():
    assert auroc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert auroc([0.5, 0.5, 0.5, 0.5], [1, 1, 0, 0]) == 0.5
    assert auroc([0.9], [1]) is None
    assert math.isclose(brier([1.0, 0.0], [1, 0]), 0.0)


def test_mcnemar_exact():
    assert mcnemar_exact(0, 0) == 1.0
    assert mcnemar_exact(10, 0) < 0.01
    assert 0.9 < mcnemar_exact(5, 5) <= 1.0


def test_surface_feature_finds_amount_presence():
    inputs = [f"요약: 과징금 {i}억원을 부과했다." for i in range(1, 9)] + [f"요약: 시정명령을 내렸다 {i}" for i in range(8)]
    ys = [1] * 8 + [0] * 8
    r = best_surface_feature(inputs, ys)
    assert r["best"]["acc"] == 1.0 and r["best"]["feature"] in ("금액 유무", "숫자 개수", "길이")
    assert surface_features("a\nb")["줄바꿈 유무"] == 1
