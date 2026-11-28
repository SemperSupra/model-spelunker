#!/usr/bin/env python3
"""Independent exact read-file lineage oracle for public two-hop Qwen JSON output.

Source: pinned Qwen 0.28.3 JsonOutputAdapter / BaseJsonOutputAdapter:
 assistant.message.content tool_use {id,name,input};
 user.message.content tool_result {tool_use_id,is_error}.
Do not persist model arguments, file content, or full stdout.
"""
import json
import math
from pathlib import Path

def _unique_object(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("duplicate JSON key")
        obj[key] = value
    return obj


def _reject_constant(value):
    raise ValueError("non-finite JSON constant")


def _finite_float(value):
    result = float(value)
    if not math.isfinite(result):
        raise ValueError("non-finite JSON number")
    return result


def lineage_verdict(stdout: str, workdir: Path, target: str) -> str:
    if target not in ("a.txt", "b.txt"):
        return "INVALID_TARGET"
    try:
        rows=json.loads(stdout, object_pairs_hook=_unique_object,
                        parse_constant=_reject_constant, parse_float=_finite_float)
    except (ValueError, TypeError, RecursionError):
        return "INVALID_JSON"
    if not isinstance(rows,list):
        return "INVALID_JSON"
    requested=[]
    returned=[]
    try:
        root=workdir.resolve()
    except (OSError, ValueError, RuntimeError):
        return "INVALID_WORKDIR"
    final_count=0
    for index,row in enumerate(rows):
        if not isinstance(row,dict):
            return "INVALID_FRAME"
        if row.get("type")=="result":
            if len(requested)!=2 or len(returned)!=2:
                return "PREMATURE_FINAL_RESULT"
            final_count+=1
            if index!=len(rows)-1:
                return "NONTERMINAL_FINAL_RESULT"
        if "message" not in row:
            if row.get("type") in ("assistant", "user"):
                return "INVALID_MESSAGE"
            continue
        msg=row["message"]
        if not isinstance(msg,dict):
            return "INVALID_MESSAGE"
        blocks=msg.get("content")
        if not isinstance(blocks,list):
            return "INVALID_CONTENT"
        for item in blocks:
            if not isinstance(item,dict):
                return "INVALID_CONTENT_BLOCK"
            if item.get("type")=="tool_use":
                if row.get("type")!="assistant":
                    return "INVALID_TOOL_USE_FRAME"
                if item.get("name")!="read_file":
                    return "UNEXPECTED_TOOL"
                args=item.get("input")
                if not isinstance(args,dict):
                    return "INVALID_ARGS"
                paths=[args.get(k) for k in ("absolute_path","file_path","path") if k in args]
                if len(paths)!=1 or not isinstance(paths[0],str) or not paths[0]:
                    return "INVALID_ARGS"
                try:
                    fp=Path(paths[0])
                    resolved=(fp if fp.is_absolute() else root/fp).resolve()
                except (OSError, ValueError, RuntimeError):
                    return "INVALID_PATH"
                try: relative=resolved.relative_to(root).as_posix()
                except ValueError: return "OUT_OF_SCOPE"
                identifier=item.get("id")
                if not isinstance(identifier,str) or not identifier:
                    return "MISSING_TOOL_ID"
                if len(requested)!=len(returned):
                    return "OVERLAPPING_TOOL_USE"
                requested.append((identifier,relative))
            elif item.get("type")=="tool_result":
                if row.get("type")!="user":
                    return "INVALID_TOOL_RESULT_FRAME"
                identifier=item.get("tool_use_id")
                if not isinstance(identifier,str) or not identifier:
                    return "INVALID_RESULT_ID"
                if item.get("is_error") is not False:
                    return "TOOL_RESULT_ERROR"
                if len(requested)!=len(returned)+1 or requested[-1][0]!=identifier:
                    return "UNMATCHED_TOOL_RESULT"
                returned.append(identifier)
    if len(requested)!=2:
        return "WRONG_TOOL_COUNT"
    if len(set(i for i,_ in requested))!=2:
        return "REUSED_TOOL_ID"
    if [p for _,p in requested]!=["index.txt",target]:
        return "WRONG_READ_SEQUENCE"
    if [i for i in returned]!=[i for i,_ in requested]:
        return "MISSING_OR_MISORDERED_TOOL_RESULT"
    if final_count!=1:
        return "MISSING_FINAL_RESULT"
    return "PASS"

def selftest():
    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as d:
        root=Path(d)
        def make(paths=("index.txt","a.txt"), tool="read_file", error=False,
                 response_ids=None, ids=("id1","id2")):
            rows=[]
            for j,path in enumerate(paths):
                rows.append({"type":"assistant","message":{"content":[{
                    "type":"tool_use","id":ids[j],"name":tool,
                    "input":{"absolute_path":str(root/path)}
                }]}})
                rows.append({"type":"user","message":{"content":[{
                    "type":"tool_result","tool_use_id":response_ids[j] if response_ids else ids[j],
                    "is_error":error
                }]}})
            rows.append({"type":"result","is_error":False,"result":"VALUE=GOOD"})
            return json.dumps(rows)
        assert lineage_verdict(make(),root,"a.txt")=="PASS"
        assert lineage_verdict(make(paths=("index.txt","b.txt")),root,"b.txt")=="PASS"
        cases=[
            (make(paths=("a.txt","index.txt")),"a.txt"),
            (make(paths=("index.txt","index.txt")),"a.txt"),
            (make(paths=("index.txt","b.txt")),"a.txt"),
            (make(tool="run_shell_command"),"a.txt"),
            (make(error=True),"a.txt"),
            (make(response_ids=("id1","WRONG")),"a.txt"),
            (make(ids=("id1","id1")),"a.txt"),
            (make(paths=("index.txt","../secret.txt")),"a.txt"),
            (make(paths=("index.txt","/etc/passwd")),"a.txt"),
            ('{"type":"result"}',"a.txt"),
            ("not-json","a.txt"),
        ]
        for value,target in cases:
            assert lineage_verdict(value,root,target)!="PASS","lineage mutant accepted"
        assert lineage_verdict(make(),root,"../../x")=="INVALID_TARGET"
        ordered=json.loads(make())
        for order in ((1,0,2,3,4),(0,2,1,3,4),(0,1,4,2,3),(4,0,1,2,3)):
            assert lineage_verdict(json.dumps([ordered[i] for i in order]),root,"a.txt")!="PASS","causal-order mutant accepted"
        for index, role in ((0,"user"),(1,"assistant"),(0,None),(1,None)):
            mutant=json.loads(make())
            if role is None:
                del mutant[index]["type"]
            else:
                mutant[index]["type"]=role
            assert lineage_verdict(json.dumps(mutant),root,"a.txt")!="PASS","wrong frame producer accepted"
        malformed=[]
        sample=make()
        malformed.append(sample.replace('"type": "assistant"', '"type": "user", "type": "assistant"', 1))
        malformed.append(sample.replace('"result": "VALUE=GOOD"', '"result": "VALUE=GOOD", "metric": NaN'))
        malformed.append(sample.replace('"result": "VALUE=GOOD"', '"result": "VALUE=GOOD", "metric": 1e999'))
        malformed.append(json.dumps(ordered[:-1]))
        malformed.append(json.dumps(ordered+[ordered[-1]]))
        malformed.append(json.dumps(ordered+[{"type":"assistant","message":{"content":[]}}]))
        malformed.append(make(paths=("index.txt", "a.txt\0")))
        mutant=json.loads(sample)
        mutant[0]["message"]["content"].append(17)
        malformed.append(json.dumps(mutant))
        malformed.append(json.dumps([{"type":"assistant","message":[]}]+ordered))
        malformed.append("["*1500+"0"+"]"*1500)
        for value in malformed:
            assert lineage_verdict(value,root,"a.txt")!="PASS","malformed lineage accepted"
        print(json.dumps({"schema":"qwen-r15-lineage-critic/v1","state":"PASS",
                          "positive_cases":2,"negative_cases":20+len(malformed),
                          "source_class":"SYNTHETIC_NO_MODEL"}))

if __name__=="__main__":
    selftest()
