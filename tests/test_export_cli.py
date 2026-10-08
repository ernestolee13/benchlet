import json
import subprocess
import sys

import yaml

from benchlet.export import to_inspect_jsonl, to_lm_eval_yaml, to_hf_eval_yaml
from benchlet.schema import load_bench


def test_exports(root, tmp_path):
    b = load_bench("route-selection", root)
    p = to_inspect_jsonl(b, tmp_path / "i.jsonl")
    rows = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines()]
    assert rows[0]["target"] in "ABCDE" and len(rows) == 40 and "route-000" == rows[0]["id"]
    t = yaml.safe_load(to_lm_eval_yaml(b, tmp_path / "lm").read_text(encoding="utf-8"))
    assert t["output_type"] == "multiple_choice" and t["doc_to_choice"] == list("ABCDE")
    h = yaml.safe_load(to_hf_eval_yaml(b, tmp_path / "eval.yaml").read_text(encoding="utf-8"))
    assert h["eval_results"] == "pending" and h["n_items"] == 40


def test_cli_validate_and_publish_without_results(root, tmp_path):
    import os
    env = dict(os.environ, PYTHONPATH=str(root / "bench-core"), BENCHLET_BANNED_TERMS=str(tmp_path / "none.txt"))
    r = subprocess.run([sys.executable, "-m", "benchlet.cli", "--root", str(root), "validate", "sns-stale-schedule"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 0 and "[PASS]" in r.stdout
    r = subprocess.run([sys.executable, "-m", "benchlet.cli", "--root", str(root), "validate", "tests/fixtures/F08_polarity_flip.jsonl"],
                       capture_output=True, text=True, env=env)
    assert r.returncode == 1 and "극성 뒤집힘" in r.stdout
    r = subprocess.run([sys.executable, "-m", "benchlet.cli", "--root", str(root), "publish", "--bench", "sns-stale-schedule",
                        "--out", str(tmp_path / "pub")], capture_output=True, text=True, env=env)
    assert r.returncode == 0, r.stdout + r.stderr
    man = yaml.safe_load((tmp_path / "pub" / "manifest.yaml").read_text(encoding="utf-8"))
    assert man["results"] == ["results/sns-stale-schedule-run.json"] or man["results"] == "pending"
    assert (tmp_path / "pub" / "samples.jsonl").read_text(encoding="utf-8").count("\n") == 5


def test_minimal_example_bench_validate_review_publish(root, tmp_path):
    import os
    from benchlet.schema import validate_bench
    from benchlet.review.checks import run_checks
    b = load_bench("benches/example", root)
    assert b.format == "minimal" and len(b.items) == 6 and b.choices == ["위반", "통과"]
    assert validate_bench(b, banned_terms=[]).ok
    rep = run_checks(b, None, [5, 9, 10])
    assert not any(f.check == 9 for f in rep.flags)
    env = dict(os.environ, PYTHONPATH=str(root / "bench-core"), BENCHLET_BANNED_TERMS=str(tmp_path / "none.txt"))
    r = subprocess.run([sys.executable, "-m", "benchlet.cli", "--root", str(root), "publish", "--bench", "benches/example",
                        "--out", str(tmp_path / "pub")], capture_output=True, text=True, env=env)
    assert r.returncode == 0 and ("pending" in r.stdout or "example-summary-norm-run.json" in r.stdout)   # 예제 실행 결과가 있으면 그걸 싣는다
    man = yaml.safe_load((tmp_path / "pub" / "manifest.yaml").read_text(encoding="utf-8"))
    assert (man["results"] == "pending" or man["results"] == ["results/example-summary-norm-run.json"]) and man["n"] == 6
