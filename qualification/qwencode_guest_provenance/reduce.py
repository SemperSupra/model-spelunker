#!/usr/bin/env python3
"""Pure source-reuse/guest-provenance classifier. Not a Hyper-V controller."""
from pathlib import Path
import argparse
import json
import re

HERE=Path(__file__).resolve().parent
SHA=re.compile(r"^[a-f0-9]{64}$")
COMMIT=re.compile(r"^[a-f0-9]{40}$")
REPO=re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
EXPECTED_IDS=("H0-VM","H1-WINDOWS-BOOT","H1-PS-DIRECT")


def require(value,reason):
    if not value:
        raise ValueError(reason)


def validate(doc):
    require(isinstance(doc,dict) and doc.get("schema")=="qwen-public-guest-provenance/v1","schema")
    require(doc.get("origin_class")=="PUBLIC_SOURCE","source class")
    require(doc.get("host_runner")=="windows-2025","runner class")
    image=doc.get("guest_image",{})
    require(image.get("purpose")=="evaluation-only","license scope")
    require(SHA.fullmatch(image.get("sha256","")),"image digest")
    require(SHA.fullmatch(image.get("wimlib_sha256","")),"wimlib digest")
    require(isinstance(image.get("size_bytes"),int) and
            1_000_000_000<=image["size_bytes"]<=11_000_000_000,"media size")
    evidence=doc.get("evidence")
    require(isinstance(evidence,list) and len(evidence)==3,"three stages")
    require(tuple(x.get("id") for x in evidence)==EXPECTED_IDS,"ordered evidence")
    for x in evidence:
        require(REPO.fullmatch(x.get("repo","")),"public repo")
        require(COMMIT.fullmatch(x.get("source_sha","")),"exact source")
        require(isinstance(x.get("run_id"),int) and x["run_id"]>0,"run identity")
        require(x.get("independent_cleanup")=="PASS","no cleanup proof")
    h0,boot,psdirect=evidence
    require(h0.get("claim")=="SUPPORTED" and h0.get("independent_gate")=="PASS",
            "h0 claim")
    require(boot.get("claim")=="SUPPORTED_OTHER_WORKSET" and
            boot.get("independent_gate")=="PASS","boot inheritance")
    require(psdirect.get("claim")=="SUPPORTED_OTHER_WORKSET_WITH_RECEIPT_RECOVERY",
            "psdirect claim")
    require(psdirect.get("producer_job")=="PASS" and
            psdirect.get("original_gate")=="FAIL_FILENAME_ONLY" and
            psdirect.get("independent_gate")=="PASS_VIA_RECOVERY",
            "psdirect original failure must be preserved")
    require(COMMIT.fullmatch(psdirect.get("recovered_source_sha","")),
            "recovered independent source")
    require(isinstance(psdirect.get("recovered_run_id"),int) and
            psdirect["recovered_run_id"]!=psdirect["run_id"],"recovered run")
    boundaries=doc.get("boundaries",{})
    for k in ("qwen_guest_installed","qwen_guest_cli_version",
              "qwen_guest_tool_call","qwen_guest_model_inference","qwen_guest_mcp"):
        require(boundaries.get(k)=="NOT_TESTED",f"{k} false promotion")
    require(boundaries.get("real_private_host_admission")=="BLOCKED_ADMISSION",
            "real host admission")
    require(boundaries.get("production_credential_projection")=="NOT_AUTHORIZED",
            "credential effect")
    require(boundaries.get("public_workflow_can_reuse_parent_without_grant") is False,
            "unauthorized inherited job effect")
    require(boundaries.get("no_private_source_in_public_runner") is True,
            "public/private boundary")
    a=doc.get("adoption",{})
    require(a.get("status")=="SOURCE_INPUT_READY_NOT_EXECUTION_ADMITTED",
            "guest source is not guest execution")
    require(SHA.fullmatch(a.get("public_qwen_windows_sha256","")),"qwen exact release")
    require(a.get("source_ref")=="https://github.com/SemperSupra/model-spelunker/pull/221",
            "Qwen source dependency")
    return {
        "schema":"qwen-guest-provenance-reduction/v1",
        "boot_substrate":"REUSABLE_OTHER_WORKSET",
        "psdirect_substrate":"REUSABLE_OTHER_WORKSET_WITH_RECOVERED_GATE",
        "qwen_in_guest":"NOT_TESTED",
        "sovereign_site":"NOT_ADMITTED",
        "dispatch_authorized":False,
        "private_actions_minutes":0,
        "source_evidence_count":3,
        "source_class":"PUBLIC_SOURCE"
    }


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--input",default=str(HERE/"public-sources.json"))
    o=p.parse_args()
    print(json.dumps(validate(json.loads(Path(o.input).read_text())),sort_keys=True))
