"""검수 검사 v0: PRD 6절의 1·2·5·7·8·9·10 과 11(덤프). 플래그만 하고 판정은 사람이 한다."""
from __future__ import annotations

import math
import random
import re
from collections import Counter, defaultdict

from ..schema.load import Bench
from ..schema.polarity import check_polarity
from ..stats.metrics import best_surface_feature
from .queue import Flag, ReviewReport, CHECK_NAMES
from .results import RunResults

SURFACE_FLAG = 0.70
SURFACE_STRONG = 0.85


def _y(it: dict) -> int:
    """이진 양성(target 0) = 1."""
    return 1 if it["target"] == 0 else 0


# ── 1 교차 패밀리 불일치 ─────────────────────────────────────────────────────
def check_1(bench: Bench, res: RunResults) -> list:
    flags = []
    fam = res.families()
    for it in bench.items:
        d = res.by_item.get(it["id"])
        if not d:
            continue
        answered = {a: v for a, v in d.items() if v["hit"] is not None}
        if len(answered) < 2:
            continue
        wrong = [a for a, v in answered.items() if v["hit"] == 0]
        frac = len(wrong) / len(answered)
        wrong_fams = sorted({fam.get(a, a) for a in wrong})
        if frac >= 0.75 and len(wrong_fams) >= 2:
            strength = "strong"
        elif frac >= 0.5 and len(wrong) >= 2 and len(wrong_fams) >= 2:
            strength = "medium" if len(answered) <= 3 else "weak"
        else:
            continue
        flags.append(Flag(1, CHECK_NAMES[1], strength,
                          f"{len(wrong)}/{len(answered)} 팔({', '.join(wrong_fams)} 패밀리)이 키와 다르게 답함. "
                          f"class={it.get('class')} target={it['choices'][it['target']]}. 라벨 또는 질문을 의심",
                          it["id"], {"wrong_arms": wrong, "class": it.get("class")}))
    return flags


# ── 2 오답 쏠림 · 클래스 전멸/만점 ────────────────────────────────────────────
def check_2(bench: Bench, res: RunResults) -> list:
    flags = []
    # (a) 다지: 같은 오답으로 몰림
    for it in bench.items:
        if it["type"] == "binary":
            continue
        d = res.by_item.get(it["id"])
        if not d:
            continue
        wrong = [v["pred"] for v in d.values() if v["hit"] == 0 and v["pred"] is not None]
        if len(wrong) < 2:
            continue
        opt, cnt = Counter(wrong).most_common(1)[0]
        if cnt >= 2:
            flags.append(Flag(2, CHECK_NAMES[2], "strong" if cnt >= 3 else "medium",
                              f"{cnt}팔이 같은 오답 「{it['choices'][opt]}」로 몰림 (정답 「{it['choices'][it['target']]}」). "
                              f"정답이 둘일 가능성(유일해 검증)",
                              it["id"], {"converged_option": it["choices"][opt], "count": cnt}))
    # (b) 클래스·질문 단위 전멸/만점
    groups = defaultdict(list)
    for it in bench.items:
        groups[("class", it.get("class") or "-")].append(it)
        groups[("question", it["question"][:40])].append(it)
    for (kind, key), its in groups.items():
        if len(its) < 3:
            continue
        per_arm = defaultdict(lambda: [0, 0])
        for it in its:
            d = res.by_item.get(it["id"]) or {}
            for a, v in d.items():
                if v["hit"] is not None:
                    per_arm[a][0] += v["hit"]; per_arm[a][1] += 1
        if len(per_arm) < 2:
            continue
        accs = {a: h / n for a, (h, n) in per_arm.items() if n}
        if all(x == 0 for x in accs.values()):
            flags.append(Flag(2, CHECK_NAMES[2], "strong",
                              f"{kind}={key}: 전 팔 전멸 ({len(its)}건, 팔 {len(accs)}). soft 규칙 이진화·오라벨·질문 결함 의심",
                              None, {kind: key, "n": len(its)}))
        elif kind == "class" and all(x == 1 for x in accs.values()) and len(its) >= 5:
            flags.append(Flag(2, CHECK_NAMES[2], "medium",
                              f"{kind}={key}: 전 팔 만점 ({len(its)}건, 팔 {len(accs)}). 자명한 클래스인지 확인(음성 자명성)",
                              None, {kind: key, "n": len(its)}))
    return flags


