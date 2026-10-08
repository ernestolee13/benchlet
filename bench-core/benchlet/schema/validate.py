"""형식 검증. 게시 전 유일한 관문이다. 스킬·CLI·웹이 같은 검사기를 쓴다."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ..config import load_banned_terms
from .load import Bench
from .pii import scan_items
from .polarity import check_polarity

LETTER_PREFIX = re.compile(r"^\s*[A-Za-z][.)]\s")
REQUIRED = ("id", "input", "question", "choices", "target", "type")
LABEL_SOURCES = {"machine", "constructed", "judged", "agent", "outcome"}


@dataclass
class ValidationResult:
    errors: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    info: list = field(default_factory=list)
    pii_hits: list = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and not self.pii_hits

    def summary_lines(self) -> list:
        out = [f"오류 {len(self.errors)} · 경고 {len(self.warnings)} · 개인정보 히트 {len(self.pii_hits)}"]
        out += [f"  E {e}" for e in self.errors]
        out += [f"  W {w}" for w in self.warnings]
        out += [f"  P {h['item_id']} {h['field']} {h['kind']} {h['match']}" for h in self.pii_hits]
        out += [f"  i {i}" for i in self.info]
        return out


def validate_manifest(bench: Bench) -> list:
    """매니페스트(.manifest.yaml 또는 bench.yaml)의 필수 필드와 항목 파일과의 일치. 반환: 오류 목록."""
    m = bench.manifest or {}
    errs = []
    if not m:
        return ["매니페스트가 없다 (benchlet manifest --bench <이름> 으로 만든다)"]
    for k in ("name", "version", "task_signature"):
        if k not in m or m[k] in (None, ""):
            errs.append(f"매니페스트에 {k} 없음")
    sig = m.get("task_signature") or {}
    for k in ("goal", "answer", "unit", "language"):
        if not sig.get(k):
            errs.append(f"task_signature.{k} 없음 (통제 어휘: goal compliance|classify|route|derive|gate|fit|rank, answer binary|choice(n)|ordinal(k), unit sentence|post|record|query|pair)")
    if m.get("items_sha256") and m["items_sha256"] not in (bench.items_sha256, "labels/SHA256SUMS"):
        errs.append(f"items_sha256 불일치: 매니페스트 {str(m['items_sha256'])[:12]} vs 항목 파일 {bench.items_sha256[:12]}")
    if bench.question and m.get("question") and str(m["question"]).strip() != bench.question.strip():
        errs.append("매니페스트 question 이 항목의 question 과 다르다")
    if bench.choices and m.get("choices") and list(map(str, m["choices"])) != list(map(str, bench.choices)):
        errs.append(f"매니페스트 choices {m['choices']} 가 항목의 {bench.choices} 와 다르다")
    if isinstance(m.get("n"), int) and m["n"] != len(bench.items):
        errs.append(f"매니페스트 n={m['n']} 이 항목 수 {len(bench.items)} 와 다르다")
    return errs


def validate_bench(bench: Bench, banned_terms: list | None = None, sha_file: Path | None = None) -> ValidationResult:
    r = ValidationResult()
    items = bench.items
    ids, hashes = {}, {}
    for n, it in enumerate(items):
        where = f"{it.get('id') or '#' + str(n)}"
        for k in REQUIRED:
            if it.get(k) is None or it.get(k) == "":
                r.errors.append(f"{where}: 필수 필드 {k} 없음")
        ch = it.get("choices") or []
        if not isinstance(ch, list) or len(ch) < 2:
            r.errors.append(f"{where}: choices 는 2개 이상이어야 한다")
            continue
        if len(set(map(str, ch))) != len(ch):
            r.errors.append(f"{where}: choices 중복 {ch}")
        # 글자 접두: 선택지들이 A./B./C. 처럼 서로 다른 글자로 시작할 때만. 모든 보기가 「a) ...」로 같은 글자면 본문의 소항목이다
        pref = [LETTER_PREFIX.match(str(c)) for c in ch]
        letters = {m.group(0).strip()[0].upper() for m in pref if m}
        n_pref = sum(1 for m in pref if m)
        if n_pref and not (n_pref == len(ch) and len(letters) == 1):
            r.errors.append(f"{where}: 선택지에 글자 접두 {sorted(letters)}. 셔플·재매핑은 러너가 하므로 이름만 쓴다")
        t = it.get("target")
        if not isinstance(t, int) or isinstance(t, bool) or not (0 <= t < len(ch)):
            r.errors.append(f"{where}: target={t!r} 는 choices 인덱스여야 한다 (0..{len(ch) - 1})")
        typ = it.get("type")
        if typ == "binary" and len(ch) != 2:
            r.errors.append(f"{where}: type=binary 인데 choices 가 {len(ch)}개")
        if typ not in ("binary", "multiclass", "route"):
            r.errors.append(f"{where}: type={typ!r} 는 binary|multiclass|route")
        if it.get("id") in ids:
            r.errors.append(f"{where}: id 중복")
        ids[it.get("id")] = n
        h = hashlib.sha1((str(it.get("input")) + "\x1f" + str(it.get("question"))).encode()).hexdigest()
        if h in hashes:
            r.errors.append(f"{where}: 입력·질문이 {hashes[h]} 와 같다(중복 해시)")
        hashes[h] = where
        ls = it.get("label_source")
        if ls not in LABEL_SOURCES:
            r.warnings.append(f"{where}: label_source={ls!r} (machine|constructed|judged|agent|outcome). 없으면 judged 로 본다")
    missing_ev = [it.get("id") for it in items if not it.get("evidence")]
    if missing_ev:
        r.warnings.append(f"evidence 없는 항목 {len(missing_ev)}/{len(items)} (근거 없는 항목은 검수가 안 된다): "
                          + ", ".join(map(str, missing_ev[:8])) + (" …" if len(missing_ev) > 8 else ""))
    missing_cls = sum(1 for it in items if not it.get("class"))
    if missing_cls:
        r.warnings.append(f"class 없는 항목 {missing_cls}/{len(items)} (실패 구조가 안 보인다)")
    # 극성 (이진, 질문별 한 번). 선택지가 항목마다 다르면(이름 둘 중 고르기) 해당 없음
    seen = set()
    varying = len({tuple(it["choices"]) for it in items if it.get("type") == "binary" and it.get("choices")}) > 3
    for it in items:
        if it.get("type") != "binary" or not it.get("choices") or varying:
            continue
        key = (it["question"], tuple(it["choices"]))
        if key in seen:
            continue
        seen.add(key)
        p = check_polarity(it["question"], it["choices"])
        q1 = it["question"].strip().splitlines()[0][:60]
        if p["status"] == "flip":
            r.errors.append(f"극성 뒤집힘: 「{q1}」 choices={it['choices']}. {p['reason']}")
        elif p["status"] == "unknown":
            r.warnings.append(f"극성 확인 불가: 「{q1}」 choices={it['choices']}. {p['reason']}")
    # 개인정보
    terms = load_banned_terms() if banned_terms is None else banned_terms
    r.pii_hits = scan_items(items, terms)
    # 해시 동결 대조
    if sha_file and sha_file.exists():
        for line in sha_file.read_text().splitlines():
            parts = line.split()
            if len(parts) == 2 and Path(parts[1]).name == bench.path.name:
                same = parts[0] == bench.items_sha256
                (r.info if same else r.warnings).append(
                    f"labels/SHA256SUMS {'일치' if same else '불일치'}: {bench.path.name} {bench.items_sha256[:12]}")
    if bench.manifest:
        try:
            from ..taxonomy import load as _tload, check_labels, labels_of
            from ..config import find_repo_root
            tax = _tload(find_repo_root(bench.path.parent))
            if tax:
                r.warnings += [f"분류: {w}" for w in check_labels(tax, labels_of(bench.manifest))]
        except Exception:        # noqa: BLE001
            pass
        merr = validate_manifest(bench)
        if bench.format == "minimal":
            r.warnings += [f"bench.yaml: {e} (게시 전에 채운다)" for e in merr]   # 최소 형식은 도구가 채우는 칸이라 경고
        else:
            r.errors += merr
        r.info.append("매니페스트 검사 포함")
    else:
        r.warnings.append("매니페스트 없음 (게시하려면 benchlet manifest --bench <이름> 으로 만든다)")
    r.info.append(f"형식 {bench.format} · 항목 {len(items)} · 유형 {bench.type} · sha256 {bench.items_sha256[:12]}")
    return r
