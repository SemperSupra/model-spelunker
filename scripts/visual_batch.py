"""Content-addressed batch orchestration for trusted visual-concept runs."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any, Callable, Sequence
import uuid

from visual_concept_worker_core import canonical_digest


@dataclass(frozen=True)
class BatchAsset:
    asset_id: str
    filename: str
    sha256: str


def sha256_file(path: str | Path) -> str:
    h=hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda:handle.read(1024*1024),b""): h.update(chunk)
    return h.hexdigest()


def extract_benchmark_assets(benchmark: dict[str,Any]) -> tuple[BatchAsset,...]:
    out=[]; ids=set(); shas=set()
    for index,entry in enumerate(benchmark.get("assets",[])):
        meta=entry.get("asset",entry)
        asset_id=meta.get("benchmark_asset_id") or entry.get("benchmark_asset_id")
        filename=meta.get("source_filename") or meta.get("filename") or entry.get("source_filename")
        sha=meta.get("sha256") or entry.get("sha256")
        if not asset_id or not filename or not sha:
            raise ValueError(f"benchmark asset {index} lacks id, filename, or sha256")
        if asset_id in ids: raise ValueError(f"duplicate benchmark_asset_id: {asset_id}")
        if sha in shas: raise ValueError(f"duplicate benchmark sha256: {sha}")
        ids.add(asset_id); shas.add(sha)
        out.append(BatchAsset(str(asset_id),str(filename),str(sha)))
    if not out: raise ValueError("benchmark contains no assets")
    return tuple(out)


def result_identity(result: dict[str,Any]) -> str:
    if result.get("execution_digest"): return str(result["execution_digest"])
    if result.get("run_digest"): return str(result["run_digest"])
    worker=result.get("worker_run")
    if isinstance(worker,dict) and worker.get("run_digest"): return str(worker["run_digest"])
    raise ValueError("result lacks a stable execution/run digest")


def run_batch(
    *,
    benchmark: dict[str,Any],
    image_root: str|Path,
    output_dir: str|Path,
    candidate_digest: str,
    treatment: str,
    run_one: Callable[[Path,BatchAsset],dict[str,Any]],
    execution_lane: str,
    limit: int=0,
    private_inputs: bool=True,
) -> dict[str,Any]:
    if private_inputs and execution_lane not in {"trusted-local","trusted-self-hosted"}:
        raise ValueError("private benchmark batches require a trusted execution lane")
    assets=list(extract_benchmark_assets(benchmark))
    if limit<0: raise ValueError("limit must be >= 0")
    if limit: assets=assets[:limit]
    root=Path(image_root); out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    run_id=f"vcw-batch-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    generated_at=datetime.now(timezone.utc).isoformat()
    succeeded=[]; failures=[]
    for asset in assets:
        path=root/asset.filename
        if not path.exists():
            failures.append({"asset_id":asset.asset_id,"input_sha256":asset.sha256,"error_kind":"image_missing"})
            continue
        actual=sha256_file(path)
        if actual!=asset.sha256:
            failures.append({"asset_id":asset.asset_id,"input_sha256":asset.sha256,"actual_sha256":actual,"error_kind":"sha256_mismatch"})
            continue
        try:
            result=run_one(path,asset)
            digest=result_identity(result)
        except Exception as exc:
            failures.append({"asset_id":asset.asset_id,"input_sha256":asset.sha256,"error_kind":type(exc).__name__,"error":str(exc)})
            continue
        file_name=f"{asset.asset_id}.{candidate_digest[:12]}.{treatment}.json"
        (out/file_name).write_text(json.dumps(result,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
        succeeded.append({"asset_id":asset.asset_id,"input_sha256":asset.sha256,"result_digest":digest,"output_file":file_name})

    identity_payload={
        "benchmark_id":benchmark.get("benchmark_id"),
        "benchmark_version":benchmark.get("benchmark_version"),
        "candidate_digest":candidate_digest,
        "treatment":treatment,
        "execution_lane":execution_lane,
        "private_inputs":private_inputs,
        "requested":[{"asset_id":a.asset_id,"sha256":a.sha256} for a in assets],
        "succeeded":[{"asset_id":x["asset_id"],"input_sha256":x["input_sha256"],"result_digest":x["result_digest"]} for x in succeeded],
        "failures":[{k:v for k,v in x.items() if k!="error"} for x in failures],
    }
    manifest={
        "schema_version":"visual_concept_batch.v0.1",
        "run_id":run_id,
        "generated_at":generated_at,
        "benchmark_id":benchmark.get("benchmark_id"),
        "benchmark_version":benchmark.get("benchmark_version"),
        "candidate_digest":candidate_digest,
        "treatment":treatment,
        "execution_lane":execution_lane,
        "private_inputs":private_inputs,
        "asset_count_requested":len(assets),
        "asset_count_succeeded":len(succeeded),
        "asset_count_failed":len(failures),
        "results":succeeded,
        "failures":failures,
        "safeguards":{
            "ground_truth":False,
            "semantic_authority":False,
            "public_runner_used_for_private_bytes":bool(private_inputs and execution_lane=="public-ringer"),
        },
        "batch_digest":canonical_digest(identity_payload),
    }
    (out/f"{run_id}.manifest.json").write_text(json.dumps(manifest,indent=2,sort_keys=True,ensure_ascii=False)+"\n",encoding="utf-8")
    return manifest
