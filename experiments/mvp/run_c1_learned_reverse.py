#!/usr/bin/env python3
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import importlib.metadata
import itertools
import json
import math
import os
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

import haiku as hk
import jax
import jax.numpy as jnp
import numpy as np
from scipy.stats import spearmanr
from tracr.compiler import compiling, lib
from tracr.craft import bases
from tracr.rasp import rasp
from tracr.transformer import model as tracr_model

TRACR_REPO = "google-deepmind/tracr"
TRACR_REVISION = "9ce2b8c82b6ba10e62e86cf6f390e7536d4fd2cd"
ORACLE_PARAM_DIGEST = "sha256:737c3f9f42b6f5f0d6dfce68765b872e2b7d574b6ab9d7a60fae459e8789d07f"
BOS = "BOS"
PAD = "PAD"
SEQ_LEN = 5
CONTENT_LEN = 4
VOCAB_SIZE = 4  # 0=BOS, 1..3 content values
MODEL_DIM = 32
NUM_LAYERS = 2
NUM_HEADS = 1
KEY_SIZE = 16
MLP_HIDDEN = 64
TRAIN_SIZE = 60
TEST_SIZE = 21
STEPS = 1000
CHECKPOINT_STEPS = (0, 10, 50, 200, 1000)
LEARNING_RATE = 0.01
SEED = 0
TARGET_ROUTE = [0, 4, 3, 2, 1]


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_json(value: Any) -> str:
    return sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))


def array_hash(x: np.ndarray) -> str:
    a = np.ascontiguousarray(np.asarray(x))
    header = json.dumps({"shape": list(a.shape), "dtype": str(a.dtype)}, sort_keys=True).encode() + b"\0"
    return sha256_bytes(header + a.tobytes(order="C"))


def params_hash(params: hk.Params) -> tuple[str, int]:
    d = hk.data_structures.to_mutable_dict(params)
    h = hashlib.sha256(); count = 0
    for module in sorted(d):
        for name in sorted(d[module]):
            a = np.ascontiguousarray(np.asarray(d[module][name]))
            key = f"{module}/{name}".encode()
            h.update(len(key).to_bytes(8, "big")); h.update(key)
            h.update(str(a.dtype).encode()); h.update(json.dumps(list(a.shape)).encode()); h.update(a.tobytes(order="C"))
            count += int(a.size)
    return "sha256:" + h.hexdigest(), count


def reverse_program():
    return lib.make_reverse(rasp.tokens)


def compile_oracle():
    return compiling.compile_rasp_to_model(
        reverse_program(), vocab={1, 2, 3}, max_seq_len=SEQ_LEN,
        causal=False, compiler_bos=BOS, compiler_pad=PAD,
    )


def all_examples() -> tuple[np.ndarray, np.ndarray, list[list[int]]]:
    content = [list(x) for x in itertools.product((1, 2, 3), repeat=CONTENT_LEN)]
    keyed = sorted(content, key=lambda x: hashlib.sha256(bytes(x)).hexdigest())
    inputs = np.asarray([[0] + x for x in keyed], dtype=np.int32)
    targets = np.asarray([[0] + list(reversed(x)) for x in keyed], dtype=np.int32)
    return inputs, targets, keyed


def make_split() -> dict[str, Any]:
    x, y, content = all_examples()
    return {
        "all_x": x, "all_y": y, "content": content,
        "train_x": x[:TRAIN_SIZE], "train_y": y[:TRAIN_SIZE],
        "test_x": x[TRAIN_SIZE:], "test_y": y[TRAIN_SIZE:],
    }


def learned_forward(tokens: jax.Array):
    token_embed = hk.Embed(vocab_size=VOCAB_SIZE, embed_dim=MODEL_DIM, name="token_embed")
    tok = token_embed(tokens)
    pos = hk.get_parameter("position_embeddings", shape=(SEQ_LEN, MODEL_DIM), init=hk.initializers.RandomNormal(0.02))
    emb = tok + pos[None, :, :]
    cfg = tracr_model.TransformerConfig(
        num_heads=NUM_HEADS,
        num_layers=NUM_LAYERS,
        key_size=KEY_SIZE,
        mlp_hidden_size=MLP_HIDDEN,
        dropout_rate=0.0,
        activation_function=jax.nn.gelu,
        layer_norm=True,
        causal=False,
    )
    stack = tracr_model.Transformer(cfg, name="transformer")
    t_out = stack(emb, jnp.ones(tokens.shape, dtype=jnp.int32), use_dropout=False)
    logits = hk.Linear(VOCAB_SIZE, name="unembed")(t_out.output)
    return logits, t_out


