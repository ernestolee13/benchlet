"""네트워크 없이: 선택지가 글자 수를 넘는 벤치의 라벨 팔, Anthropic 팔 해석과 응답 모양, 라벨 매칭."""
import json

from benchlet.runner.arms import resolve_arms
from benchlet.runner.client import ChatClient, AnthropicClient, LETTERS, match_label, anthropic_price
from benchlet.runner.run import call_arm, effective_mode
from benchlet.runner.templates import generic_label

LABELS = ["card_arrival", "card_not_working", "lost_or_stolen_card", "getting_spare_card"] + [f"intent_{i:02d}" for i in range(20)]
ITEM = {"id": "x-0001", "input": "Can my daughter use one of my cards?", "question": "Classify the message.",
        "choices": LABELS, "target": 3, "type": "multiclass"}


def test_match_label_exact_normalized_and_json():
    assert match_label("getting_spare_card", LABELS) == 3
    assert match_label('"Getting Spare Card"\n', LABELS) == 3
    assert match_label(json.dumps({"label": "card_arrival"}), LABELS) == 0
    assert match_label("card", LABELS) is None            # 여러 라벨에 걸리면 못 고른다
    assert match_label("", LABELS) is None


def test_effective_mode_switches_to_label_above_letter_count():
    assert len(LABELS) > len(LETTERS)
    assert effective_mode(ITEM, "logprob") == "label"
    assert effective_mode(ITEM, "generative") == "label"
    assert effective_mode(ITEM, "typed") == "typed"
    small = dict(ITEM, choices=LABELS[:3], target=0)
    assert effective_mode(small, "logprob") == "logprob"


def test_anthropic_arm_resolves_without_openrouter_fields():
    a = resolve_arms(["anthropic:claude-opus-5-5"])[0]
    assert a["preset"] == "anthropic" and a["api_key_env"] == "ANTHROPIC_API_KEY" and a["mode"] == "generative"
    assert a["in_per_m"] == anthropic_price("claude-opus-5-5")[0] > 0
    assert anthropic_price("unknown-model") == (0.0, 0.0, 0.0, 0.0)


class FakeAnthropic(AnthropicClient):
    def __init__(self):
        super().__init__("https://api.anthropic.com/v1", "k")
        self.bodies = []

    def _post(self, url, body):
        self.bodies.append((url, body))
        if "output_config" in body:
            return {"content": [{"type": "text", "text": json.dumps({"label": "getting_spare_card"})}],
                    "usage": {"input_tokens": 50, "cache_read_input_tokens": 1900, "output_tokens": 12}, "stop_reason": "end_turn"}, 10, None
        return {"content": [{"type": "thinking", "thinking": "..."}, {"type": "text", "text": "B"}],
                "usage": {"input_tokens": 80, "output_tokens": 3}, "stop_reason": "end_turn"}, 10, None


def test_anthropic_label_arm_uses_schema_enum_cache_and_prices():
    c = FakeAnthropic()
    arm = resolve_arms(["anthropic:claude-opus-5-5"])[0]
    r = call_arm(c, arm, ITEM, "generic", "logprob")
    assert r["pred_index"] == 3 and r["err"] is None and r["answer_format"] == "json-schema-enum" and r["prob_source"] == "none"
    url, body = c.bodies[-1]
    assert url.endswith("/messages") and body["thinking"] == {"type": "disabled"} and "temperature" not in body
    assert body["output_config"]["format"]["schema"]["properties"]["label"]["enum"] == LABELS
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    pi, pcr, _, po = anthropic_price("claude-opus-5-5")
    assert abs(r["cost"] - (50 * pi + 1900 * pcr + 12 * po) / 1e6) < 1e-9 and r["in_tok"] == 1950


def test_anthropic_generative_letter_arm_reads_text_block_only():
    c = FakeAnthropic()
    arm = resolve_arms(["anthropic:claude-haiku-5-5"])[0]
    small = dict(ITEM, choices=["a", "b", "c"], target=1)
    r = call_arm(c, arm, small, "generic", "generative")
    assert r["pred_index"] is not None and r["err"] is None and r["prob_source"] == "none"


def test_anthropic_retries_without_thinking_on_400():
    class Rejecting(FakeAnthropic):
        def _post(self, url, body):
            if "thinking" in body:
                self.bodies.append((url, body)); return None, 5, "HTTP 400 thinking.type: disabled is not supported"
            return super()._post(url, body)
    c = Rejecting()
    arm = resolve_arms(["anthropic:claude-fable-5-1"])[0]
    r = call_arm(c, arm, ITEM, "generic", "label")
    assert r["err"] is None and r["pred_index"] == 3 and "thinking" not in c.bodies[-1][1]


class FakeChat(ChatClient):
    def _post(self, url, body):
        return {"choices": [{"message": {"content": "getting_spare_card\n"}}], "usage": {"prompt_tokens": 700}, "provider": "x"}, 7, None


def test_openai_compatible_label_arm_generates_label_name():
    c = FakeChat("https://openrouter.ai/api/v1", "k")
    arm = resolve_arms(["glm"])[0]
    r = call_arm(c, arm, ITEM, "generic", "logprob")
    assert r["pred_index"] == 3 and r["answer_format"] == "label-name" and r["order"] is None
    system, user = generic_label(ITEM)
    assert all(l in system for l in LABELS) and ITEM["input"] in user