# ── 5 순환 ───────────────────────────────────────────────────────────────────
_SAME = re.compile(r"same script|same code|같은 (?:스크립트|코드)|동일 (?:스크립트|코드)|생성기와 같", re.I)


def check_5(bench: Bench) -> list:
    flags = []
    n = len(bench.items)
    no_prov = [it["id"] for it in bench.items if not it.get("provenance")]
    if len(no_prov) == n:
        flags.append(Flag(5, CHECK_NAMES[5], "medium",
                          "provenance 가 없다(생성기·검증기·읽은 사람 미기재). 자기 검증인지 알 수 없다", None))
        return flags
    gens = Counter((it.get("provenance") or {}).get("generator") for it in bench.items)
    vers = Counter((it.get("provenance") or {}).get("verifier") for it in bench.items)
    for gen, _ in gens.items():
        for ver, cnt in vers.items():
            if ver in (None, "", "none"):
                flags.append(Flag(5, CHECK_NAMES[5], "medium",
                                  f"검증기 미기재 {cnt}건(생성기 {gen}). 검증기가 없으면 라벨은 자기 검증이다", None))
                continue
            g = str(gen or "").split("@")[0]
            v = str(ver)
            if (g and g == v) or _SAME.search(v) or (g and g.replace(".py", "") in v and "build" in g):
                flags.append(Flag(5, CHECK_NAMES[5], "strong",
                                  f"생성기와 검증기가 같은 코드 경로: generator={gen} verifier={v[:80]}. 「불일치 0건」은 증거가 아니다", None))
    human = sum(1 for it in bench.items if (it.get("provenance") or {}).get("read_by_human"))
    if human == 0:
        flags.append(Flag(5, CHECK_NAMES[5], "medium", f"사람이 읽은 항목 0/{n} (read_by_human). 에이전트가 읽은 것은 사람 검수가 아니다", None))
    rev = (bench.manifest.get("review") or {})
    if rev and rev.get("checks_run", 0) == 0:
        flags.append(Flag(5, CHECK_NAMES[5], "weak", "매니페스트 review.checks_run = 0", None))
    return flags


# ── 7 음성 자명성 ─────────────────────────────────────────────────────────────
def check_7(bench: Bench, sections: dict) -> list:
    flags = []
    groups = defaultdict(list)
    for it in bench.items:
        if it["type"] == "binary":
            groups[it["question"]].append(it)
        else:
            # 다지: 클래스마다 일대다(one-vs-rest)
            for k in range(len(it["choices"])):
                groups[f"{it['question']} [{it['choices'][k]} 대 나머지]"].append((it, k))
    rows_md = ["| 질문(앞 40자) | n | 다수결 | 최선 특징 | 정확도 | 임계 |", "|---|---|---|---|---|---|"]
    for q, its in groups.items():
        if len(its) < 6:
            continue
        if isinstance(its[0], tuple):
            r = best_surface_feature([it["input"] for it, _ in its], [int(it["target"] == k) for it, k in its])
        else:
            r = best_surface_feature([it["input"] for it in its], [_y(it) for it in its])
        b = r.get("best")
        if not b:
            continue
        rows_md.append(f"| {q.strip().splitlines()[0][:40]} | {len(its)} | {r['majority']:.0%} | {b['feature']} | {b['acc']:.0%} | {b['direction']}{b['threshold']} |")
        if b["acc"] >= SURFACE_FLAG and b["acc"] > r["majority"] + (0.05 if "대 나머지" not in q else 0.10):
            flags.append(Flag(7, CHECK_NAMES[7], "strong" if b["acc"] >= SURFACE_STRONG else "medium",
                              f"단일 표면 특징 「{b['feature']}」({b['direction']}{b['threshold']})만으로 정확도 {b['acc']:.0%} "
                              f"(다수결 {r['majority']:.0%}, n={len(its)}). 질문 「{q.strip().splitlines()[0][:30]}」. 그 특징을 깨는 항목을 더한다",
                              None, {"feature": b["feature"], "acc": b["acc"], "question": q[:60],
                                     "table": r["table"][:5]}))
    if len(rows_md) > 2:
        sections["검사 7 표면 특징 최선 정확도 (질문별)"] = "\n".join(rows_md)
    return flags