TRANSFORMED = hk.without_apply_rng(hk.transform(learned_forward))


def loss_fn(params: hk.Params, x: jax.Array, y: jax.Array) -> jax.Array:
    logits, _ = TRANSFORMED.apply(params, x)
    logp = jax.nn.log_softmax(logits, axis=-1)
    return -jnp.mean(jnp.take_along_axis(logp, y[..., None], axis=-1))


loss_and_grad = jax.jit(jax.value_and_grad(loss_fn))


def adam_init(params: hk.Params):
    zeros = jax.tree_util.tree_map(jnp.zeros_like, params)
    return zeros, zeros


@jax.jit
def adam_step(params, m, v, step, x, y):
    loss, grads = jax.value_and_grad(loss_fn)(params, x, y)
    b1, b2, eps = 0.9, 0.999, 1e-8
    m = jax.tree_util.tree_map(lambda mm, g: b1 * mm + (1 - b1) * g, m, grads)
    v = jax.tree_util.tree_map(lambda vv, g: b2 * vv + (1 - b2) * (g * g), v, grads)
    step_f = jnp.asarray(step, dtype=jnp.float32)
    mhat = jax.tree_util.tree_map(lambda mm: mm / (1 - b1 ** step_f), m)
    vhat = jax.tree_util.tree_map(lambda vv: vv / (1 - b2 ** step_f), v)
    params = jax.tree_util.tree_map(lambda p, mm, vv: p - LEARNING_RATE * mm / (jnp.sqrt(vv) + eps), params, mhat, vhat)
    return params, m, v, loss


def accuracy(params: hk.Params, x: np.ndarray, y: np.ndarray) -> dict[str, float]:
    logits, _ = TRANSFORMED.apply(params, jnp.asarray(x))
    pred = np.asarray(jnp.argmax(logits, axis=-1))
    return {
        "token_accuracy": float(np.mean(pred == y)),
        "sequence_accuracy": float(np.mean(np.all(pred == y, axis=-1))),
        "loss": float(loss_fn(params, jnp.asarray(x), jnp.asarray(y))),
    }


def stack_learned_outputs(params: hk.Params, x: np.ndarray) -> dict[str, list[np.ndarray]]:
    _, out = TRANSFORMED.apply(params, jnp.asarray(x))
    return {
        "residuals": [np.asarray(z, dtype=np.float64) for z in out.residuals],
        "layer_outputs": [np.asarray(z, dtype=np.float64) for z in out.layer_outputs],
        "attn_logits": [np.asarray(z, dtype=np.float64) for z in out.attn_logits],
    }


def oracle_outputs(oracle, content_rows: list[list[int]]) -> dict[str, list[np.ndarray]]:
    residual_buckets = None; attention_buckets = None
    decoded = []
    for content in content_rows:
        out = oracle.apply([BOS] + content)
        decoded.append(out.decoded)
        if residual_buckets is None:
            residual_buckets = [[] for _ in out.residuals]
            attention_buckets = [[] for _ in out.attn_logits]
        for i, z in enumerate(out.residuals): residual_buckets[i].append(np.asarray(z, dtype=np.float64))
        for i, z in enumerate(out.attn_logits): attention_buckets[i].append(np.asarray(z, dtype=np.float64))
    return {
        "residuals": [np.concatenate(xs, axis=0) for xs in residual_buckets],
        "attn_logits": [np.concatenate(xs, axis=0) for xs in attention_buckets],
        "decoded": decoded,
    }


def center_features(x: np.ndarray) -> np.ndarray:
    z = np.asarray(x, dtype=np.float64).reshape(-1, x.shape[-1])
    return z - np.mean(z, axis=0, keepdims=True)


