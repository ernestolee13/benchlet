"""씨앗 5과제(state·options·label 구식 스키마)를 확장 형식으로 바꾼다. 파일은 건드리지 않는다.

구식 이진 항목은 label 1 이 options[0] 이다(run.py 의 채점식 (p>=0.5)==(label==1), p=P(options[0])).
그래서 target = 0 if label == 1 else 1. 다지는 label_index 가 그대로 target.
"""
from __future__ import annotations

import json

# 구식 과제별 입력 조립. legacy-seed 템플릿은 metadata.legacy.state 로 원래 프롬프트를 다시 만든다.
def _state_text(task: str, st: dict) -> str:
    if task == "editorial-norm":
        return f"기업: {st.get('company','')}\n분류: {st.get('category','')}\n요약: {st.get('summary','')}"
    if task == "derivation-check":
        return f"요약: {st.get('summary','')}\n주장: {st.get('claim','')}"
    if task == "option-fit":
        return (f"질문: {st.get('prompt','')}\n선택지 A: {st.get('option_a','')}\n"
                f"선택지 B: {st.get('option_b','')}")
    if task == "guideline-compliance":
        return f"장면: {st.get('scene','')}"
    if task in ("route-selection",):
        return f"질의: {st.get('query','')}"
    if task == "t2-subcategory":
        return (f"기업: {st.get('company','')}\n헤드라인: {st.get('headline','')}\n"
                f"요약: {st.get('summary','')}")
    if task == "t3-text-grounded":
        return f"요약: {st.get('summary','')}"
    # 모르는 과제: 키: 값 줄로
    return "\n".join(f"{k}: {v}" for k, v in st.items())


def is_legacy_item(it: dict) -> bool:
    return "options" in it and "label" in it and "choices" not in it


_CLASS_KEYS = ("violation_class", "defect", "question_key", "label_route", "condition")
_EVIDENCE_KEYS = ("derivation", "mismatch", "defect_desc", "violation_rule", "verify_rule", "evidence")
_META_SKIP = {"id", "task", "type", "state", "question", "options", "label", "label_index",
              "label_source", "difficulty", "norm", "rule", "n_options"}


def adapt_legacy_item(it: dict) -> dict:
    task = it.get("task", "")
    st = it.get("state") or {}
    options = list(it["options"])
    typ = it.get("type") or ("binary" if len(options) == 2 else "multiclass")
    if typ == "binary":
        target = 0 if int(it["label"]) == 1 else 1
    else:
        target = int(it["label_index"]) if "label_index" in it else options.index(it["label"])
    rule = it.get("norm") or it.get("rule")
    question = it.get("question", "")
    cls = None
    for k in _CLASS_KEYS:
        if it.get(k) is not None:
            cls = str(it[k])
            break
    if cls is None and task == "derivation-check" and it.get("difficulty"):
        cls = str(it["difficulty"])          # D1·D2·D3 는 도출 유형이라 클래스로 쓴다
    ev = None
    for k in _EVIDENCE_KEYS:
        v = it.get(k)
        if v:
            ev = v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)
            break
    meta = {k: v for k, v in it.items() if k not in _META_SKIP}
    meta["legacy"] = {"task": task, "state": st, "norm": it.get("norm"), "rule": it.get("rule"),
                      "label": it.get("label"), "label_index": it.get("label_index")}
    diff = it.get("difficulty")
    return {
        "id": it.get("id"),
        "input": _state_text(task, st),
        "question": f"{question}\n\n{rule}" if rule else question,
        "choices": options,
        "target": target,
        "type": typ,
        "label_source": it.get("label_source", "judged"),
        "class": cls,
        "difficulty": diff if diff not in (None, "n/a") else None,
        "cluster": it.get("pair_id") or it.get("source_event_id") or it.get("source_question_id"),
        "evidence": ev,
        "provenance": {},          # 구식 파일엔 provenance 가 없다. 검사 5 가 이걸 플래그한다
        "metadata": meta,
    }
