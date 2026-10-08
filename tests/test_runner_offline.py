"""네트워크 없이: legacy-seed 템플릿이 src/run.py 프롬프트와 글자 단위로 같은지(수용 기준 4), 확률 읽기, 스모크 항목 선택, 팔 해석."""
import json

import pytest

seed_run = pytest.importorskip("run")        # src/run.py (씨앗 러너). 공개 리포에는 없어 건너뛴다
from benchlet.runner.templates import legacy_binary, legacy_choice, legacy_jev
from benchlet.runner.client import read_probs
from benchlet.runner.arms import resolve_arms, arm_family
from benchlet.runner.smoke import pick_smoke_items
from benchlet.schema import load_bench

SHORT = {"editorial-norm": "norm", "derivation-check": "deriv", "option-fit": "fit", "guideline-compliance": "guide"}


@pytest.mark.parametrize("name", list(SHORT))
def test_legacy_binary_prompts_identical_to_seed_runner(root, name):
    b = load_bench(name, root)
    raw = [json.loads(l) for l in (root / "tasks" / f"{name}.jsonl").open(encoding="utf-8")]
    for it, old in zip(b.items, raw):
        for flip in (False, True):
            assert legacy_binary(it, flip) == seed_run.binary_prompt(old, flip)


def test_legacy_choice_prompt_and_jev_identical(root):
    b = load_bench("route-selection", root)
    raw = [json.loads(l) for l in (root / "tasks" / "route-selection.jsonl").open(encoding="utf-8")]
    for it, old in zip(b.items, raw):
        assert legacy_choice(it, list(range(5))) == seed_run.choice_prompt(old)
        state, q, key = legacy_jev(it)
        assert json.loads(state) == old["state"] and key == "choice_q"
        assert q[key]["criteria"] == {o: o for o in old["options"]}
    n = load_bench("editorial-norm", root)
    state, q, key = legacy_jev(n.items[0])
    assert key == "violation" and q[key]["instructions"].startswith(n.items[0]["metadata"]["legacy"]["norm"])


def test_read_probs_renormalizes_and_reports_mass():
    resp = {"choices": [{"logprobs": {"content": [{"top_logprobs": [
        {"token": "A", "logprob": -0.1}, {"token": "B", "logprob": -2.5}, {"token": "네", "logprob": -3.0}]}]}}]}
    probs, mass, note = read_probs(resp, 2)
    assert note == "ok" and abs(sum(probs) - 1) < 1e-9 and probs[0] > 0.9 and 0.9 < mass < 1.0
    assert read_probs({"choices": [{"message": {"content": "A"}}]}, 2)[2] == "logprobs 없음"
    assert read_probs({"choices": [{"logprobs": {"content": [{"top_logprobs": [{"token": "네", "logprob": -0.1}]}]}}]}, 2)[2] == "라벨 토큰이 상위에 없음"


def test_resolve_arms_presets_and_custom(monkeypatch):
    arms = resolve_arms(["qwen", "jev", "google/gemma-4-31b-it@coreweave"])
    assert arms[0]["extra_body"]["reasoning"] == {"enabled": False}
    assert arms[0]["extra_body"]["provider"]["only"] == ["parasail"] and arms[0]["extra_body"]["provider"]["allow_fallbacks"] is False
    assert arms[1]["mode"] == "typed" and arms[2]["family"] == "Gemma" and arms[2]["in_per_m"] == 0.09
    monkeypatch.setenv("BENCHLET_BASE_URL", "https://gateway.example/v1")
    monkeypatch.setenv("BENCHLET_EXTRA_BODY", '{"thinking": false}')
    c = resolve_arms(["custom:my/model"])[0]
    assert c["base_url"].endswith("/v1") and c["extra_body"] == {"thinking": False} and c["api_key_env"] == "BENCHLET_API_KEY"
    assert arm_family("deepseek/deepseek-v4-flash") == "DeepSeek"


def test_smoke_picks_3_pos_2_neg(root):
    b = load_bench("editorial-norm", root)
    items = pick_smoke_items(b)
    assert [it["target"] for it in items] == [0, 0, 0, 1, 1]


def test_polarity_suspect_rule():
    from benchlet.runner.smoke import polarity_suspect
    assert polarity_suspect({"qwen": {"usable": True, "smoke_acc": 0.0}, "jev": {"usable": True, "smoke_acc": 0.2}})
    assert not polarity_suspect({"qwen": {"usable": True, "smoke_acc": 0.0}, "jev": {"usable": True, "smoke_acc": 1.0}})
    assert not polarity_suspect({"qwen": {"usable": False, "smoke_acc": 0.0}})