def linear_cka(a: np.ndarray, b: np.ndarray) -> float:
    x, y = center_features(a), center_features(b)
    cross = x.T @ y; xx = x.T @ x; yy = y.T @ y
    num = float(np.sum(cross * cross))
    den = math.sqrt(float(np.sum(xx * xx)) * float(np.sum(yy * yy)))
    return float(num / den) if den > 1e-20 else 0.0


def pairwise_cosine_vector(x: np.ndarray) -> np.ndarray:
    z = center_features(x)
    n = np.linalg.norm(z, axis=1, keepdims=True)
    norm = np.divide(z, n, out=np.zeros_like(z), where=n > 1e-12)
    sim = norm @ norm.T
    iu = np.triu_indices(sim.shape[0], k=1)
    return 1.0 - sim[iu]


def rsa_spearman(a: np.ndarray, b: np.ndarray) -> float:
    va, vb = pairwise_cosine_vector(a), pairwise_cosine_vector(b)
    corr = spearmanr(va, vb).statistic
    return float(corr) if math.isfinite(float(corr)) else 0.0


def representational_matrices(learned_res: list[np.ndarray], oracle_res: list[np.ndarray]) -> dict[str, Any]:
    cka = [[linear_cka(x, y) for y in oracle_res] for x in learned_res]
    rsa = [[rsa_spearman(x, y) for y in oracle_res] for x in learned_res]
    best_cka = max((v, i, j) for i, row in enumerate(cka) for j, v in enumerate(row))
    best_rsa = max((v, i, j) for i, row in enumerate(rsa) for j, v in enumerate(row))
    return {
        "linear_cka": cka,
        "rsa_spearman": rsa,
        "best_cka": {"value": best_cka[0], "learned_residual": best_cka[1], "oracle_residual": best_cka[2]},
        "best_rsa": {"value": best_rsa[0], "learned_residual": best_rsa[1], "oracle_residual": best_rsa[2]},
    }


def attention_to_bhqk(a: np.ndarray) -> np.ndarray:
    if a.ndim != 4: raise RuntimeError(f"unexpected attention rank {a.shape}")
    if a.shape[1] == NUM_HEADS: return a
    if a.shape[-1] == NUM_HEADS: return np.moveaxis(a, -1, 1)
    raise RuntimeError(f"cannot locate head axis {a.shape}")


def route_metrics(attn_logits: list[np.ndarray]) -> list[dict[str, Any]]:
    rows = []
    for layer, raw in enumerate(attn_logits):
        a = attention_to_bhqk(raw)
        shifted = a - np.max(a, axis=-1, keepdims=True)
        p = np.exp(shifted); p /= np.sum(p, axis=-1, keepdims=True)
        target_probs = np.stack([p[:, 0, q, TARGET_ROUTE[q]] for q in range(1, SEQ_LEN)], axis=1)
        argmax = np.argmax(a[:, 0], axis=-1)
        target = np.asarray(TARGET_ROUTE, dtype=np.int64)[None, :]
        rows.append({
            "layer": layer,
            "mean_opposite_route_probability_content": float(np.mean(target_probs)),
            "opposite_route_argmax_fraction_content": float(np.mean(argmax[:, 1:] == target[:, 1:])),
            "mean_attention_matrix": np.mean(p[:, 0], axis=0).astype(float).tolist(),
        })
    return rows


def oracle_route_metrics(attn_logits: list[np.ndarray], oracle_heads: int) -> list[dict[str, Any]]:
    rows=[]
    for layer, raw in enumerate(attn_logits):
        a=np.asarray(raw)
        if a.shape[1] == oracle_heads: bhqk=a
        elif a.shape[-1] == oracle_heads: bhqk=np.moveaxis(a,-1,1)
        else: raise RuntimeError(a.shape)
        shifted=bhqk-np.max(bhqk,axis=-1,keepdims=True); p=np.exp(shifted); p/=np.sum(p,axis=-1,keepdims=True)
        tp=np.stack([p[:,0,q,TARGET_ROUTE[q]] for q in range(1,SEQ_LEN)],axis=1)
        arg=np.argmax(bhqk[:,0],axis=-1); target=np.asarray(TARGET_ROUTE)[None,:]
        rows.append({"layer":layer,"mean_opposite_route_probability_content":float(np.mean(tp)),"opposite_route_argmax_fraction_content":float(np.mean(arg[:,1:]==target[:,1:]))})
    return rows


