#!/usr/bin/env python3
"""Redacted Qwen one-file model→tool→final diagnosis; never serialize tool text or nonce."""
import json
from pathlib import Path

def classify(stdout, root, expected):
    try: rows=json.loads(stdout)
    except (ValueError,TypeError): return {"phase":"INVALID_JSON"}
    if not isinstance(rows,list):return {"phase":"INVALID_ARRAY"}
    tool_calls=[]; results=[]; final=[]
    for row in rows:
        if not isinstance(row,dict):continue
        if row.get("type")=="result":
            final.append(row)
        msg=row.get("message")
        if not isinstance(msg,dict):continue
        for block in msg.get("content",[]) if isinstance(msg.get("content"),list) else []:
            if not isinstance(block,dict):continue
            if block.get("type")=="tool_use":
                arg=block.get("input")
                path=None
                if isinstance(arg,dict):
                    path=next((arg[k] for k in ("absolute_path","file_path","path") if isinstance(arg.get(k),str)),None)
                label="NO_PATH"
                if path:
                    resolved=Path(path).resolve() if Path(path).is_absolute() else (root/Path(path)).resolve()
                    label="FIXTURE" if resolved==root.resolve()/"fixture.txt" else "OTHER_OR_OUTSIDE"
                tool_calls.append({"name_class":"READ_FILE" if block.get("name")=="read_file" else "OTHER","path_class":label,"id":block.get("id")})
            if block.get("type")=="tool_result":
                body=block.get("content")
                serialized=json.dumps(body,ensure_ascii=False) if isinstance(body,(dict,list)) else str(body or "")
                results.append({"id":block.get("tool_use_id"),"is_error":block.get("is_error"),"contains_expected":expected in serialized})
    terminal=final[-1] if len(final)==1 else {}
    answer=terminal.get("result")
    if not isinstance(answer,str): answer=""
    low=answer.lower()
    diagnosis={
       "schema":"qwen-r16-no-content-causal-diagnostic/v1",
       "phase":"EVALUATED",
       "tool_call_count":len(tool_calls),
       "tool_call_path_classes":[t["path_class"] for t in tool_calls],
       "tool_call_name_classes":[t["name_class"] for t in tool_calls],
       "tool_return_count":len(results),
       "tool_return_ids_match":bool(tool_calls) and len(results)==len(tool_calls) and [t["id"] for t in tool_calls]==[z["id"] for z in results],
       "tool_error_observed":any(z["is_error"] is not False for z in results),
       "tool_result_contains_expected":any(z["contains_expected"] for z in results),
       "final_frame_count":len(final),
       "final_error":terminal.get("is_error"),
       "final_length_bucket":"0" if not answer else "1-16" if len(answer)<=16 else "17-80" if len(answer)<=80 else "81+",
       "final_contains_expected":expected in answer,
       "final_starts_value_prefix":answer.lstrip().startswith("VALUE="),
       "final_contains_filename":"fixture.txt" in answer,
       "final_has_cannot_or_error":any(t in low for t in ("cannot","can't","error","unable","failed")),
       "final_has_done_or_success":any(t in low for t in ("done","success","completed")),
       "final_is_empty":not bool(answer.strip())
    }
    return diagnosis

def selftest():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        root=Path(d);expect="VALUE=SECRET"
        def make(output,tool_payload=expect,err=False,path="fixture.txt"):
            return json.dumps([
             {"type":"assistant","message":{"content":[{"type":"tool_use","id":"a","name":"read_file","input":{"absolute_path":str(root/path)}}]}},
             {"type":"user","message":{"content":[{"type":"tool_result","tool_use_id":"a","content":tool_payload,"is_error":err}]}},
             {"type":"result","is_error":False,"result":output}
            ])
        good=classify(make(expect),root,expect)
        assert good["tool_return_ids_match"] and good["tool_result_contains_expected"] and good["final_contains_expected"] and not good["tool_error_observed"]
        echo=classify(make("Done",expect),root,expect)
        assert echo["tool_result_contains_expected"] and not echo["final_contains_expected"] and echo["final_has_done_or_success"]
        wrong=classify(make("Cannot read",tool_payload="",err=True,path="../private"),root,expect)
        assert wrong["tool_error_observed"] and wrong["tool_call_path_classes"]==["OTHER_OR_OUTSIDE"]
        assert "SECRET" not in json.dumps(good)
        assert "SECRET" not in json.dumps(echo)
        assert classify("bad",root,expect)=={"phase":"INVALID_JSON"}
        print(json.dumps({"schema":"qwen-r16-diagnostic-test/v1","state":"PASS","cases":4}))

if __name__=="__main__":selftest()