# ── 8 유일해 (규칙 매처) ──────────────────────────────────────────────────────
def _compile_rules(rules: dict) -> dict:
    out = {}
    for choice, pats in (rules or {}).items():
        if isinstance(pats, str):
            pats = [pats]
        out[str(choice)] = [re.compile(p) for p in pats]
    return out


def check_8(bench: Bench, rules: dict | None = None) -> list:
    flags = []
    rules = _compile_rules(rules if rules is not None else bench.rules)
    if not rules:
        return flags
    for it in bench.items:
        text = it["input"]
        matched = [c for c, pats in rules.items() if any(p.search(text) for p in pats)]
        target_name = str(it["choices"][it["target"]])
        if it["type"] == "binary":
            # 이진: 매처는 choices[0](양성) 의 위반 어휘. 음성이 걸리면 오라벨 의심
            if it["target"] == 1 and matched:
                flags.append(Flag(8, CHECK_NAMES[8], "strong",
                                  f"음성 항목에 양성 규칙 매처가 걸림: {matched}. 오라벨 의심", it["id"], {"matched": matched}))
            continue
        if len(matched) >= 2:
            flags.append(Flag(8, CHECK_NAMES[8], "strong",
                              f"규칙 {len(matched)}개가 동시 성립 {matched} (정답 「{target_name}」). 우선순위 한 줄이 필요하다",
                              it["id"], {"matched": matched}))
        elif not matched:
            flags.append(Flag(8, CHECK_NAMES[8], "medium", f"어느 규칙도 안 맞음 (정답 「{target_name}」)", it["id"], {}))
        elif matched[0] != target_name:
            flags.append(Flag(8, CHECK_NAMES[8], "strong",
                              f"규칙 매처는 「{matched[0]}」인데 정답은 「{target_name}」", it["id"], {"matched": matched}))
    return flags


# ── 9 극성 ────────────────────────────────────────────────────────────────────
def check_9(bench: Bench, llm=None) -> list:
    flags = []
    seen = set()
    distinct = {tuple(it["choices"]) for it in bench.items if it.get("type") == "binary"}
    if len(distinct) > 3:
        return [Flag(9, CHECK_NAMES[9], "weak", f"선택지가 항목마다 다르다({len(distinct)}종, WinoGrande 꼴). 질문 극성 검사는 해당 없음. 러너의 극성 반전은 그대로 적용된다", None)]
    for it in bench.items:
        if it["type"] != "binary":
            continue
        key = (it["question"], tuple(it["choices"]))
        if key in seen:
            continue
        seen.add(key)
        p = check_polarity(it["question"], it["choices"])
        q1 = it["question"].strip().splitlines()[0][:50]
        if p["status"] == "flip":
            flags.append(Flag(9, CHECK_NAMES[9], "strong", f"「{q1}」 choices={it['choices']}: {p['reason']}", None, p))
        elif p["status"] == "unknown":
            if llm is not None:
                try:
                    yes_idx = llm(it["question"], it["choices"])
                except Exception as e:      # noqa: BLE001
                    yes_idx = None
                    p["llm_error"] = type(e).__name__
                if yes_idx == 1:
                    flags.append(Flag(9, CHECK_NAMES[9], "strong", f"LLM: 질문의 「예」가 choices[1]={it['choices'][1]}", None, p))
                elif yes_idx == 0:
                    continue
            flags.append(Flag(9, CHECK_NAMES[9], "weak", f"「{q1}」 choices={it['choices']}: {p['reason']}", None, p))
    return flags


