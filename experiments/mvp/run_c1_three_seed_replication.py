#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import resource
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_c1_learned_reverse as base  # noqa: E402

SEEDS = (0, 1, 2)


def summarize_seed(seed: int, split):
    base.SEED = seed
    t = time.perf_counter()
    final_params, checkpoints = base.train_once(split, capture=True)
    training_seconds = time.perf_counter() - t
    final_hash, final_count = base.params_hash(final_params)
    t = time.perf_counter()
    replay_params, _ = base.train_once(split, capture=False)
    replay_seconds = time.perf_counter() - t
    replay_hash, _ = base.params_hash(replay_params)
    ablation = base.learned_ablation_map(final_params, split["test_x"], split["test_y"])

    test_acc = [c["test"]["sequence_accuracy"] for c in checkpoints]
    route = [max(r["mean_opposite_route_probability_content"] for r in c["attention_routing"]) for c in checkpoints]
    cka = [c["representational_similarity_to_oracle"]["best_cka"]["value"] for c in checkpoints]
    rsa = [c["representational_similarity_to_oracle"]["best_rsa"]["value"] for c in checkpoints]
    corr = float(np.corrcoef(test_acc, route)[0, 1]) if np.std(test_acc) > 0 and np.std(route) > 0 else 0.0
    final = checkpoints[-1]
    return {
        "seed": seed,
        "training_seconds": training_seconds,
        "deterministic_replay_seconds": replay_seconds,
        "final_parameter_sha256": final_hash,
        "final_parameter_count": final_count,
        "deterministic_replay_parameter_sha256": replay_hash,
        "deterministic_replay_exact": replay_hash == final_hash,
        "checkpoint_steps": [c["step"] for c in checkpoints],
        "test_sequence_accuracy": {str(c["step"]): c["test"]["sequence_accuracy"] for c in checkpoints},
        "best_opposite_route_probability": {str(c["step"]): max(r["mean_opposite_route_probability_content"] for r in c["attention_routing"]) for c in checkpoints},
        "best_cka_to_oracle": {str(c["step"]): c["representational_similarity_to_oracle"]["best_cka"]["value"] for c in checkpoints},
        "best_rsa_to_oracle": {str(c["step"]): c["representational_similarity_to_oracle"]["best_rsa"]["value"] for c in checkpoints},
        "route_probability_vs_test_accuracy_pearson": corr,
        "final_train_sequence_accuracy": final["train"]["sequence_accuracy"],
        "final_test_sequence_accuracy": final["test"]["sequence_accuracy"],
        "final_all_sequence_accuracy": final["all"]["sequence_accuracy"],
        "cka_change_final_minus_initial": cka[-1] - cka[0],
        "rsa_change_final_minus_initial": rsa[-1] - rsa[0],
        "route_change_final_minus_initial": route[-1] - route[0],
        "earliest_test_accuracy_ge_0_9": base.first_checkpoint(checkpoints, lambda c: c["test"]["sequence_accuracy"] >= 0.9),
        "final_attention_routing": final["attention_routing"],
        "final_causal_ablation": ablation,
    }


def mean_by_step(seed_rows, field):
    return {
        str(step): float(np.mean([row[field][str(step)] for row in seed_rows]))
        for step in base.CHECKPOINT_STEPS
    }


