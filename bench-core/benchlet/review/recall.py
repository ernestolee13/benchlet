"""결함 12개 소급 재현률. 우리가 손으로 잡은 결함(skill/minibench-author/references/lessons.md)을 v0 검사가 잡는지.

    python3 -m benchlet.review.recall [--out docs/REVIEW_RECALL.md]

결함이 있던 판의 출처를 셋으로 구분한다. 실제 파일(tasks/retired, tasks/parked), 재구성(빌더 주석·원자료로 다시 만든 판),
근사(dist.md 기술대로 현재 판을 되돌린 것). 검사 1·2 는 4팔 결과가 있는 경우에만 「재현」으로 센다.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import yaml

from ..config import find_repo_root
from ..schema import load_bench, validate_bench
from .checks import run_checks
from .results import load_results, find_results

FIX = "tests/fixtures"


def _flags(rep, check: int, strength: str | None = None):
    return [f for f in rep.flags if f.check == check and (strength is None or f.strength == strength)]


def _results_for(root: Path, bench, fixture_stem: str | None = None):
    if fixture_stem:
        p = root / FIX / f"{fixture_stem}-run.json"
        return load_results(p, bench.items) if p.exists() else None
    p = find_results(bench.name, root)
    return load_results(p, bench.items) if p else None


def case_1(root):
    b = load_bench("sns-numbers-sourced", root)
    rep = run_checks(b, None, [5])
    hit = [f for f in _flags(rep, 5, "strong") if "같은 코드 경로" in f.message]
    return dict(no=1, title="자기 검증 순환 (「불일치 0건」을 파서로 확인)", check="5", source="실제 파일",
                fixture="tasks/sns-numbers-sourced.jsonl (provenance.verifier 「same script」)", caught=bool(hit),
                detail=hit[0].message if hit else "플래그 없음")


def case_2(root):
    b = load_bench(f"{FIX}/F02_amount_fragment.jsonl", root)
    res = _results_for(root, b, "F02_amount_fragment")
    rep = run_checks(b, res, [1, 11])
    dumped = "조각남" in rep.sections.get("검사 11 채점기·검증기 표본 덤프 (20건)", "")
    c1 = _flags(rep, 1)
    caught = bool(c1)
    return dict(no=2, title="복합 금액 조각남 (6조315억원 → 315억)", check="11 (덤프) · 1", source="재구성",
                fixture="F02_amount_fragment.jsonl 4건" + (" + 4팔 결과" if res else " (결과 없음)"),
                caught=caught,
                detail=(f"검사 1 이 {len(c1)}/4 건 플래그 ({', '.join(f.item_id for f in c1)})" if c1 else "검사 1 플래그 없음")
                       + f"; 검사 11 덤프에 조각 파서 근거 노출: {'예' if dumped else '아니오'}. 파서 자체의 오류는 사람이 덤프를 봐야 잡힌다")


def case_3(root):
    b = load_bench("route-selection", root)
    rules = json.loads("\n".join(l for l in (root / FIX / "F03_route_rules.yaml").read_text(encoding="utf-8").splitlines() if not l.startswith("#")))
    rep = run_checks(b, _results_for(root, b), [2, 8], rules=rules)
    multi = [f for f in _flags(rep, 8, "strong") if "동시 성립" in f.message]
    ad = [f for f in multi if "직접 폴더" in str(f.data.get("matched")) and "인덱스·로그" in str(f.data.get("matched"))]
    c2 = _flags(rep, 2)
    return dict(no=3, title="「정확히 하나만 만족」이 거짓 (라우트 A 와 D 동시 성립)", check="8 · 2", source="실제 파일 + 규칙 매처",
                fixture="tasks/route-selection.jsonl + F03_route_rules.yaml", caught=bool(ad),
                detail=f"검사 8: 규칙 동시 성립 {len(multi)}건, 그중 A·D 겹침 {len(ad)}건 ({', '.join(f.item_id for f in ad)}); "
                       f"검사 2(실행 결과): 같은 오답 쏠림 {len(c2)}건 ({', '.join(f.item_id for f in c2)})")


def case_4(root):
    b = load_bench(f"{FIX}/F04_letter_prefix.jsonl", root)
    r = validate_bench(b, banned_terms=[])
    hit = [e for e in r.errors if "글자 접두" in e]
    return dict(no=4, title="글자 충돌 (선택지 본문에 「C. 백링크」)", check="validate", source="재구성",
                fixture="F04_letter_prefix.jsonl 6건", caught=bool(hit), detail=f"validate 오류 {len(hit)}건, 예: {hit[0][:60] if hit else '-'}")


def case_5(root):
    b = load_bench("t3-text-grounded", root)
    rep = run_checks(b, None, [7])
    real = [f for f in _flags(rep, 7) if f.data.get("acc", 0) >= 0.95]
    b2 = load_bench(f"{FIX}/F05_t3_q3_obvious_negatives.jsonl", root)
    rep2 = run_checks(b2, None, [7])
    approx = _flags(rep2, 7, "strong")
    return dict(no=5, title="음성이 자명 (「100억을 넘는가」의 음성이 전부 값 없는 문장)", check="7", source="실제 파일 + 근사",
                fixture="tasks/retired/t3-text-grounded.jsonl; F05 (Q3 양성 + 값 없는 음성)", caught=bool(real or approx),
                detail=(f"실제 파일: {real[0].message[:70]}" if real else "실제 파일: 100% 특징 없음")
                       + (f"; 근사 Q3: {approx[0].data.get('feature')} {approx[0].data.get('acc'):.0%}" if approx else "; 근사 Q3: 플래그 없음"))


def case_6(root):
    return dict(no=6, title="심은 결함이 새는 네 가지 (비문·태 뒤집힘·주체 오류·내용 모순)", check="6 (v0 없음)", source="없음",
                fixture="-", caught=False, detail="검사 6(심은 구간을 가린 뒤 탐지)은 2단계. v0 에서는 사람만 잡는다")


def case_7(root):
    b = load_bench(f"{FIX}/F07_optionfit_v1_generic.jsonl", root)
    res = _results_for(root, b, "F07_optionfit_v1_generic")
    if res is None:
        return dict(no=7, title="선택지 교체가 무효 (범용 쌍이라 바꿔도 성립, V1 8건 중 6건 오라벨)", check="1", source="재구성",
                    fixture="F07 8건 (결과 없음)", caught=None, detail="4팔 결과가 없어 재현으로 세지 않는다")
    rep = run_checks(b, res, [1])
    c1 = [f for f in _flags(rep, 1) if f.strength in ("strong", "medium")]
    return dict(no=7, title="선택지 교체가 무효 (범용 쌍이라 바꿔도 성립, V1 8건 중 6건 오라벨)", check="1", source="재구성 + 4팔 재실행",
                fixture="F07_optionfit_v1_generic.jsonl 8건 + F07-run.json", caught=len(c1) >= 4,
                detail=f"8건 중 {len(c1)}건 플래그 (strong {sum(f.strength == 'strong' for f in c1)}): {', '.join(f.item_id for f in c1)}. "
                       f"원 결함은 8건 중 6건. 재구성은 「질문 어휘에 맞는 범용 쌍」을 붙인 것이라 원판 항목과 같지 않다")


def case_8(root):
    b = load_bench(f"{FIX}/F08_polarity_flip.jsonl", root)
    rep = run_checks(b, None, [9])
    hit = _flags(rep, 9, "strong")
    return dict(no=8, title="극성 불일치 (질문 「맞는가」인데 label 0 = 어긋남, Jev 4.2%)", check="9 · validate", source="재구성",
                fixture="F08_polarity_flip.jsonl", caught=bool(hit), detail=hit[0].message[:90] if hit else "플래그 없음")


def case_9(root):
    b = load_bench("guideline-compliance", root)
    rep = run_checks(b, _results_for(root, b), [2])
    hit = [f for f in _flags(rep, 2, "strong") if "P4-register" in f.message and "전멸" in f.message]
    return dict(no=9, title="soft 규칙 이진화 (반말 종결 P4-register, 네 팔 전부 0%)", check="2 (클래스 전멸)", source="실제 파일 + 실제 결과",
                fixture="tasks/guideline-compliance.jsonl + results/guide-run.json", caught=bool(hit),
                detail=hit[0].message if hit else "플래그 없음")


def case_10(root):
    b = load_bench(f"{FIX}/F10_clean_mislabel.jsonl", root)
    res = _results_for(root, b, "F10_clean_mislabel")
    if res is None:
        return dict(no=10, title="CLEAN 오라벨 (승인 요약에 lint 가 못 잡는 논평 「오히려」「뒤늦은」)", check="1", source="재구성",
                    fixture="F10 10건 (결과 없음)", caught=None, detail="4팔 결과가 없어 재현으로 세지 않는다")
    rep = run_checks(b, res, [1])
    c1 = [f for f in _flags(rep, 1) if f.strength in ("strong", "medium")]
    return dict(no=10, title="CLEAN 오라벨 (승인 요약에 lint 가 못 잡는 논평 「오히려」「뒤늦은」)", check="1", source="재구성 + 4팔 재실행",
                fixture="F10_clean_mislabel.jsonl 10건 + F10-run.json", caught=len(c1) >= 1,
                detail=f"10건 중 {len(c1)}건 플래그 (strong {sum(f.strength == 'strong' for f in c1)}): {', '.join(f.item_id for f in c1)}. "
                       f"원 결함은 CLEAN 30건 중 2건. 논평 어휘가 든 요약을 모델은 「위반」으로 읽는 비율이 이만큼이다")


def case_11(root):
    b = load_bench("guideline-compliance", root)
    rep = run_checks(b, None, [10])
    hit = [f for f in _flags(rep, 10, "strong") if "original" in f.message]
    return dict(no=11, title="작성자 문장 편향 (준수본 20건은 사람이 쓴 문장, 원자료가 아님)", check="10", source="실제 파일",
                fixture="tasks/guideline-compliance.jsonl (양성만 original 필드)", caught=bool(hit),
                detail=hit[0].message[:100] if hit else "플래그 없음")


def case_12(root):
    b = load_bench(f"{FIX}/F12_parser_agency.jsonl", root)
    res = _results_for(root, b, "F12_parser_agency")
    rep = run_checks(b, res, [1, 11])
    dumped = "법원" in rep.sections.get("검사 11 채점기·검증기 표본 덤프 (20건)", "")
    c1 = [f for f in _flags(rep, 1) if f.strength in ("strong", "medium")]
    return dict(no=12, title="파서 검증 라벨도 틀린다 (기관 목록에 법원 누락)", check="11 (덤프) · 1", source="재구성",
                fixture="F12_parser_agency.jsonl 6건" + (" + 4팔 결과" if res else " (결과 없음)"), caught=bool(c1),
                detail=(f"검사 1 이 {len(c1)}/6 건 플래그" if c1 else "검사 1 플래그 없음")
                       + f"; 검사 11 덤프에 노출: {'예' if dumped else '아니오'}. 파서 목록의 누락은 덤프를 사람이 봐야 잡힌다")


def sns_cases(root):
    out = []
    b = load_bench(f"{FIX}/FS1_sns_numbers_round1.jsonl", root)
    rep = run_checks(b, None, [7])
    f7 = _flags(rep, 7)
    out.append(dict(no="S1", title="sns 근거 없는 수치 1회차: 인용문 유무로 40/60", check="7", source="근사",
                    fixture="FS1 (심은 음성 10건 제거, 50건)", caught=(True if f7 else None),
                    detail=f7[0].message[:90] if f7 else "근사 판에서 재현 안 됨. 1회차의 원본 음성 30건 중 10건이 심은 음성으로 교체돼 남아 있지 않다. "
                           "현재 50건에서 본문 큰따옴표 유무 정확도는 27/50 이라 원판(40/60)과 다르다"))
    b = load_bench("sns-comment-safety", root)
    rep = run_checks(b, None, [7, 10])
    f10 = [f for f in _flags(rep, 10) if "label_source" in f.message]
    f7 = _flags(rep, 7)
    out.append(dict(no="S2", title="sns 댓글 분류: 출처(실제/심음)가 클래스 신호, 길이로 클래스가 갈림 (보류)", check="10 · 7", source="실제 파일",
                    fixture="tasks/parked/sns-comment-safety.jsonl", caught=bool(f10),
                    detail=(f10[0].message[:110] if f10 else "출처 플래그 없음")
                           + ("; 검사 7(일대다): " + f7[0].message[:60] if f7 else "; 검사 7 플래그 없음")))
    out.append(dict(no="S3", title="sns 질문·선택지 정합 1회차: 줄기 길이로 라벨이 갈림 (시간·장소 클래스)", check="7", source="없음",
                    fixture="-", caught=None, detail="1회차 파일이 남아 있지 않다. 검사 7 의 「길이」 특징이 잡는 종류이나 재현 불가"))
    return out


CASES = [case_1, case_2, case_3, case_4, case_5, case_6, case_7, case_8, case_9, case_10, case_11, case_12]


def run_all(root: Path | None = None) -> list:
    root = root or find_repo_root()
    rows = [c(root) for c in CASES]
    rows += sns_cases(root)
    return rows


def render(rows: list) -> str:
    main = [r for r in rows if isinstance(r["no"], int)]
    caught = sum(1 for r in main if r["caught"])
    unverified = sum(1 for r in main if r["caught"] is None)
    L = ["# 검수 검사 v0 의 결함 12개 소급 재현률", "",
         "우리가 236항목을 만들며 손으로 잡은 결함 12개(`skill/minibench-author/references/lessons.md`)를 v0 검사(1·2·5·7·8·9·10 + 11 덤프)가 소급으로 잡는지 쟀다.",
         "리포는 커밋 0개에서 시작해 옛 판이 git 에 없다. 결함이 있던 판의 출처를 「실제 파일 / 재구성 / 근사」로 구분했고, 검사 1·2 는 4팔 결과가 있는 경우에만 「재현」으로 셌다.",
         "생성 명령: `python3 -m benchlet.review.recall --out docs/REVIEW_RECALL.md`. 픽스처는 `tests/fixtures/build_fixtures.py` 가 만든다.", "",
         f"**재현률 {caught}/12** (검증 불가 {unverified}, 사람만 잡는 것 {12 - caught - unverified}).", "",
         "| # | 결함 | 검사 | 결함 판 출처 | 픽스처 | 잡았나 | 근거 |", "|---|---|---|---|---|---|---|"]
    for r in rows:
        mark = {True: "예", False: "아니오", None: "검증 불가"}[r["caught"]]
        L.append(f"| {r['no']} | {r['title']} | {r['check']} | {r['source']} | {r['fixture']} | {mark} | {r['detail'].replace('|', '¦')} |")
    L += ["", "## 읽는 법", "",
          "- 「예」는 그 검사가 결함 판에서 플래그를 냈다는 뜻이다. 판정은 여전히 사람이 한다.",
          "- 「아니오」는 v0 검사가 못 잡은 것이다. 검사 범위 밖(6), 검사 11 덤프로 사람 눈에 보이게만 한 것(2·12), 또는 재구성 판에서 검사 1 이 플래그를 내지 못한 것(7). 사람만 잡는다.",
          "- 「검증 불가」는 결함 판을 재구성했으나 4팔 결과가 없어 재현으로 세지 않은 것이다.",
          "- 「근사」는 dist.md 기술대로 현재 판을 되돌린 것이라 1회차 수치와 정확히 같지 않다.",
          "- S1~S3 은 sns 1회차 결함(PRD 11-3절)으로 12개 밖의 추가 사례다.", ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    rows = run_all()
    md = render(rows)
    print(md)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