# ── 10 분포 ───────────────────────────────────────────────────────────────────
def check_10(bench: Bench) -> list:
    flags = []
    items = bench.items
    n = len(items)
    if n == 0:
        return flags
    if bench.type == "binary":
        pos = sum(_y(it) for it in items)
        if not 0.3 <= pos / n <= 0.7:
            flags.append(Flag(10, CHECK_NAMES[10], "medium", f"라벨 비율 치우침: 양성 {pos}/{n} ({pos / n:.0%})", None))
    else:
        cnt = Counter(it["target"] for it in items)
        k = max(len(it["choices"]) for it in items)
        top = cnt.most_common(1)[0]
        if top[1] / n > 2.0 / k:
            flags.append(Flag(10, CHECK_NAMES[10], "medium", f"정답 위치 치우침: 인덱스 {top[0]} 가 {top[1]}/{n} (선택지 {k}개)", None))
    cls = Counter(it.get("class") or "-" for it in items)
    small = {c: v for c, v in cls.items() if v < 8 and c != "-"}
    if small:
        flags.append(Flag(10, CHECK_NAMES[10], "weak", f"클래스별 8건 미만: {small}", None))
    clus = Counter(it.get("cluster") for it in items if it.get("cluster"))
    if clus:
        c, v = clus.most_common(1)[0]
        if v > max(3, 0.1 * n):
            flags.append(Flag(10, CHECK_NAMES[10], "weak", f"클러스터 {c} 가 {v}건 ({v / n:.0%}). 클러스터 표준오차 필요", None))
    # 메타데이터·출처 필드가 라벨을 완전히 가르는가 (작성자 문장 편향·출처 신호)
    ys = [it["target"] for it in items]
    if len(set(ys)) >= 2:
        for key, getter in _meta_fields(items):
            vals = [getter(it) for it in items]
            distinct = set(vals)
            if len(distinct) < 2 or len(distinct) > 6:
                continue          # 항목마다 다른 값(id·원본 번호)은 상관을 잴 수 없다
            if all(str(v) == str(it.get("class")) for v, it in zip(vals, items)):
                continue          # class 그 자체
            table = defaultdict(Counter)
            for v, y in zip(vals, ys):
                table[v][y] += 1
            if any(sum(c.values()) < 3 for c in table.values()):
                continue
            pure = all(len(cnt) == 1 for cnt in table.values())
            if pure:
                desc = "; ".join(f"{k}→target {list(c)[0]} ({sum(c.values())}건)" for k, c in list(table.items())[:4])
                strength = "medium" if key == "label_source" else "strong"
                flags.append(Flag(10, CHECK_NAMES[10], strength,
                                  f"필드 「{key}」가 라벨을 완전히 가른다: {desc}. 음성과 양성의 원천이 다르면 출처가 라벨 신호가 된다",
                                  None, {"field": key}))
                continue
            # 출처 편중: 어떤 값이 한 클래스의 절반 이상을 차지하는데 다른 클래스에는 거의 없다(10% 미만)
            tot = Counter(ys)
            for v, cnt in table.items():
                for t, c in cnt.items():
                    if c < 3 or c < 0.5 * tot[t]:
                        continue
                    others = sum(cnt.values()) - c
                    others_n = n - tot[t]
                    if others_n and others / others_n < 0.10:
                        flags.append(Flag(10, CHECK_NAMES[10], "medium",
                                          f"필드 「{key}」={v} 가 target {t}({items[ys.index(t)]['choices'][t]})의 {c / tot[t]:.0%}({c}건)인데 "
                                          f"다른 클래스에는 {others}/{others_n}건뿐이다. 출처(실제/심음)가 클래스 신호일 수 있다",
                                          None, {"field": key, "value": str(v), "target": t}))
    if all(it.get("label_source") in ("judged", "agent", None) for it in items) and n > 0:
        flags.append(Flag(10, CHECK_NAMES[10], "weak", "label_source 가 전부 judged·agent(미기재 포함). 기계·규칙 근거가 없어 주 분석에서 따로 보고한다. agent 는 사람 검수 뒤 judged 로 바꾼다", None))
    return flags


