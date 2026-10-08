"""벤치 로더. 최소 형식(bench.yaml [+ items.jsonl]) · 확장 형식(.jsonl [+ .manifest.yaml]) · 구식 씨앗 스키마."""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..config import find_repo_root
from .legacy import adapt_legacy_item, is_legacy_item

EXTENDED_DEFAULTS = {"label_source": "judged", "class": None, "difficulty": None, "cluster": None,
                     "evidence": None, "provenance": None, "metadata": None}


@dataclass
class Bench:
    name: str
    path: Path                     # 항목 파일(.jsonl) 또는 bench.yaml
    format: str                    # minimal | extended | legacy
    items: list
    manifest: dict = field(default_factory=dict)
    template: str = "generic"      # generic | legacy-seed
    rules: dict = field(default_factory=dict)   # 검사 8 용 선택지별 매처 {choice: [regex,...]}
    items_sha256: str = ""
    warnings: list = field(default_factory=list)

    @property
    def question(self) -> str | None:
        qs = {it.get("question") for it in self.items}
        return qs.pop() if len(qs) == 1 else None

    @property
    def choices(self) -> list | None:
        cs = {tuple(it.get("choices") or ()) for it in self.items}
        return list(cs.pop()) if len(cs) == 1 else None

    @property
    def type(self) -> str:
        ts = {it.get("type") for it in self.items}
        return ts.pop() if len(ts) == 1 else "mixed"

    def questions(self) -> list:
        seen, out = set(), []
        for it in self.items:
            q = it.get("question")
            if q not in seen:
                seen.add(q); out.append(q)
        return out


def file_sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def resolve_bench_path(spec: str, root: Path | None = None) -> Path:
    """이름·경로를 항목 파일 또는 bench.yaml 로 푼다."""
    root = root or find_repo_root()
    p = Path(spec)
    cands = []
    if p.exists():
        if p.is_dir():
            cands += [p / "bench.yaml", p / "bench.yml"]
        else:
            return p
    else:
        cands += [Path(str(p) + ".jsonl"), root / "tasks" / f"{spec}.jsonl",
                  root / "tasks" / "retired" / f"{spec}.jsonl", root / "tasks" / "parked" / f"{spec}.jsonl",
                  root / "benches" / spec / "bench.yaml", root / spec / "bench.yaml"]
    for c in cands:
        if c.exists():
            return c
    raise FileNotFoundError(f"벤치를 찾을 수 없다: {spec}")


def _read_jsonl(p: Path) -> list:
    out = []
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"{p.name}:{n} JSON 오류: {e}") from e
    return out


def expand_minimal(spec: dict, items: list, name: str) -> list:
    """최소 형식 항목(input·target·evidence·class) → 확장 항목."""
    choices = list(spec["choices"])
    guide = str(spec["guide"]).strip()
    typ = spec.get("type") or ("binary" if len(choices) == 2 else "multiclass")
    out = []
    for i, raw in enumerate(items):
        it = {
            "id": raw.get("id") or f"{name}-{i:03d}",
            "input": raw["input"],
            "question": guide,
            "choices": choices,
            "target": raw["target"],
            "type": typ,
            "label_source": raw.get("label_source", "judged"),
            "class": raw.get("class"),
            "difficulty": raw.get("difficulty"),
            "cluster": raw.get("cluster"),
            "evidence": raw.get("evidence"),
            "provenance": raw.get("provenance") or {},
            "metadata": raw.get("metadata") or {},
        }
        out.append(it)
    return out


def _fill_extended(it: dict) -> dict:
    it = dict(it)
    for k, v in EXTENDED_DEFAULTS.items():
        it.setdefault(k, v)
    if it["provenance"] is None:
        it["provenance"] = {}
    if it["metadata"] is None:
        it["metadata"] = {}
    if not it.get("type") and it.get("choices"):
        it["type"] = "binary" if len(it["choices"]) == 2 else "multiclass"
    return it


def load_bench(spec: str, root: Path | None = None) -> Bench:
    root = root or find_repo_root()
    path = resolve_bench_path(spec, root).resolve()
    if path.name.endswith(".manifest.yaml"):
        sib = path.with_name(path.name[: -len(".manifest.yaml")] + ".jsonl")
        if sib.exists():
            return _load_jsonl(sib, root)
        raise FileNotFoundError(f"매니페스트 옆에 항목 파일이 없다: {sib.name}")
    if path.suffix in (".yaml", ".yml"):
        return _load_minimal(path)
    return _load_jsonl(path, root)


def _load_minimal(path: Path) -> Bench:
    spec = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    for k in ("name", "guide", "choices"):
        if k not in spec:
            raise ValueError(f"bench.yaml 에 {k} 가 없다")
    items_spec = spec.get("items", "items.jsonl")
    if isinstance(items_spec, str):
        items_path = path.parent / items_spec
        raw = _read_jsonl(items_path)
        sha = file_sha256(items_path)
    else:
        raw = list(items_spec)
        sha = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    items = expand_minimal(spec, raw, spec["name"])
    manifest = {k: v for k, v in spec.items() if k != "items"}
    return Bench(name=spec["name"], path=path, format="minimal", items=items, manifest=manifest,
                 rules=spec.get("rules") or {}, items_sha256=sha)


def _load_jsonl(path: Path, root: Path) -> Bench:
    raw = _read_jsonl(path)
    if not raw:
        raise ValueError(f"{path.name}: 항목이 없다")
    name = path.stem
    manifest_path = path.with_name(path.stem + ".manifest.yaml")
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    manifest = manifest or {}
    legacy = all(is_legacy_item(it) for it in raw)
    if legacy:
        items = [adapt_legacy_item(it) for it in raw]
        fmt, template = "legacy", "legacy-seed"
        name = raw[0].get("task") or name
    else:
        items = [_fill_extended(it) for it in raw]
        fmt, template = "extended", "generic"
    rules = manifest.get("rules") or {}
    return Bench(name=manifest.get("name") or name, path=path, format=fmt, items=items,
                 manifest=manifest, template=template, rules=rules, items_sha256=file_sha256(path))