def ablate_params(params: hk.Params, needle: str) -> tuple[hk.Params, int]:
    d = hk.data_structures.to_mutable_dict(params); count=0
    for module in list(d):
        if needle in module:
            for name in list(d[module]):
                count += int(np.asarray(d[module][name]).size)
                d[module][name] = jnp.zeros_like(d[module][name])
    if count == 0: raise RuntimeError(f"ablation matched no parameters: {needle}")
    return hk.data_structures.to_immutable_dict(d), count


def learned_ablation_map(params: hk.Params, x: np.ndarray, y: np.ndarray) -> list[dict[str, Any]]:
    rows=[]
    for layer in range(NUM_LAYERS):
        for block in ("attn", "mlp"):
            ablated,count=ablate_params(params,f"transformer/layer_{layer}/{block}")
            rows.append({"layer":layer,"block":block,"ablated_parameters":count,**accuracy(ablated,x,y)})
    return rows


def oracle_sequence_accuracy(oracle) -> float:
    x,_,content = all_examples(); correct=0
    for row in content:
        out=oracle.apply([BOS]+row).decoded
        expected=[BOS]+list(reversed(row))
        if out == expected: correct += 1
    return correct/len(content)


def oracle_ablation_map(oracle) -> list[dict[str, Any]]:
    rows=[]
    for layer in range(oracle.model_config.num_layers):
        for block in ("attn", "mlp"):
            ablated,count=ablate_params(oracle.params,f"transformer/layer_{layer}/{block}")
            altered=dataclasses.replace(oracle,params=ablated)
            rows.append({"layer":layer,"block":block,"ablated_parameters":count,"sequence_accuracy_all":oracle_sequence_accuracy(altered)})
    return rows


def train_once(split: dict[str, Any], capture: bool) -> tuple[hk.Params, list[dict[str, Any]]]:
    tx,ty=split["train_x"],split["train_y"]; testx,testy=split["test_x"],split["test_y"]
    params=TRANSFORMED.init(jax.random.PRNGKey(SEED),jnp.asarray(tx[:1]))
    m,v=adam_init(params); checkpoints=[]
    oracle=compile_oracle() if capture else None
    oracle_test=oracle_outputs(oracle,split["content"][TRAIN_SIZE:]) if capture else None

    def capture_step(step:int, params):
        learned=stack_learned_outputs(params,testx)
        phash,pcount=params_hash(params)
        checkpoints.append({
            "step":step,
            "parameter_sha256":phash,
            "parameter_count":pcount,
            "train":accuracy(params,tx,ty),
            "test":accuracy(params,testx,testy),
            "all":accuracy(params,split["all_x"],split["all_y"]),
            "attention_routing":route_metrics(learned["attn_logits"]),
            "representational_similarity_to_oracle":representational_matrices(learned["residuals"],oracle_test["residuals"]),
        })

    if capture: capture_step(0,params)
    for step in range(1,STEPS+1):
        params,m,v,_=adam_step(params,m,v,step,jnp.asarray(tx),jnp.asarray(ty))
        if capture and step in CHECKPOINT_STEPS: capture_step(step,params)
    return params,checkpoints


def first_checkpoint(checkpoints:list[dict[str,Any]], pred) -> int|None:
    for c in checkpoints:
        if pred(c): return c["step"]
    return None