def _meta_fields(items: list):
    keys = set()
    for it in items:
        keys.update((it.get("metadata") or {}).keys())
        keys.update((it.get("provenance") or {}).keys())
    out = [("label_source", lambda it: it.get("label_source"))]
    for k in sorted(keys):
        if k in ("legacy", "state", "note", "read_by", "read_by_agent", "read_by_human", "source_row", "plant",
                 "defect", "defect_desc", "violation_class", "violation_rule", "mismatch", "seed", "generator", "verifier"):
            continue
        def getter(it, k=k):
            md = it.get("metadata") or {}
            pv = it.get("provenance") or {}
            if k in md:
                v = md[k]
            elif k in pv:
                v = pv[k]
            else:
                return "(없음)"
            if isinstance(v, (dict, list)):
                return "(있음)"
            if isinstance(v, str) and len(v) > 40:
                return "(있음)"
            return v
        out.append((k, getter))
    return out


# ── 11 채점기 표본 덤프 ───────────────────────────────────────────────────────
def check_11(bench: Bench, sections: dict, k: int = 20, seed: int = 20260930) -> None:
    rng = random.Random(seed)
    by_cls = defaultdict(list)
    for it in bench.items:
        by_cls[it.get("class") or "-"].append(it)
    picked = []
    classes = sorted(by_cls)
    while len(picked) < min(k, len(bench.items)):
        for c in classes:
            if by_cls[c] and len(picked) < k:
                picked.append(by_cls[c].pop(rng.randrange(len(by_cls[c]))))
        if not any(by_cls.values()):
            break
    L = ["사람이 본다. 라벨과 근거가 입력과 맞는지, 파서·검증기가 조각을 놓치지 않았는지 20건을 눈으로 확인한다.", "",
         "| id | class | 정답 | evidence | 입력(앞 160자) |", "|---|---|---|---|---|"]
    for it in picked:
        ev = str(it.get("evidence") or "(없음)").replace("\n", " ").replace("|", "¦")[:120]
        inp = str(it["input"]).replace("\n", " ").replace("|", "¦")[:160]
        L.append(f"| {it['id']} | {it.get('class') or '-'} | {it['choices'][it['target']]} | {ev} | {inp} |")
    sections["검사 11 채점기·검증기 표본 덤프 (20건)"] = "\n".join(L)


CHECKS = {1: "결과 필요", 2: "결과 필요", 5: "규칙", 7: "규칙", 8: "규칙 매처 필요", 9: "규칙(+LLM 선택)", 10: "규칙", 11: "덤프"}


def run_checks(bench: Bench, results: RunResults | None = None, checks: list | None = None,
               rules: dict | None = None, llm=None, dump_k: int = 20) -> ReviewReport:
    want = checks or [1, 2, 5, 7, 8, 9, 10, 11]
    rep = ReviewReport(bench=bench.name, n_items=len(bench.items))
    for c in want:
        if c in (1, 2):
            if results is None:
                rep.skipped[c] = "실행 결과가 없다(results/<bench>-run.json 또는 --results)"
                continue
            rep.flags += check_1(bench, results) if c == 1 else check_2(bench, results)
        elif c == 5:
            rep.flags += check_5(bench)
        elif c == 7:
            rep.flags += check_7(bench, rep.sections)
        elif c == 8:
            r = rules if rules is not None else bench.rules
            if not r:
                rep.skipped[c] = "규칙 매처가 없다(bench.yaml 또는 manifest 의 rules: {선택지: [정규식]})"
                continue
            rep.flags += check_8(bench, r)
        elif c == 9:
            rep.flags += check_9(bench, llm)
        elif c == 10:
            rep.flags += check_10(bench)
        elif c == 11:
            check_11(bench, rep.sections, dump_k)
        else:
            rep.skipped[c] = "v0 에 없는 검사(3·4·6 은 2단계)"
            continue
        rep.checks_run.append(c)
    return rep
