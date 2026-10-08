"""검사 9 v0: 이진 질문의 극성과 choices[0] 의 뜻이 같은지 어간 대조로 본다(LLM 없음).

질문 「…위반하는가」의 「예」는 choices[0] 이어야 한다. 「맞는가」인데 choices 가 [어긋난다, 맞는다] 면
어간 「맞」이 choices[1] 에만 있으므로 뒤집힘이다(option-fit Jev 4.2% 교훈).
"""
from __future__ import annotations

import re

AFFIRM = {"예", "네", "그렇다", "맞다", "yes", "true", "있다"}
NEGATE = {"아니오", "아니요", "아니다", "no", "false", "없다", "틀리다"}
# 질문 종결 어미. 앞의 어간을 남긴다
_ENDINGS = re.compile(r"(?:하는가|되는가|있는가|없는가|는가|은가|인가|한가|나요|는지|까)\s*[?？.]?\s*$")
_STRIP = re.compile(r"(?:하|되|되어|어|아|나|이)$")


def question_stem(question: str) -> str | None:
    """첫 문장의 마지막 어절에서 종결 어미를 떼고 어간을 돌려준다."""
    first = re.split(r"[.。]\s+|\n", question.strip())[0].strip()
    m = _ENDINGS.search(first)
    if not m:
        return None
    body = first[: m.start()].rstrip()
    last = body.split()[-1] if body.split() else ""
    # 「남아 있는가」→ 어미 자체가 「있는가」이면 어간은 「있」
    if m.group(0).strip().startswith("있"):
        return "있"
    if m.group(0).strip().startswith("없"):
        return "없"
    last = re.sub(r"[「」\"']", "", last)
    stem = _STRIP.sub("", last)
    return stem or None


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def check_polarity(question: str, choices: list) -> dict:
    """반환: {status: ok|flip|unknown, reason}. flip 이 강한 플래그, unknown 은 사람·LLM 확인."""
    if len(choices) != 2:
        return {"status": "ok", "reason": "이진 아님"}
    c0, c1 = _norm(str(choices[0])), _norm(str(choices[1]))
    stem = question_stem(question)
    if c0 in NEGATE and c1 in AFFIRM:
        return {"status": "flip", "reason": f"choices[0]={choices[0]} 가 부정, choices[1]={choices[1]} 가 긍정"}
    if stem:
        in0, in1 = stem in c0, stem in c1
        if in0 and not in1:
            return {"status": "ok", "reason": f"어간 「{stem}」이 choices[0] 에 있음"}
        if in1 and not in0:
            return {"status": "flip", "reason": f"질문 어간 「{stem}」이 choices[1]={choices[1]} 에만 있음. 질문의 「예」가 target 0 이 아니다"}
        if in0 and in1:
            # 「필요/불필요」「맞다/안 맞다」처럼 choices[1] 이 어간 앞에 부정 형태소를 붙인 꼴, 또는 「도출된다/도출되지 않는다」처럼 뒤에 붙인 꼴
            neg_pre = lambda c: re.search(r"(?:불|비|무|미|안|않|못)" + re.escape(stem), c)
            neg_post = lambda c: re.search(re.escape(stem) + r"[가-힣]*?(?:지않|지못|안되|없)", c)
            if (neg_pre(c1) or neg_post(c1)) and not (neg_pre(c0) or neg_post(c0)):
                return {"status": "ok", "reason": f"어간 「{stem}」 양쪽, choices[1] 이 부정형"}
            if (neg_pre(c0) or neg_post(c0)) and not (neg_pre(c1) or neg_post(c1)):
                return {"status": "flip", "reason": f"choices[0]={choices[0]} 가 어간 「{stem}」의 부정형"}
            if re.search(r"(?:불|비|무|미|안|않|못)" + re.escape(stem), c0) and not re.search(r"(?:불|비|무|미|안|않|못)" + re.escape(stem), c1):
                return {"status": "flip", "reason": f"choices[0]={choices[0]} 가 어간 「{stem}」의 부정형"}
            return {"status": "unknown", "reason": f"어간 「{stem}」이 양쪽 선택지에 있음"}
    if c0 in AFFIRM and c1 in NEGATE:
        return {"status": "ok", "reason": "범용 긍정/부정 쌍이고 순서가 맞음"}
    return {"status": "unknown", "reason": f"어간 「{stem}」을 선택지와 대조할 수 없음. 사람 또는 LLM 확인"}
