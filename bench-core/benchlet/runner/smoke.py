"""스모크. 어느 경로든 전량 실행 전에 강제한다.

항목 5건(뻔한 양성 3·음성 2)을 팔마다 돌려 (1) 로그확률이 실제로 오는지 (2) 추론 토큰 0 (3) provider 핀 일치
(4) 라벨 질량 ≥ 0.5 (5) 같은 항목 3회 재현성(P(A) 편차 ≤ 0.05) (6) 확률값 종류 수 를 잰다.
로그확률이 안 오면 생성 팔로 강등하고 prob_source=none. 편차·정밀도가 나쁘면 「못 쓴다 → 경로 0」.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from ..schema.load import Bench
from .arms import resolve_arms
from .run import make_client, call_arm
from .templates import build

SPREAD_MAX = 0.05
MASS_MIN = 0.5


@dataclass
class SmokeVerdict:
    arm: str
    mode: str                     # logprob | typed | generative
    usable: bool
    reasons: list = field(default_factory=list)
    has_logprobs: bool | None = None
    reasoning_tokens_zero: bool | None = None
    provider_match: bool | None = None
    mass_min: float | None = None
    spread: float | None = None
    distinct_p: int | None = None
    n_calls: int = 0
    smoke_acc: float | None = None
    cost: float = 0.0
    per_item: list = field(default_factory=list)      # [{id, target, pred, hit, p}] 어느 항목을 틀렸는지

    def to_dict(self) -> dict:
        return dict(self.__dict__)


def pick_smoke_items(bench: Bench, n_pos: int = 3, n_neg: int = 2) -> list:
    """뻔한 것 우선: difficulty easy → 나머지. 이진은 양성(target 0) 3·음성 2. 다지는 앞 5건."""
    items = bench.items
    if bench.type != "binary":
        return items[: n_pos + n_neg]
    def rank(it):
        return {"easy": 0, "medium": 1, "hard": 2}.get(it.get("difficulty") or "", 1)

    def diverse(cands, k):
        """easy 우선, 같은 클래스는 한 번씩 먼저 돈다(스모크가 한 클래스에 몰리지 않게)."""
        cands = sorted(cands, key=rank)
        out, seen = [], set()
        for it in cands:
            if len(out) >= k:
                break
            if it.get("class") not in seen:
                out.append(it); seen.add(it.get("class"))
        for it in cands:
            if len(out) >= k:
                break
            if it not in out:
                out.append(it)
        return out
    return diverse([it for it in items if it["target"] == 0], n_pos) + diverse([it for it in items if it["target"] == 1], n_neg)


def smoke_bench(bench: Bench, arm_specs: list, repeats: int = 3, progress: bool = True) -> dict:
    arms = resolve_arms(arm_specs)
    items = pick_smoke_items(bench)
    verdicts = {}
    for a in arms:
        client = make_client(a)
        v = SmokeVerdict(arm=a["key"], mode=a["mode"], usable=True)
        if a["mode"] == "typed":
            hits, n = 0, 0
            for it in items:
                r = call_arm(client, a, it, bench.template, "typed")
                v.n_calls += 1; v.cost += r.get("cost") or 0
                if r.get("err"):
                    v.reasons.append(f"오류 {r['err']}"); continue
                n += 1
                ok = ((r["p_violation"] >= 0.5) == (it["target"] == 0)) if it["type"] == "binary" else (r.get("pred_index") == it["target"])
                hits += int(ok)
                v.per_item.append({"id": it["id"], "target": it["target"], "hit": int(ok),
                                   "p": r.get("p_violation"), "pred": r.get("pred_index")})
            v.smoke_acc = hits / n if n else None
            v.usable = n == len(items)
            _miss_reason(v, hits, n)
            verdicts[a["key"]] = v
            continue
        # 확률 팔: 항목 5건 (이진은 극성 2회씩)
        binary_t, choice_t, _ = build(bench.template)
        ps, masses, hits, n_ans = [], [], 0, 0
        has_lp, rt_zero, prov_ok = [], [], []
        for it in items:
            nlab = len(it["choices"])
            prompts = [binary_t(it, False), binary_t(it, True)] if it["type"] == "binary" else [choice_t(it, list(range(nlab)))]
            rs = [client.logprob_choice(a["model"], p, nlab, a.get("in_per_m", 0)) for p in prompts]
            v.n_calls += len(rs); v.cost += sum(r["cost"] for r in rs)
            for r in rs:
                if r["err"] and not r["has_logprobs"] and r.get("raw_text") is None:
                    v.reasons.append(f"오류 {r['err']}")
                    continue
                has_lp.append(bool(r["has_logprobs"]))
                if r.get("reasoning_tokens") is not None:
                    rt_zero.append(r["reasoning_tokens"] == 0)
                if a.get("provider") and a["provider"] != "openrouter" and r.get("provider"):
                    prov_ok.append(str(r["provider"]).lower() == a["provider"].lower())
                if r.get("mass") is not None:
                    masses.append(r["mass"])
                if r.get("probs"):
                    ps.append(round(r["probs"][0], 4))
            if it["type"] == "binary" and rs[0].get("probs") and rs[1].get("probs"):
                p = (rs[0]["probs"][0] + rs[1]["probs"][1]) / 2
                ok = int((p >= 0.5) == (it["target"] == 0))
                n_ans += 1; hits += ok
                v.per_item.append({"id": it["id"], "target": it["target"], "hit": ok, "p": round(p, 4)})
            elif it["type"] != "binary" and rs[0].get("probs"):
                pred = max(range(nlab), key=lambda i: rs[0]["probs"][i])
                ok = int(pred == it["target"])
                n_ans += 1; hits += ok
                v.per_item.append({"id": it["id"], "target": it["target"], "hit": ok, "pred": pred})
        v.has_logprobs = any(has_lp) if has_lp else False
        v.reasoning_tokens_zero = all(rt_zero) if rt_zero else None
        v.provider_match = all(prov_ok) if prov_ok else None
        v.mass_min = min(masses) if masses else None
        v.distinct_p = len(set(ps)) if ps else 0
        v.smoke_acc = hits / n_ans if n_ans else None
        if not v.has_logprobs:
            # 생성 팔 강등 시험
            g = client.generate_choice(a["model"], prompts[0], len(items[-1]["choices"]), a.get("in_per_m", 0))
            v.n_calls += 1; v.cost += g["cost"]
            if g["pred_index"] is not None:
                v.mode = "generative"; v.reasons.append("로그확률이 안 와서 생성 팔로 강등 (prob_source=none, 정확도만)")
            else:
                v.usable = False; v.reasons.append("로그확률도 생성 답도 못 읽음")
            verdicts[a["key"]] = v
            continue
        if v.reasoning_tokens_zero is False:
            v.usable = False; v.reasons.append("추론 토큰이 0 이 아니다. 로그확률이 「생각의 첫 토큰」 분포다 (추론을 꺼라)")
        if v.provider_match is False:
            v.usable = False; v.reasons.append("응답 provider 가 핀과 다르다 (라우팅 누수)")
        if v.mass_min is not None and v.mass_min < MASS_MIN:
            v.reasons.append(f"라벨 질량 최소 {v.mass_min:.2f} < {MASS_MIN}. 첫 토큰이 라벨이 아닌 항목이 있다 (오류로 두고 세지 않는다)")
        # 재현성: 첫 항목을 repeats 회
        it0 = items[0]
        p0 = binary_t(it0, False) if it0["type"] == "binary" else choice_t(it0, list(range(len(it0["choices"]))))
        reps = []
        for _ in range(repeats):
            r = client.logprob_choice(a["model"], p0, len(it0["choices"]), a.get("in_per_m", 0))
            v.n_calls += 1; v.cost += r["cost"]
            if r.get("probs"):
                reps.append(r["probs"][0])
        if len(reps) >= 2:
            v.spread = max(reps) - min(reps)
            if v.spread > SPREAD_MAX:
                v.usable = False; v.reasons.append(f"3회 재현 편차 {v.spread:.2f} > {SPREAD_MAX}")
        if ps and v.distinct_p is not None and v.distinct_p < max(3, len(ps) // 2):
            v.reasons.append(f"확률값 종류 {v.distinct_p}/{len(ps)}: 반올림된 로그확률 의심 (AUROC 를 믿지 마라)")
        _miss_reason(v, hits, n_ans)
        verdicts[a["key"]] = v
        if progress:
            print(f"  {a['key']:10} {'OK' if v.usable else 'NO'} lp={v.has_logprobs} rt0={v.reasoning_tokens_zero} prov={v.provider_match} "
                  f"mass≥{v.mass_min} spread={v.spread} distinct={v.distinct_p} acc5={v.smoke_acc}", flush=True)
    return {k: v.to_dict() for k, v in verdicts.items()}


def _miss_reason(v: "SmokeVerdict", hits: int, n: int) -> None:
    """뻔한 항목을 하나라도 틀리면 질문 결함을 먼저 의심한다(스킬 규칙). 팔은 계속 쓸 수 있다."""
    if not n or hits == n:
        return
    missed = [x["id"] for x in v.per_item if not x["hit"]]
    v.reasons.append(f"뻔한 {n}건 중 {n - hits}건 틀림 ({', '.join(missed)}). 다른 팔도 틀리면 질문 결함, 이 팔만 틀리면 팔 약점")


def polarity_suspect(verdicts: dict) -> bool:
    """쓸 수 있는 팔 전부가 뻔한 5건을 거의 다 틀리면(≤20%) 모델 탓이 아니라 라벨 극성·타깃이 뒤집힌 것이다."""
    accs = [v.get("smoke_acc") for v in verdicts.values() if v.get("usable") and v.get("smoke_acc") is not None]
    return bool(accs) and all(a <= 0.2 for a in accs)


def render_smoke(verdicts: dict) -> str:
    L = ["| 팔 | 모드 | 쓸 수 있나 | 로그확률 | 추론0 | provider | 질량min | 편차(3회) | 확률값 종류 | 5건 정확도 | 비용 | 사유 |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, v in verdicts.items():
        f = lambda x: "-" if x is None else (f"{x:.2f}" if isinstance(x, float) else str(x))
        L.append(f"| {k} | {v['mode']} | {'예' if v['usable'] else '아니오'} | {f(v['has_logprobs'])} | {f(v['reasoning_tokens_zero'])} | "
                 f"{f(v['provider_match'])} | {f(v['mass_min'])} | {f(v['spread'])} | {f(v['distinct_p'])} | {f(v['smoke_acc'])} | "
                 f"${v['cost']:.4f} | {'; '.join(v['reasons']) or '-'} |")
    if polarity_suspect(verdicts):
        L.append("")
        L.append("전 팔이 뻔한 항목을 거의 다 틀렸다. 모델 문제가 아니라 라벨 극성이나 target 이 뒤집힌 것이다. 항목의 target 과 choices[0] 의 뜻을 확인하라.")
    bad = [k for k, v in verdicts.items() if not v["usable"]]
    if bad:
        L.append("")
        L.append(f"못 쓰는 조합: {', '.join(bad)}. 이 조합은 빼거나, 실행하지 말고 게시만 해서 기준 팔 결과를 받아라(경로 0).")
    return "\n".join(L)
