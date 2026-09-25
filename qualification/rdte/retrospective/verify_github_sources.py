#!/usr/bin/env python3
"""Verify public GitHub source facts referenced by retrospective manifests.

RDT&E only: model-spelunker#114 / agent-dispatch-private#314.

This verifier checks source identity/timestamps/tree identities only. It does
not interpret actor behavior, classify outcomes, or modify qualification state.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

GITHUB = "https://github.com"
API = "https://api.github.com"

FetchJson = Callable[[str], dict[str, Any]]


class VerifyError(ValueError):
    pass


def _default_fetch(url: str) -> dict[str, Any]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "model-spelunker-retro-source-verifier/1",
    }
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            value = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, json.JSONDecodeError) as exc:
        raise VerifyError(f"GitHub fetch failed for {url}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise VerifyError(f"GitHub response was not an object: {url}")
    return value


def _source_api(ref: str) -> tuple[str, str] | None:
    commit = re.fullmatch(
        r"https://github\.com/([^/]+)/([^/]+)/commit/([0-9a-fA-F]{7,40})",
        ref,
    )
    if commit:
        owner, repo, sha = commit.groups()
        return "commit", f"{API}/repos/{owner}/{repo}/commits/{sha}"

    comment = re.fullmatch(
        r"https://github\.com/([^/]+)/([^/]+)/(?:issues|pull)/(\d+)#issuecomment-(\d+)",
        ref,
    )
    if comment:
        owner, repo, _number, comment_id = comment.groups()
        return "comment", f"{API}/repos/{owner}/{repo}/issues/comments/{comment_id}"

    issue = re.fullmatch(
        r"https://github\.com/([^/]+)/([^/]+)/issues/(\d+)",
        ref,
    )
    if issue:
        owner, repo, number = issue.groups()
        return "issue", f"{API}/repos/{owner}/{repo}/issues/{number}"

    blob = re.fullmatch(
        r"https://github\.com/([^/]+)/([^/]+)/blob/([^/]+)/(.+)",
        ref,
    )
    if blob:
        owner, repo, revision, file_path = blob.groups()
        return (
            "file",
            f"{API}/repos/{owner}/{repo}/contents/{file_path}?ref={revision}",
        )

    return None


def _observed_fact(kind: str, value: dict[str, Any]) -> dict[str, Any]:
    if kind == "commit":
        commit = value.get("commit")
        commit = commit if isinstance(commit, dict) else {}
        author = commit.get("author")
        author = author if isinstance(author, dict) else {}
        tree = commit.get("tree")
        tree = tree if isinstance(tree, dict) else {}
        return {
            "at": author.get("date"),
            "material_id": (
                f"git-tree:{tree['sha']}"
                if isinstance(tree.get("sha"), str)
                else None
            ),
        }
    if kind in {"comment", "issue"}:
        return {
            "at": value.get("created_at"),
            "material_id": None,
        }
    if kind == "file":
        return {
            "at": None,
            "material_id": None,
        }
    raise VerifyError(f"unsupported GitHub source kind: {kind}")


def verify_manifest(
    manifest: dict[str, Any],
    *,
    fetch_json: FetchJson = _default_fetch,
) -> dict[str, Any]:
    if not isinstance(manifest, dict):
        raise VerifyError("manifest must be an object")
    rep_id = manifest.get("rep_id")
    if not isinstance(rep_id, str) or not rep_id:
        raise VerifyError("rep_id is required")
    events = manifest.get("events")
    if not isinstance(events, list):
        raise VerifyError("events must be an array")

    source_defs = manifest.get("sources")
    if not isinstance(source_defs, list):
        raise VerifyError("sources must be an array")
    source_meta = {
        source.get("ref"): source
        for source in source_defs
        if isinstance(source, dict) and isinstance(source.get("ref"), str)
    }

    cache: dict[str, tuple[str, dict[str, Any]]] = {}
    checks: list[dict[str, Any]] = []

    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise VerifyError(f"events[{index}] must be an object")
        ref = event.get("source_ref")
        if not isinstance(ref, str):
            raise VerifyError(f"events[{index}].source_ref is required")
        source = source_meta.get(ref, {})
        access_class = source.get("access_class", "public-github")
        if access_class != "public-github":
            checks.append({
                "event_index": index,
                "source_ref": ref,
                "status": "SKIP_ACCESS_CLASS",
                "access_class": access_class,
            })
            continue

        parsed = _source_api(ref)
        if parsed is None:
            checks.append({
                "event_index": index,
                "source_ref": ref,
                "status": "SKIP_UNSUPPORTED_SOURCE",
            })
            continue

        if ref not in cache:
            kind, api_url = parsed
            cache[ref] = (kind, fetch_json(api_url))
        kind, source = cache[ref]
        observed = _observed_fact(kind, source)

        expected_at = event.get("at")
        expected_material = event.get("material_id")
        mismatches: list[str] = []

        if expected_at is not None and expected_at != observed.get("at"):
            mismatches.append("timestamp")
        if (
            expected_material is not None
            and expected_material != observed.get("material_id")
        ):
            mismatches.append("material_id")

        checks.append({
            "event_index": index,
            "source_ref": ref,
            "source_kind": kind,
            "status": "PASS" if not mismatches else "MISMATCH",
            "mismatches": mismatches,
            "observed_at": observed.get("at"),
            "observed_material_id": observed.get("material_id"),
        })

    mismatches = [check for check in checks if check["status"] == "MISMATCH"]
    verified = [check for check in checks if check["status"] == "PASS"]
    skipped_access = [
        check for check in checks if check["status"] == "SKIP_ACCESS_CLASS"
    ]
    skipped_unsupported = [
        check for check in checks if check["status"] == "SKIP_UNSUPPORTED_SOURCE"
    ]

    return {
        "record_type": "retrospective-github-source-verification",
        "schema_version": 1,
        "rep_id": rep_id,
        "verified_event_count": len(verified),
        "mismatch_count": len(mismatches),
        "skipped_access_class_count": len(skipped_access),
        "skipped_unsupported_count": len(skipped_unsupported),
        "checks": checks,
        "source_interpretation_performed": False,
        "qualification_state_changed": False,
        "status": "PASS" if not mismatches else "FAIL_SOURCE_MISMATCH",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    report = verify_manifest(manifest)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
