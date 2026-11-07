#!/usr/bin/env python3
"""Source-only Heretic/base model metadata gate for Model Spelunker #189.

Reads public Hugging Face metadata, not weights or inference. This never grants
actor admission. Offline JSON snapshots support deterministic negative tests.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PAIRS = {
    "lfm-2.6b": ("LiquidAI/LFM2.5-2.6B", "heretic-org/LFM-2.5-2.6B-heretic", "lfm1.0"),
    "qwen-4b-instruct": ("Qwen/Qwen3-4B-Instruct-2507", "heretic-org/Qwen3-4B-Instruct-2507-heretic", "apache-2.0"),
    "qwen-4b-thinking": ("Qwen/Qwen3-4B-Thinking-2507", "heretic-org/Qwen3-4B-Thinking-2507-heretic", "apache-2.0"),
}
HEX40 = re.compile(r"^[a-f0-9]{40}$")
MAX_METADATA_BYTES = 4 * 1024 * 1024
MAX_TEMPLATE_BYTES = 256 * 1024

def sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()

def canonical_hash(value: object) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))

def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate metadata field denied")
        result[key] = value
    return result


def reject_nonfinite(value: str) -> None:
    raise ValueError("nonfinite JSON metadata denied")


def read_metadata_json(data: bytes) -> dict:
    if len(data) > MAX_METADATA_BYTES:
        raise ValueError("metadata exceeds bound")
    parsed = json.loads(data, object_pairs_hook=reject_duplicate_keys, parse_constant=reject_nonfinite)
    if not isinstance(parsed, dict):
        raise ValueError("model metadata is not an object")
    return parsed


def read_offline_metadata(path: Path) -> dict:
    with path.open("rb") as handle:
        return read_metadata_json(handle.read(MAX_METADATA_BYTES + 1))


def read_template_bytes(data: bytes) -> str:
    if len(data) > MAX_TEMPLATE_BYTES:
        raise ValueError("chat template exceeds bound")
    template = data.decode("utf-8")
    if not template or not template.strip():
        raise ValueError("empty chat template")
    return template


def metadata_files(meta: dict) -> list[str]:
    siblings = meta.get("siblings") or []
    if not isinstance(siblings, list):
        return []
    return [file["rfilename"] for file in siblings
            if isinstance(file, dict) and isinstance(file.get("rfilename"), str)]


def public_chat_template(model_id: str, revision: str) -> str:
    if not HEX40.fullmatch(revision):
        raise ValueError("unpinned template revision")
    if model_id not in {name for pair in PAIRS.values() for name in pair[:2]}:
        raise ValueError("unknown model id")
    url = "https://huggingface.co/" + model_id + "/resolve/" + revision + "/chat_template.jinja"
    req = urllib.request.Request(url, headers={"User-Agent": "model-spelunker-source-preflight/1"})
    with urllib.request.urlopen(req, timeout=12) as response:
        if response.url != url:
            raise ValueError("chat template redirect denied")
        data = response.read(MAX_TEMPLATE_BYTES + 1)
    return read_template_bytes(data)


def public_api_metadata(model_id: str) -> dict:
    # model_id only comes from the local, constant PAIRS table.
    url = "https://huggingface.co/api/models/" + model_id
    req = urllib.request.Request(url, headers={"User-Agent": "model-spelunker-source-preflight/1"})
    with urllib.request.urlopen(req, timeout=12) as response:
        if response.url != url:
            raise ValueError("metadata redirect denied")
        data = response.read(MAX_METADATA_BYTES + 1)
    return read_metadata_json(data)

def license_name(meta: dict) -> str:
    card = meta.get("cardData") or {}
    if not isinstance(card, dict):
        return "unknown"
    return str(card.get("license_name") or card.get("license") or "unknown").lower()

def assess_one(meta: dict, expected_id: str, license_required: str,
               expected_sha: str | None, template_file: str | None = None) -> dict:
    holds = []
    if meta.get("id") != expected_id:
        holds.append("MODEL_ID_MISMATCH")
    commit = meta.get("sha")
    if not isinstance(commit, str) or HEX40.fullmatch(commit) is None:
        holds.append("REVISION_NOT_PINNABLE")
    if expected_sha is None:
        holds.append("REVISION_LOCK_NOT_SUPPLIED")
    elif commit != expected_sha:
        holds.append("REVISION_DRIFT")
    if meta.get("private") is not False or meta.get("gated") is not False or meta.get("disabled") is not False:
        holds.append("MODEL_NOT_PUBLIC_UNGATED_ENABLED")
    observed_license = license_name(meta)
    if observed_license != license_required:
        holds.append("LICENSE_UNVERIFIED_OR_MISMATCH")
    config = meta.get("config") or {}
    if not isinstance(config, dict):
        config = {}
    model_type = config.get("model_type")
    if not isinstance(model_type, str) or not model_type:
        holds.append("MODEL_TYPE_UNKNOWN")
    tokenizer_cfg = config.get("tokenizer_config") or {}
    if not isinstance(tokenizer_cfg, dict):
        tokenizer_cfg = {}
    names = metadata_files(meta)
    has_standalone_template = "chat_template.jinja" in names
    if has_standalone_template:
        template = template_file
        if template is None:
            holds.append("PINNED_TEMPLATE_FILE_NOT_VERIFIED")
    else:
        template = tokenizer_cfg.get("chat_template") or config.get("chat_template_jinja")
        if template_file is not None:
            holds.append("UNEXPECTED_TEMPLATE_FILE")
    if not isinstance(template, str) or not template:
        holds.append("CHAT_TEMPLATE_UNVERIFIED")
    if not any(isinstance(n, str) and n.endswith(".safetensors") for n in names):
        holds.append("SAFETENSORS_WEIGHTS_MISSING")
    if "config.json" not in names or "tokenizer_config.json" not in names:
        holds.append("MODEL_CONFIG_OR_TOKENIZER_MISSING")
    return {
        "id": expected_id,
        "observed_revision": commit if isinstance(commit, str) else None,
        "expected_revision": expected_sha,
        "model_type": model_type,
        "license": observed_license,
        "model_files_count": len(names),
        "safetensors_file_count": sum(isinstance(n, str) and n.endswith(".safetensors") for n in names),
        "metadata_digest": canonical_hash(meta),
        "chat_template_digest": sha256(template) if isinstance(template, str) else None,
        "chat_template_source": "pinned_file" if has_standalone_template and isinstance(template, str) else (
            "embedded_metadata" if not has_standalone_template and isinstance(template, str) else None),
        "holds": sorted(set(holds)),
    }

def pair_report(pair: str, base_meta: dict, mod_meta: dict, base_sha: str | None, mod_sha: str | None,
                base_template: str | None = None, modified_template: str | None = None) -> dict:
    base_id, mod_id, required_license = PAIRS[pair]
    base = assess_one(base_meta, base_id, required_license, base_sha, base_template)
    modified = assess_one(mod_meta, mod_id, required_license, mod_sha, modified_template)
    holds = []
    if base["model_type"] != modified["model_type"]:
        holds.append("MODEL_ARCHITECTURE_NOT_MATCHED")
    if base["license"] != modified["license"]:
        holds.append("LICENSE_VARIANCE")
    if base["chat_template_digest"] != modified["chat_template_digest"]:
        holds.append("CHAT_TEMPLATE_DIFFERS_REQUIRES_EXPERIMENT_CONTROL")
    if base["holds"] or modified["holds"]:
        holds.append("SOURCE_METADATA_NOT_READY")
    # Metadata cannot prove on-runner model bytes, quantization, capacity, or permission.
    return {
        "schema_version": 1,
        "campaign": "model-spelunker-189",
        "experiment_pair": pair,
        "base": base,
        "modified": modified,
        "cross_checks": sorted(set(holds)),
        "source_gate": "HOLD" if holds else "METADATA_READY_ONLY",
        "runtime_gate": "HOLD_UNTIL_WEIGHT_HASH_QUANTIZATION_AND_VENUE_GRANT_VERIFIED",
        "actor_qualification": "UNKNOWN_NOT_EXECUTED",
        "inference_calls": 0,
    }

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pair", required=True, choices=sorted(PAIRS))
    parser.add_argument("--base-json", type=Path, help="Offline public HF metadata")
    parser.add_argument("--modified-json", type=Path, help="Offline public HF metadata")
    parser.add_argument("--base-template-file", type=Path, help="Offline pinned chat_template.jinja")
    parser.add_argument("--modified-template-file", type=Path, help="Offline pinned chat_template.jinja")
    parser.add_argument("--base-sha", help="Expected exact upstream commit")
    parser.add_argument("--modified-sha", help="Expected exact Heretic commit")
    parser.add_argument("--fetch-public-metadata", action="store_true", help="Read-only public API, no model downloads")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.fetch_public_metadata == bool(args.base_json or args.modified_json):
        parser.error("select --fetch-public-metadata or BOTH --base-json and --modified-json")
    if not args.fetch_public_metadata and not (args.base_json and args.modified_json):
        parser.error("offline mode requires both JSON files")
    if args.fetch_public_metadata and (args.base_template_file or args.modified_template_file):
        parser.error("public API mode fetches pinned templates; local template paths are offline-only")
    for revision in [args.base_sha, args.modified_sha]:
        if revision is not None and HEX40.fullmatch(revision) is None:
            parser.error("expected commit must be a 40-character lowercase hex SHA")
    try:
        ids = PAIRS[args.pair]
        if args.fetch_public_metadata:
            base_meta, mod_meta = public_api_metadata(ids[0]), public_api_metadata(ids[1])
        else:
            base_meta = read_offline_metadata(args.base_json)
            mod_meta = read_offline_metadata(args.modified_json)
        if not isinstance(base_meta, dict) or not isinstance(mod_meta, dict):
            raise ValueError("metadata snapshots must be objects")
        templates = []
        for model_id, meta, locked_sha, offline_file in zip(
                ids[:2], (base_meta, mod_meta), (args.base_sha, args.modified_sha),
                (args.base_template_file, args.modified_template_file)):
            if "chat_template.jinja" not in metadata_files(meta):
                templates.append(None)
            elif args.fetch_public_metadata and meta.get("sha") == locked_sha and locked_sha:
                templates.append(public_chat_template(model_id, locked_sha))
            elif not args.fetch_public_metadata and offline_file is not None:
                with offline_file.open("rb") as stream:
                    templates.append(read_template_bytes(stream.read(MAX_TEMPLATE_BYTES + 1)))
            else:
                templates.append(None)
        result = pair_report(args.pair, base_meta, mod_meta, args.base_sha, args.modified_sha,
                             base_template=templates[0], modified_template=templates[1])
    except (ValueError, OSError, urllib.error.URLError) as exc:
        print(json.dumps({"source_gate": "HOLD", "failure": type(exc).__name__, "actor_qualification": "UNKNOWN_NOT_EXECUTED"}))
        return 2
    output = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
    print(output, end="")
    return 0 if result["source_gate"] == "METADATA_READY_ONLY" else 1

if __name__ == "__main__":
    sys.exit(main())
