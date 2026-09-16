#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import jsonschema

REPO_ROOT=Path(__file__).resolve().parents[2]
SCHEMA=REPO_ROOT/"schemas"/"observation-bundle.schema.json"
TRACR_REVISION="9ce2b8c82b6ba10e62e86cf6f390e7536d4fd2cd"
ORACLE_DIGEST="sha256:737c3f9f42b6f5f0d6dfce68765b872e2b7d574b6ab9d7a60fae459e8789d07f"
CHECKPOINTS=[0,10,50,200,1000]


def finite(v): return isinstance(v,(int,float)) and math.isfinite(float(v))

def sha256_json(value):
    data=json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    return "sha256:"+hashlib.sha256(data).hexdigest()


def metric(m):
    assert set(m)=={"token_accuracy","sequence_accuracy","loss"}
    assert finite(m["token_accuracy"]) and 0<=m["token_accuracy"]<=1
    assert finite(m["sequence_accuracy"]) and 0<=m["sequence_accuracy"]<=1
    assert finite(m["loss"]) and m["loss"]>=0


def finite_matrix(x, rows, cols, lower=-1.000001, upper=1.000001):
    assert len(x)==rows
    for row in x:
        assert len(row)==cols
        assert all(finite(v) and lower<=v<=upper for v in row)


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("bundle",type=Path); args=ap.parse_args()
    b=json.loads(args.bundle.read_text()); jsonschema.validate(b,json.loads(SCHEMA.read_text()))
    assert b["probe_id"]=="c1-learned-reverse-longitudinal-v1"
    assert b["instrument"]=="compiled-oracle-vs-learned-longitudinal-mechanistic-suite"
    assert b["access_tier"]=="A4" and b["evidence_level"]=="CAUSAL"
    assert b["model_identity"]["revision"]==TRACR_REVISION
    assert b["model_identity"]["model_class"]=="cpu-trained-tiny-transformer"
    assert b["artifact_provenance"]["tracked"] is False

    o=b["observations"]; oracle=o["oracle"]; learned=o["learned_specimen"]
    assert oracle["source_revision"]==TRACR_REVISION
    assert oracle["parameter_sha256"]==ORACLE_DIGEST
    assert oracle["parameter_count"]==18755
    assert oracle["model_config"]=={"num_layers":4,"num_heads":1,"residual_dims":41}
    assert len(oracle["final_attention_routing"])==4
    assert len(oracle["causal_ablation"])==8
    for row in oracle["final_attention_routing"]:
        assert 0<=row["layer"]<4
        assert finite(row["mean_opposite_route_probability_content"]) and 0<=row["mean_opposite_route_probability_content"]<=1.000001
        assert finite(row["opposite_route_argmax_fraction_content"]) and 0<=row["opposite_route_argmax_fraction_content"]<=1
    for row in oracle["causal_ablation"]:
        assert row["block"] in {"attn","mlp"} and 0<=row["layer"]<4
        assert int(row["ablated_parameters"])>0
        assert finite(row["sequence_accuracy_all"]) and 0<=row["sequence_accuracy_all"]<=1

    arch=learned["architecture"]
    assert arch["implementation"]=="tracr.transformer.model.Transformer"
    assert arch["sequence_length"]==5 and arch["content_vocab"]==[1,2,3]
    assert arch["num_layers"]==2 and arch["num_heads"]==1 and arch["model_dim"]==32
    train=learned["training"]
    assert train["seed"]==0 and train["steps"]==1000
    assert train["train_examples"]==60 and train["test_examples"]==21
    assert train["checkpoint_steps"]==CHECKPOINTS

    cps=learned["checkpoints"]
    assert [c["step"] for c in cps]==CHECKPOINTS
    param_counts=set()
    for c in cps:
        assert c["parameter_sha256"].startswith("sha256:") and len(c["parameter_sha256"])==71
        param_counts.add(int(c["parameter_count"]))
        metric(c["train"]); metric(c["test"]); metric(c["all"])
        routes=c["attention_routing"]; assert len(routes)==2
        for r in routes:
            assert r["layer"] in {0,1}
            assert finite(r["mean_opposite_route_probability_content"]) and 0<=r["mean_opposite_route_probability_content"]<=1.000001
            assert finite(r["opposite_route_argmax_fraction_content"]) and 0<=r["opposite_route_argmax_fraction_content"]<=1
            mat=r["mean_attention_matrix"]; finite_matrix(mat,5,5,0,1.000001)
        sim=c["representational_similarity_to_oracle"]
        finite_matrix(sim["linear_cka"],4,8,0,1.000001)
        finite_matrix(sim["rsa_spearman"],4,8,-1.000001,1.000001)
        for key in ("best_cka","best_rsa"):
            z=sim[key]; assert finite(z["value"])
            assert z["learned_residual"] in range(4) and z["oracle_residual"] in range(8)
    assert len(param_counts)==1

    final=cps[-1]
    assert learned["final_parameter_sha256"]==final["parameter_sha256"]
    assert learned["final_parameter_count"]==final["parameter_count"]
    assert learned["deterministic_replay_parameter_sha256"]==learned["final_parameter_sha256"]
    assert learned["deterministic_replay_exact"] is True
    assert len(learned["final_causal_ablation"])==4
    for row in learned["final_causal_ablation"]:
        assert row["layer"] in {0,1} and row["block"] in {"attn","mlp"}
        assert int(row["ablated_parameters"])>0
        metric({"token_accuracy":row["token_accuracy"],"sequence_accuracy":row["sequence_accuracy"],"loss":row["loss"]})

    d=b["derived_metrics"]
    assert d["oracle_identity_matches_rep33"] is True
    assert d["learned_deterministic_replay_exact"] is True
    for key in ("final_train_sequence_accuracy","final_test_sequence_accuracy","final_all_sequence_accuracy"):
        assert finite(d[key]) and 0<=d[key]<=1
    for field in ("checkpoint_test_sequence_accuracy","checkpoint_best_opposite_route_probability","checkpoint_best_cka_to_oracle"):
        assert set(d[field])=={str(x) for x in CHECKPOINTS}
        assert all(finite(v) for v in d[field].values())
    assert finite(d["route_probability_vs_test_accuracy_pearson"]) and -1.000001<=d["route_probability_vs_test_accuracy_pearson"]<=1.000001
    assert len(d["oracle_attention_ablation_sequence_accuracy"])==8
    assert len(d["learned_final_ablation_test_sequence_accuracy"])==4
    checks=d["portable_method_checks"]; assert checks and all(v is True for v in checks.values())

    assert b["provenance"]["raw_output_hash"]==sha256_json({"observations":o,"derived_metrics":d})
    assert b["provenance"]["model_revision"]==learned["final_parameter_sha256"]

    print(json.dumps({"valid":True,"probe_id":b["probe_id"],"final_train_sequence_accuracy":d["final_train_sequence_accuracy"],"final_test_sequence_accuracy":d["final_test_sequence_accuracy"],"final_route_probability":d["checkpoint_best_opposite_route_probability"]["1000"],"final_best_cka":d["checkpoint_best_cka_to_oracle"]["1000"],"deterministic_replay_exact":True,"scientific_outcome_not_acceptance_gate":True},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