def std_by_step(seed_rows, field):
    return {
        str(step): float(np.std([row[field][str(step)] for row in seed_rows]))
        for step in base.CHECKPOINT_STEPS
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--output", type=Path, default=Path("out/c1-three-seed-replication.json"))
    args = ap.parse_args()
    started = time.perf_counter()
    split = base.make_split()

    oracle = base.compile_oracle()
    oracle_hash, oracle_param_count = base.params_hash(oracle.params)
    if oracle_hash != base.ORACLE_PARAM_DIGEST:
        raise RuntimeError(f"oracle identity drift: {oracle_hash}")
    oracle_test = base.oracle_outputs(oracle, split["content"][base.TRAIN_SIZE:])
    oracle_routes = base.oracle_route_metrics(oracle_test["attn_logits"], int(oracle.model_config.num_heads))

    seeds = [summarize_seed(seed, split) for seed in SEEDS]

    derived = {
        "seed_count": len(seeds),
        "all_deterministic_replays_exact": all(x["deterministic_replay_exact"] for x in seeds),
        "all_final_test_sequence_accuracy_ge_0_9": all(x["final_test_sequence_accuracy"] >= 0.9 for x in seeds),
        "all_final_test_sequence_accuracy_eq_1": all(x["final_test_sequence_accuracy"] == 1.0 for x in seeds),
        "all_cka_final_below_initial": all(x["cka_change_final_minus_initial"] < 0 for x in seeds),
        "all_rsa_final_below_initial": all(x["rsa_change_final_minus_initial"] < 0 for x in seeds),
        "all_route_final_above_initial": all(x["route_change_final_minus_initial"] > 0 for x in seeds),
        "per_seed_cka_change_final_minus_initial": {str(x["seed"]): x["cka_change_final_minus_initial"] for x in seeds},
        "per_seed_rsa_change_final_minus_initial": {str(x["seed"]): x["rsa_change_final_minus_initial"] for x in seeds},
        "per_seed_route_change_final_minus_initial": {str(x["seed"]): x["route_change_final_minus_initial"] for x in seeds},
        "per_seed_route_accuracy_correlation": {str(x["seed"]): x["route_probability_vs_test_accuracy_pearson"] for x in seeds},
        "mean_test_sequence_accuracy_by_step": mean_by_step(seeds, "test_sequence_accuracy"),
        "std_test_sequence_accuracy_by_step": std_by_step(seeds, "test_sequence_accuracy"),
        "mean_best_route_probability_by_step": mean_by_step(seeds, "best_opposite_route_probability"),
        "std_best_route_probability_by_step": std_by_step(seeds, "best_opposite_route_probability"),
        "mean_best_cka_by_step": mean_by_step(seeds, "best_cka_to_oracle"),
        "std_best_cka_by_step": std_by_step(seeds, "best_cka_to_oracle"),
        "mean_best_rsa_by_step": mean_by_step(seeds, "best_rsa_to_oracle"),
        "std_best_rsa_by_step": std_by_step(seeds, "best_rsa_to_oracle"),
        "final_route_probability_mean": float(np.mean([x["best_opposite_route_probability"]["1000"] for x in seeds])),
        "final_route_probability_std": float(np.std([x["best_opposite_route_probability"]["1000"] for x in seeds])),
        "final_cka_mean": float(np.mean([x["best_cka_to_oracle"]["1000"] for x in seeds])),
        "final_cka_std": float(np.std([x["best_cka_to_oracle"]["1000"] for x in seeds])),
        "portable_method_checks": {
            "same_architecture_task_split_and_schedule_across_seeds": True,
            "three_seed_max_respected": len(seeds) == 3,
            "longitudinal_behavior_recorded": True,
            "longitudinal_routing_recorded": True,
            "longitudinal_cka_rsa_recorded": True,
            "final_coarse_causal_ablation_recorded": True,
            "deterministic_replay_per_seed_recorded": True,
            "raw_activation_tensors_not_persisted": True,
        },
    }
    observations = {
        "oracle": {
            "source_revision": base.TRACR_REVISION,
            "parameter_sha256": oracle_hash,
            "parameter_count": oracle_param_count,
            "final_attention_routing": oracle_routes,
        },
        "replication_protocol": {
            "task": "reverse",
            "seeds": list(SEEDS),
            "architecture": {"model_dim": base.MODEL_DIM, "num_layers": base.NUM_LAYERS, "num_heads": base.NUM_HEADS, "key_size": base.KEY_SIZE, "mlp_hidden_size": base.MLP_HIDDEN},
            "train_examples": base.TRAIN_SIZE,
            "test_examples": base.TEST_SIZE,
            "steps": base.STEPS,
            "checkpoint_steps": list(base.CHECKPOINT_STEPS),
            "learning_rate": base.LEARNING_RATE,
            "methodological_expansion": False,
        },
        "seeds": seeds,
    }
    raw_output_hash = base.sha256_json({"observations": observations, "derived_metrics": derived})
    bundle = {
        "probe_id": "c1-learned-reverse-three-seed-replication-v1",
        "instrument": "longitudinal-mechanistic-seed-replication-suite",
        "instrument_version": "mvp-1",
        "model_identity": {"repository": base.TRACR_REPO, "revision": base.TRACR_REVISION, "logical_id": "trained/tracr-transformer/reverse-seeds0-2", "model_class": "cpu-trained-tiny-transformer-replication", "final_parameter_digests": {str(x["seed"]): x["final_parameter_sha256"] for x in seeds}},
        "artifact_provenance": {"tracked": False, "reason": "Three tiny learned specimens are deterministically trained in-process from the same exhaustive synthetic reverse-task universe; code, fixed split, per-seed parameter digests, checkpoints, and deterministic replays retain identity without an external model artifact."},
        "access_tier": "A4",
        "evidence_level": "CAUSAL",
        "claim_tags": ["C1_CALIBRATION", "THREE_SEED_REPLICATION", "LONGITUDINAL", "CKA", "RSA", "ATTENTION_ROUTING", "ABLATION"],
        "observations": observations,
        "derived_metrics": derived,
        "uncertainty": {"scope": "three seeds of one tiny architecture/task; replication tests instrument behavior, not general transformer training dynamics", "causal_ablation": "whole-block zero ablations remain deliberately coarse and are not interpreted as unique mechanism identification"},
        "known_assumptions": ["the seed-0 protocol is replicated without methodological expansion", "three seeds are sufficient for this bounded calibration decision but not population statistics"],
        "known_failure_modes": ["all three seeds share one deterministic train/test split", "representational metrics can be dominated by input/position geometry unrelated to causal algorithm implementation"],
        "cost": {"total_script_seconds": time.perf_counter() - started, "peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, "per_seed_training_seconds": {str(x["seed"]): x["training_seconds"] for x in seeds}, "per_seed_replay_seconds": {str(x["seed"]): x["deterministic_replay_seconds"] for x in seeds}},
        "provenance": {"run_id": str(os.environ.get("GITHUB_RUN_ID", "local")), "code_revision": os.environ.get("GITHUB_SHA"), "model_revision": base.TRACR_REVISION, "tokenizer_revision": None, "environment": {"python": sys.version.split()[0], "numpy": np.__version__, "tracr_source_revision": base.TRACR_REVISION}, "randomness": {"training_seeds": list(SEEDS), "split": "same deterministic sha256 ordering for all seeds", "dropout": 0.0}, "raw_input_hash": base.sha256_json({"task": "reverse", "seeds": SEEDS, "content": split["content"], "steps": base.STEPS, "checkpoints": base.CHECKPOINT_STEPS}), "raw_output_hash": raw_output_hash},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(bundle, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"output": str(args.output), "all_final_perfect": derived["all_final_test_sequence_accuracy_eq_1"], "all_cka_final_below_initial": derived["all_cka_final_below_initial"], "final_route_mean": derived["final_route_probability_mean"], "final_route_std": derived["final_route_probability_std"], "final_cka_mean": derived["final_cka_mean"], "final_cka_std": derived["final_cka_std"], "all_replays_exact": derived["all_deterministic_replays_exact"], "peak_rss_mib": bundle["cost"]["peak_rss_mib"]}, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
