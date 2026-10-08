"""축약: 합성 정오 행렬(로지스틱 능력·난이도)에서 검증 모델 MAE 가 작고 순위가 보존되는지."""
import math
import random

from benchlet.distill import distill, evaluate, _kendall


def synth(M=120, N=1500, seed=1):
    rng = random.Random(seed)
    ab = [rng.gauss(0, 1.2) for _ in range(M)]
    df = [rng.gauss(0, 1.0) for _ in range(N)]
    C = [[1 if rng.random() < 1 / (1 + math.exp(-(a - d))) else 0 for d in df] for a in ab]
    return {"models": [f"m{i}" for i in range(M)], "items": [f"i{j}" for j in range(N)], "correct": C}


def test_distill_preserves_accuracy_and_rank():
    r = distill(synth(), n=100, seed=3, iters=600)
    assert len(r["selected"]) == 100 and len(set(r["selected"])) == 100 and len(r["irt_b"]) == 100
    # 100건에서는 이항 잡음 때문에 3~4pp 가 바닥이다. 방법 간 차이보다 n 이 결정한다
    assert r["val"]["mae"] < 0.05, r["val"]
    assert r["val"]["kendall"] > 0.85
    assert abs(r["val"]["mae"] - r["baseline_val"]["mae"]) < 0.02


def test_irt_method_runs():
    r = distill(synth(M=60, N=400), n=40, seed=5, method="irt")
    assert len(r["selected"]) == 40 and r["val"]["mae"] < 0.08


def test_anchor_method_runs():
    r = distill(synth(M=60, N=400), n=40, seed=5, method="anchor")
    assert len(r["selected"]) == 40 and abs(sum(r["weights"].values()) - 1) < 1e-6


def test_kendall_basic():
    assert _kendall([1, 2, 3], [1, 2, 3]) == 1.0 and _kendall([1, 2, 3], [3, 2, 1]) == -1.0
