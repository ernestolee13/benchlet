"""플래그 큐. 자동 검사는 플래그만 하고 판정은 사람이 한다."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict

STRENGTH_ORDER = {"strong": 0, "medium": 1, "weak": 2}


@dataclass
class Flag:
    check: int
    name: str
    strength: str          # strong | medium | weak
    message: str
    item_id: str | None = None
    data: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReviewReport:
    bench: str
    n_items: int
    flags: list = field(default_factory=list)
    checks_run: list = field(default_factory=list)
    skipped: dict = field(default_factory=dict)     # check → 이유
    sections: dict = field(default_factory=dict)    # 추가 표(검사 7 특징표, 검사 11 덤프)

    def sorted_flags(self) -> list:
        return sorted(self.flags, key=lambda f: (STRENGTH_ORDER.get(f.strength, 9), f.check, f.item_id or ""))

    def by_check(self) -> dict:
        d = {}
        for f in self.flags:
            d.setdefault(f.check, []).append(f)
        return d

    def to_dict(self) -> dict:
        return {"bench": self.bench, "n_items": self.n_items, "checks_run": self.checks_run,
                "skipped": self.skipped, "flags": [f.to_dict() for f in self.sorted_flags()],
                "sections": self.sections}


CHECK_NAMES = {
    1: "교차 패밀리 불일치", 2: "오답 쏠림·클래스 전멸/만점", 5: "순환(생성기=검증기)",
    7: "음성 자명성(표면 특징)", 8: "유일해(규칙 매처)", 9: "극성 일치", 10: "분포 점검",
    11: "채점기 표본 덤프(사람이 본다)",
}


def render_markdown(rep: ReviewReport) -> str:
    L = [f"# 검수 플래그 큐: {rep.bench}", "",
         f"항목 {rep.n_items} · 실행한 검사 {', '.join(str(c) for c in rep.checks_run)} · 플래그 {len(rep.flags)}", ""]
    if rep.skipped:
        L.append("건너뛴 검사")
        for c, why in sorted(rep.skipped.items()):
            L.append(f"- 검사 {c} {CHECK_NAMES.get(c, '')}: {why}")
        L.append("")
    L += ["| 강도 | 검사 | 항목 | 설명 |", "|---|---|---|---|"]
    for f in rep.sorted_flags():
        L.append(f"| {f.strength} | {f.check} {f.name} | {f.item_id or '(벤치)'} | {f.message.replace('|', '¦')} |")
    L.append("")
    for title, body in rep.sections.items():
        L += [f"## {title}", "", body, ""]
    return "\n".join(L)
