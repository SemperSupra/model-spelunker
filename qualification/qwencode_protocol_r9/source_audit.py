#!/usr/bin/env python3
"""Qwen v0.28.3 exact-source OpenAI/SSE protocol contract verification.

Pure stdlib; captures no prompt, nonce, model response, bearer token or host
identity. A matching static source is NOT a claim of Ollama interoperability.
"""
import argparse
import hashlib
import json
from pathlib import Path

HERE=Path(__file__).resolve().parent
NEEDLES={
"packages/core/src/core/openaiContentGenerator/pipeline.ts":[
  "baseRequest.stream_options = { include_usage: true }",
  "this.client.chat.completions.create(",
  "applyConfiguredReasoningEffort(",
  "providerRequest = this.config.provider.buildRequest(",
  "openaiRequestCaptureContext.getStore()?.(openaiRequest)",
  "if (fcMode === 'ANY')",
  "'tool_choice'",
  "StreamingToolCallParser",
],
"packages/core/src/core/openaiContentGenerator/requestCaptureContext.ts":[
  "post", "provider", "stream_options","samplingParams","openaiRequestCaptureContext"
],
"packages/core/src/core/openaiContentGenerator/streamingToolCallParser.ts":[
  "StreamingToolCallParser","hasIncompleteToolCalls()","getCompletedToolCalls()",
],
"packages/core/src/core/llm-chat.ts":[
  "Model stream ended with empty response text.","'NO_RESPONSE_TEXT'",
],
}


def git_blob(raw):
    return hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\x00"+raw).hexdigest()


def audit(pins,files):
    if pins.get("schema")!="qwen-r9-upstream-openai-protocol/v1":
        raise ValueError("wrong source schema")
    if pins.get("repo")!="QwenLM/qwen-code" or pins.get("tag_commit")!="99fcf89892f1a3a8027c75468546c7e7be906245":
        raise ValueError("floating or unknown upstream release")
    if set(pins.get("files",{}))!=set(NEEDLES):
        raise ValueError("source set mismatches")
    for path,required in NEEDLES.items():
        raw=files.get(path)
        if not isinstance(raw,bytes) or git_blob(raw)!=pins["files"][path]:
            raise ValueError("source blob changed: "+path)
        source=raw.decode("utf-8")
        for marker in required:
            if marker not in source:
                raise ValueError("source behavior not present: "+path+" "+marker)
    return {"schema":"qwen-r9-source-audit/v1",
            "status":"PASS_EXACT_SOURCE_FIELDS",
            "source":"QwenLM/qwen-code@v0.28.3",
            "sha":pins["tag_commit"],
            "blobs_verified":len(NEEDLES),
            "request_keys_to_compare":["stream","stream_options.include_usage",
              "reasoning_effort","reasoning","tool_choice","max_tokens",
              "max_completion_tokens","extra_body","tools[].function"],
            "provider_stream_and_model_interoperability":"NOT_QUALIFIED",
            "raw_values_retained":False,"effect_authorized":False}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--upstream",type=Path,required=True)
    p.add_argument("--pins",type=Path,default=HERE/"upstream-pins.json")
    args=p.parse_args()
    pinned=json.loads(args.pins.read_text())
    found={k:(args.upstream/k).read_bytes() for k in NEEDLES}
    print(json.dumps(audit(pinned,found),sort_keys=True))


if __name__=="__main__":main()