def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--output",type=Path,default=Path("out/c1-learned-reverse.json")); args=ap.parse_args()
    started=time.perf_counter(); split=make_split()

    oracle=compile_oracle(); oracle_hash,oracle_params=params_hash(oracle.params)
    if oracle_hash != ORACLE_PARAM_DIGEST: raise RuntimeError(f"oracle identity drift: {oracle_hash}")
    oracle_test=oracle_outputs(oracle,split["content"][TRAIN_SIZE:])
    oracle_routes=oracle_route_metrics(oracle_test["attn_logits"],int(oracle.model_config.num_heads))
    oracle_ablation=oracle_ablation_map(oracle)

    train_start=time.perf_counter(); final_params,checkpoints=train_once(split,capture=True); training_seconds=time.perf_counter()-train_start
    final_hash,final_count=params_hash(final_params)
    replay_start=time.perf_counter(); replay_params,_=train_once(split,capture=False); replay_seconds=time.perf_counter()-replay_start
    replay_hash,_=params_hash(replay_params)

    final_checkpoint=next(c for c in checkpoints if c["step"]==STEPS)
    learned_ablation=learned_ablation_map(final_params,split["test_x"],split["test_y"])
    test_accs=[c["test"]["sequence_accuracy"] for c in checkpoints]
    routing_best=[max(r["mean_opposite_route_probability_content"] for r in c["attention_routing"]) for c in checkpoints]
    cka_best=[c["representational_similarity_to_oracle"]["best_cka"]["value"] for c in checkpoints]
    route_acc_corr=float(np.corrcoef(test_accs,routing_best)[0,1]) if np.std(test_accs)>0 and np.std(routing_best)>0 else 0.0

    observations={
        "oracle":{
            "source_repository":TRACR_REPO,"source_revision":TRACR_REVISION,"parameter_sha256":oracle_hash,"parameter_count":oracle_params,
            "model_config":{"num_layers":int(oracle.model_config.num_layers),"num_heads":int(oracle.model_config.num_heads),"residual_dims":len(oracle.residual_labels)},
            "final_attention_routing":oracle_routes,"causal_ablation":oracle_ablation,
        },
        "learned_specimen":{
            "architecture":{"implementation":"tracr.transformer.model.Transformer","sequence_length":SEQ_LEN,"content_vocab":[1,2,3],"model_dim":MODEL_DIM,"num_layers":NUM_LAYERS,"num_heads":NUM_HEADS,"key_size":KEY_SIZE,"mlp_hidden_size":MLP_HIDDEN,"layer_norm":True,"causal":False},
            "training":{"algorithm":"full-batch Adam implemented in-run","learning_rate":LEARNING_RATE,"steps":STEPS,"seed":SEED,"train_examples":TRAIN_SIZE,"test_examples":TEST_SIZE,"split_rule":"all 3^4 sequences sorted by sha256(content bytes); first 60 train, last 21 held out","checkpoint_steps":list(CHECKPOINT_STEPS)},
            "checkpoints":checkpoints,
            "final_parameter_sha256":final_hash,"final_parameter_count":final_count,"deterministic_replay_parameter_sha256":replay_hash,"deterministic_replay_exact":replay_hash==final_hash,
            "final_causal_ablation":learned_ablation,
        },
    }
    derived={
        "oracle_identity_matches_rep33":oracle_hash==ORACLE_PARAM_DIGEST,
        "learned_deterministic_replay_exact":replay_hash==final_hash,
        "final_train_sequence_accuracy":final_checkpoint["train"]["sequence_accuracy"],
        "final_test_sequence_accuracy":final_checkpoint["test"]["sequence_accuracy"],
        "final_all_sequence_accuracy":final_checkpoint["all"]["sequence_accuracy"],
        "earliest_checkpoint_test_sequence_accuracy_ge_0_9":first_checkpoint(checkpoints,lambda c:c["test"]["sequence_accuracy"]>=0.9),
        "earliest_checkpoint_best_route_probability_ge_0_8":first_checkpoint(checkpoints,lambda c:max(r["mean_opposite_route_probability_content"] for r in c["attention_routing"])>=0.8),
        "checkpoint_test_sequence_accuracy":{str(c["step"]):c["test"]["sequence_accuracy"] for c in checkpoints},
        "checkpoint_best_opposite_route_probability":{str(c["step"]):max(r["mean_opposite_route_probability_content"] for r in c["attention_routing"]) for c in checkpoints},
        "checkpoint_best_cka_to_oracle":{str(c["step"]):c["representational_similarity_to_oracle"]["best_cka"]["value"] for c in checkpoints},
        "route_probability_vs_test_accuracy_pearson":route_acc_corr,
        "oracle_attention_ablation_sequence_accuracy":{f"L{r['layer']}_{r['block']}":r["sequence_accuracy_all"] for r in oracle_ablation},
        "learned_final_ablation_test_sequence_accuracy":{f"L{r['layer']}_{r['block']}":r["sequence_accuracy"] for r in learned_ablation},
        "portable_method_checks":{"same_algorithm_oracle_and_learned_specimen":True,"heldout_behavior_recorded":True,"longitudinal_checkpoints_recorded":True,"rsa_and_cka_recorded":True,"attention_route_metric_recorded":True,"causal_block_ablation_recorded":True,"deterministic_training_replay_recorded":True,"raw_activation_tensors_not_persisted":True},
    }
    raw_output_hash=sha256_json({"observations":observations,"derived_metrics":derived}); git_sha=os.environ.get("GITHUB_SHA")
    bundle={
        "probe_id":"c1-learned-reverse-longitudinal-v1","instrument":"compiled-oracle-vs-learned-longitudinal-mechanistic-suite","instrument_version":"mvp-1",
        "model_identity":{"repository":TRACR_REPO,"revision":TRACR_REVISION,"logical_id":"trained/tracr-transformer/reverse-seed0","model_class":"cpu-trained-tiny-transformer","final_parameter_sha256":final_hash},
        "artifact_provenance":{"tracked":False,"reason":"The tiny learned specimen is trained deterministically in-process from the exhaustive synthetic reverse-task universe; code, split, seed, checkpoint parameter SHA-256 values, and an exact deterministic replay are retained instead of an external model artifact."},
        "access_tier":"A4","evidence_level":"CAUSAL","claim_tags":["C1_CALIBRATION","LONGITUDINAL","TRAINING_DYNAMICS","RSA","CKA","ATTENTION_ROUTING","ABLATION"],
        "observations":observations,"derived_metrics":derived,
        "uncertainty":{"scope":"one seed, one learned architecture, one reverse task; this is a calibration specimen rather than evidence about language-model training dynamics","mechanism_comparison":"CKA/RSA measure representational correspondence but do not identify a unique causal isomorphism","causal_ablation":"zeroing a whole attention or MLP block is coarse and can disrupt downstream computation beyond the intended feature"},
        "known_assumptions":["the compiled reverse transformer is a useful ground-truth oracle for routing structure","held-out combinations from the finite 3^4 universe are sufficient to distinguish some memorization from learned compositional routing","same Tracr Transformer implementation improves comparability without making compiled and trained weights equivalent"],
        "known_failure_modes":["a trained model can implement reverse using a mechanism different from the compiled oracle","high CKA/RSA can coexist with different causal mechanisms","one seed cannot characterize training-path variability"],
        "cost":{"training_seconds":training_seconds,"deterministic_replay_seconds":replay_seconds,"total_script_seconds":time.perf_counter()-started,"peak_rss_mib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1024.0},
        "provenance":{"run_id":str(os.environ.get("GITHUB_RUN_ID","local")),"code_revision":git_sha,"model_revision":final_hash,"tokenizer_revision":None,"environment":{"python":sys.version.split()[0],"platform":platform.platform(),"numpy":np.__version__,"jax":jax.__version__,"jaxlib":importlib.metadata.version("jaxlib"),"dm_haiku":importlib.metadata.version("dm-haiku"),"scipy":importlib.metadata.version("scipy"),"tracr_source_revision":TRACR_REVISION},"randomness":{"training_seed":SEED,"dropout":0.0,"split":"deterministic sha256 ordering"},"raw_input_hash":sha256_json({"task":"reverse","all_content":split["content"],"train_size":TRAIN_SIZE,"test_size":TEST_SIZE,"steps":STEPS,"checkpoint_steps":CHECKPOINT_STEPS,"seed":SEED}),"raw_output_hash":raw_output_hash}
    }
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(bundle,indent=2,sort_keys=True)+"\n")
    print(json.dumps({"output":str(args.output),"oracle_hash":oracle_hash,"final_hash":final_hash,"replay_exact":replay_hash==final_hash,"final_train_seq_acc":derived["final_train_sequence_accuracy"],"final_test_seq_acc":derived["final_test_sequence_accuracy"],"best_route_probability":derived["checkpoint_best_opposite_route_probability"][str(STEPS)],"best_cka":derived["checkpoint_best_cka_to_oracle"][str(STEPS)],"training_seconds":training_seconds,"peak_rss_mib":bundle["cost"]["peak_rss_mib"]},sort_keys=True)); return 0

if __name__=="__main__": raise SystemExit(main())
