"""형식 로드·검증·극성·개인정보·구식 어댑터."""
import json

import pytest

from benchlet.schema import load_bench, validate_bench, scan_text
from benchlet.schema.legacy import adapt_legacy_item
from benchlet.schema.polarity import check_polarity

SEEDS = ["editorial-norm", "route-selection", "derivation-check", "option-fit", "guideline-compliance"]
SNS = ["sns-numbers-sourced", "sns-published-audit", "sns-q-option-fit", "sns-stale-schedule"]


@pytest.mark.parametrize("name", SEEDS + SNS)
def test_frozen_benches_validate_and_hash_match(root, name):
    b = load_bench(name, root)
    r = validate_bench(b, banned_terms=[], sha_file=root / "labels" / "SHA256SUMS")
    assert r.ok, r.summary_lines()
    assert any("일치" in i for i in r.info), "labels/SHA256SUMS 와 항목 해시가 같아야 한다"


def test_legacy_binary_target_mapping():
    it = {"task": "editorial-norm", "type": "binary", "state": {"company": "X", "category": "C", "summary": "S"},
          "question": "이 요약 문장이 편집 규범을 위반하는가", "norm": "N", "options": ["위반", "통과"], "label": 1,
          "violation_class": "W1", "label_source": "machine", "id": "n-0"}
    e = adapt_legacy_item(it)
    assert e["target"] == 0 and e["choices"] == ["위반", "통과"] and e["class"] == "W1"
    it["label"] = 0
    assert adapt_legacy_item(it)["target"] == 1


def test_minimal_format_expands(tmp_path):
    (tmp_path / "bench.yaml").write_text(
        "name: demo\nguide: 이 문장이 규칙을 위반하는가\nchoices: [위반, 통과]\nitems:\n"
        "  - {input: 'a', target: 0, evidence: e1, class: W1}\n  - {input: 'b', target: 1, evidence: e2, class: OK}\n",
        encoding="utf-8")
    b = load_bench(str(tmp_path), None)
    assert b.format == "minimal" and len(b.items) == 2
    assert b.items[0]["question"].startswith("이 문장이") and b.items[0]["type"] == "binary"
    assert b.items[1]["id"] == "demo-001" and b.items[1]["label_source"] == "judged"
    r = validate_bench(b, banned_terms=[])
    assert r.ok


def test_validate_catches_letter_prefix_target_range_dup(tmp_path):
    p = tmp_path / "x.jsonl"
    rows = [
        {"id": "a", "input": "같은 입력", "question": "규칙을 위반하는가", "choices": ["A. 위반", "통과"], "target": 0, "type": "binary"},
        {"id": "b", "input": "같은 입력", "question": "규칙을 위반하는가", "choices": ["위반", "통과"], "target": 2, "type": "binary"},
    ]
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows), encoding="utf-8")
    r = validate_bench(load_bench(str(p), None), banned_terms=[])
    msgs = " ".join(r.errors)
    assert "글자 접두" in msgs and "인덱스여야" in msgs and "중복 해시" in msgs


@pytest.mark.parametrize("q,choices,status", [
    ("이 요약 문장이 편집 규범을 위반하는가", ["위반", "통과"], "ok"),
    ("이 문항은 질문과 선택지가 서로 어긋나는가", ["어긋난다", "맞는다"], "ok"),
    ("이 문항은 질문과 선택지가 서로 맞는가", ["어긋난다", "맞는다"], "flip"),
    ("이 글 본문에 발행 전 지워야 할 잔재가 남아 있는가", ["있다", "없다"], "ok"),
    ("이 글 본문에 잔재가 남아 있는가", ["없다", "있다"], "flip"),
    ("요약의 수치로 볼 때 이 주장이 맞는가", ["맞다", "틀리다"], "ok"),
    ("이 문장은 지난 일정을 앞으로 있을 것처럼 쓴 문장인가", ["그렇다", "아니다"], "ok"),
])
def test_polarity_heuristic(q, choices, status):
    assert check_polarity(q, choices)["status"] == status


def test_pii_scan_hits_and_masks():
    hits = scan_text("문의는 someone@example.com 또는 010-1234-5678, 서버 192.168.0.12, 키 sk-or-v1-abcdefghijklmnopqrstuvwxyz0123")
    kinds = {h["kind"] for h in hits}
    assert {"email", "phone_kr", "ipv4_private", "api_key"} <= kinds
    assert all("*" in h["match"] for h in hits)
    assert scan_text("2026년 10.5% 상승, 3.2.1 버전") == []
    assert scan_text("회사 내부 문서", banned_terms=["회사 내부"])[0]["kind"] == "banned_term"
