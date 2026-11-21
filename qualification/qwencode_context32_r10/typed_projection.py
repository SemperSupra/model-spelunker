#!/usr/bin/env python3
"""Narrow typed read_file operation projection from a *successful* actual Qwen CLI tool result.

This is a deterministic DATA-PLANE adapter, not a model-generated final answer.
Do not promote model answer correctness based on this function. Synthetic task only.
"""
from pathlib import Path
import json
import re

TOKEN_RE = re.compile(r"(?<![A-Za-z0-9_])VALUE=[0-9a-f]{24}(?![A-Za-z0-9_])")

def project(stdout: str, root: Path) -> tuple[str, str | None]:
    try:
        rows=json.loads(stdout)
    except (ValueError,TypeError):
        return "INVALID_JSON",None
    if not isinstance(rows,list):
        return "INVALID_JSON",None
    calls=[]
    returned=[]
    base=root.resolve()
    for row in rows:
        if not isinstance(row,dict):return "INVALID_FRAME",None
        message=row.get("message")
        if not isinstance(message,dict):continue
        blocks=message.get("content")
        if not isinstance(blocks,list):continue
        for block in blocks:
            if not isinstance(block,dict):continue
            if block.get("type")=="tool_use":
                if block.get("name")!="read_file":return "UNEXPECTED_TOOL",None
                args=block.get("input")
                if not isinstance(args,dict):return "INVALID_ARGS",None
                keys=[key for key in ("absolute_path","file_path","path") if key in args]
                if len(keys)!=1 or not isinstance(args[keys[0]],str):
                    return "INVALID_ARGS",None
                path=Path(args[keys[0]])
                full=(path if path.is_absolute() else base/path).resolve()
                if full!=base/"fixture.txt":
                    return "NON_FIXTURE_PATH",None
                identifier=block.get("id")
                if not isinstance(identifier,str) or not identifier:return "INVALID_ID",None
                calls.append(identifier)
            elif block.get("type")=="tool_result":
                identifier=block.get("tool_use_id")
                if not isinstance(identifier,str) or not identifier:return "INVALID_RESULT_ID",None
                if block.get("is_error") is not False:return "TOOL_ERROR",None
                content=block.get("content")
                if isinstance(content,str):
                    payload=content
                elif isinstance(content,list):
                    # Tool text blocks are allowed; do not trust non-text structured blobs.
                    if any(not isinstance(x,dict) or x.get("type")!="text" or not isinstance(x.get("text"),str) for x in content):
                        return "INVALID_TOOL_PAYLOAD",None
                    payload="\n".join(x["text"] for x in content)
                else:
                    return "INVALID_TOOL_PAYLOAD",None
                matches=set(TOKEN_RE.findall(payload))
                if len(matches)!=1:
                    return "AMBIGUOUS_OR_MISSING_VALUE",None
                returned.append((identifier,next(iter(matches))))
    if len(calls)!=1 or len(returned)!=1:return "WRONG_TOOL_COUNT",None
    if calls[0]!=returned[0][0]:return "UNMATCHED_TOOL_ID",None
    return "PROJECTED",returned[0][1]

def selftest():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        root=Path(tmp)
        def sample(*,path="fixture.txt",call_id="id",return_id="id",
                   value="VALUE="+"a"*24,error=False,tool="read_file",
                   final="DONE"):
            return json.dumps([
                {"type":"assistant","message":{"content":[{"type":"tool_use","name":tool,"id":call_id,"input":{"absolute_path":str(root/path)}}]}},
                {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":return_id,"is_error":error,"content":"L1: "+value+"\n"}]}},
                {"type":"result","is_error":False,"result":final}
            ])
        valid="VALUE="+"a"*24
        assert project(sample(),root)==("PROJECTED",valid)
        # A wrong/empty final answer must not be mistaken for model semantic PASS,
        # but the successful exact tool result remains independently projectable.
        assert project(sample(final="INCORRECT"),root)==("PROJECTED",valid)
        bad=[
            sample(path="../private"),
            sample(path="other.txt"),
            sample(return_id="wrong"),
            sample(error=True),
            sample(tool="run_shell_command"),
            sample(value="NO_NONCE"),
            sample(value="VALUE="+"b"*24+" VALUE="+"a"*24),
            "not JSON",json.dumps({"type":"result"}),
            json.dumps([{"type":"result","result":"VALUE="+"a"*24}]),
        ]
        for attempt in bad:
            assert project(attempt,root)[0]!="PROJECTED","bad tool transcript accepted"
        assert valid not in json.dumps({"schema":"qwen-r17-typed-tool-critic/v1","state":"PASS"})
        print(json.dumps({"schema":"qwen-r17-typed-tool-critic/v1","state":"PASS",
                          "positive_cases":2,"negative_cases":len(bad),
                          "no_credentials_or_model":"TRUE"}))
if __name__=="__main__":selftest()
