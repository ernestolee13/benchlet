"""프롬프트 템플릿. generic 은 확장 형식용, legacy-seed 는 씨앗 5과제의 run.py 프롬프트를 그대로 재현한다(수용 기준 4).

극성 반전(flip)·셔플은 여기서 결정한다. 작성자는 모른다.
"""
from __future__ import annotations

import json
import random

from .client import LETTERS


def shuffled_order(item: dict, template: str) -> list:
    """다지 선택지 제시 순서. generic 은 항목 id 시드로 결정론적 셔플, legacy 는 파일 순서(이미 셔플돼 있다)."""
    n = len(item["choices"])
    order = list(range(n))
    if template == "generic" and n > 2:
        random.Random(f"{item['id']}|{item['question'][:20]}").shuffle(order)
    return order


# ── generic ──────────────────────────────────────────────────────────────────
def generic_binary(item: dict, flip: bool) -> str:
    c0, c1 = item["choices"]
    a, b = (c1, c0) if flip else (c0, c1)
    return (f"{item['question']}\n\n---\n{item['input']}\n---\n\n"
            f"「{a}」이면 A, 「{b}」이면 B. 글자 하나만 답한다.")


def generic_choice(item: dict, order: list) -> str:
    opts = "\n".join(f"{LETTERS[i]}. {item['choices'][j]}" for i, j in enumerate(order))
    return f"{item['question']}\n\n---\n{item['input']}\n---\n\n{opts}\n\n글자 하나만 답한다."


def generic_jev(item: dict) -> tuple:
    """(state, questions, answer_key)"""
    if item["type"] == "binary":
        return item["input"], {"q": {"type": "noul", "instructions": item["question"]}}, "q"
    return item["input"], {"q": {"type": "choice", "instructions": item["question"],
                                 "criteria": {o: o for o in item["choices"]}}}, "q"


# ── legacy-seed (src/run.py 와 글자 단위로 같다) ─────────────────────────────
def legacy_binary(item: dict, flip: bool) -> str:
    lg = item["metadata"]["legacy"]
    t, st = lg["task"], lg["state"]
    if t == "editorial-norm":
        a, b = ("통과", "위반") if flip else ("위반", "통과")
        return (f"{lg['norm']}\n\n기업: {st['company']}\n분류: {st['category']}\n요약: {st['summary']}\n\n"
                f"{a}이면 A, {b}이면 B. 글자 하나만 답한다.")
    if t == "derivation-check":
        a, b = ("틀리다", "맞다") if flip else ("맞다", "틀리다")
        q = item["question"].split("\n\n")[0]
        return f"{q}\n\n요약: {st['summary']}\n주장: {st['claim']}\n\n{a}면 A, {b}면 B. 글자 하나만 답한다."
    if t == "option-fit":
        a, b = ("맞는다", "어긋난다") if flip else ("어긋난다", "맞는다")
        return (f"{lg['rule']}\n\n질문: {st['prompt']}\n선택지 A: {st['option_a']}\n선택지 B: {st['option_b']}\n\n"
                f"{a}면 A, {b}면 B. 글자 하나만 답한다.")
    if t == "guideline-compliance":
        a, b = ("준수", "위반") if flip else ("위반", "준수")
        return f"{lg['rule']}\n\n장면: {st['scene']}\n\n{a}면 A, {b}면 B. 글자 하나만 답한다."
    return generic_binary(item, flip)


def legacy_choice(item: dict, order: list) -> str:
    lg = item["metadata"]["legacy"]
    opts = "\n".join(f"{LETTERS[i]}. {item['choices'][j]}" for i, j in enumerate(order))
    if lg["task"] == "route-selection":
        return f"{lg['rule']}\n\n질의: {lg['state']['query']}\n\n{opts}\n\n글자 하나만 답한다."
    return generic_choice(item, order)


def legacy_jev(item: dict) -> tuple:
    lg = item["metadata"]["legacy"]
    q = item["question"].split("\n\n")[0]
    if item["type"] == "binary":
        instr = " ".join(x for x in (lg.get("norm"), lg.get("rule"), q) if x)
        return json.dumps(lg["state"], ensure_ascii=False), {"violation": {"type": "noul", "instructions": instr}}, "violation"
    return (json.dumps(lg["state"], ensure_ascii=False),
            {"choice_q": {"type": "choice", "instructions": (lg.get("rule") or "") + " " + q,
                          "criteria": {o: o for o in item["choices"]}}}, "choice_q")


def build(template: str):
    if template == "legacy-seed":
        return legacy_binary, legacy_choice, legacy_jev
    return generic_binary, generic_choice, generic_jev
