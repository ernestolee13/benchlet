from benchlet.community import build_submission, aggregate


def _run(acc_hits, sha="abc"):
    return {"items_sha256": sha, "template": "generic", "arms": {"qwen": {"model": "qwen/qwen3.8-27b", "provider": "parasail", "prob_source": "logprob"}},
            "agg": {"qwen": {"n": 10, "ok": 10, "hit": acc_hits}}, "items": [{"id": f"i{k}", "target": 0, "arms": {"qwen": {"p_violation": 0.9}}} for k in range(10)]}


def test_submission_requires_same_hash():
    man = {"name": "b", "version": 1, "items_sha256": "abc", "owner": "alice"}
    subs = build_submission(_run(8), man, "bob")["submissions"]
    assert subs[0]["model_key"] == "qwen/qwen3.8-27b@parasail" and subs[0]["acc"] == 0.8 and len(subs[0]["per_item"]) == 10
    try:
        build_submission(_run(8, sha="zzz"), man, "bob"); assert False
    except ValueError:
        pass


def test_aggregate_verifies_after_three_consistent_submitters():
    man = {"name": "b", "version": 1, "items_sha256": "abc", "owner": "alice"}
    subs = [build_submission(_run(h), man, who)["submissions"][0] for who, h in [("bob", 8), ("carol", 8), ("alice", 10)]]
    agg = aggregate(subs, owner="alice", items_sha256="abc")
    k = "qwen/qwen3.8-27b@parasail"
    assert agg[k]["n_submissions"] == 2 and not agg[k]["verified"]          # 작성자 제출 제외
    subs.append(build_submission(_run(9), man, "dave")["submissions"][0])
    agg = aggregate(subs, owner="alice", items_sha256="abc")
    assert agg[k]["n_submissions"] == 3 and not agg[k]["verified"] and "불일치" in agg[k]["status"]   # 범위 10pp
    subs[-1]["acc"] = 0.82
    agg = aggregate(subs, owner="alice", items_sha256="abc")
    assert agg[k]["verified"] and abs(agg[k]["median_acc"] - 0.8) < 1e-9
