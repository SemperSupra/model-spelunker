#!/usr/bin/env python3
"""Strict Qwen JSON result oracle; never interpret tool output as final completion."""
import json

class InvalidResult(ValueError):
    pass

def extract_final_response(stdout: str) -> str:
    try:
        messages=json.loads(stdout)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidResult("invalid CLI JSON") from exc
    if not isinstance(messages,list):
        raise InvalidResult("batch JSON must be a list")
    results=[v for v in messages if isinstance(v,dict) and v.get("type")=="result"]
    if len(results)!=1:
        raise InvalidResult("missing/duplicate final result")
    result=results[0]
    if result.get("is_error") is not False or not isinstance(result.get("result"),str):
        raise InvalidResult("error or missing final text")
    return result["result"].strip()

def verify_selected(stdout: str, expected: str, decoy: str) -> bool:
    try:
        return extract_final_response(stdout)==expected and expected!=decoy
    except InvalidResult:
        return False

def selftest() -> None:
    def payload(final,tool="VALUE=DECOY",error=False):
        return json.dumps([
            {"type":"assistant","message":{"content":[{"type":"tool_use","name":"read_file"}]}},
            {"type":"user","message":{"content":[{"type":"tool_result","content":tool}]}},
            {"type":"result","is_error":error,"result":final},
        ])
    selected="VALUE=SELECTED"
    decoy="VALUE=DECOY"
    assert verify_selected(payload(selected),selected,decoy)
    adversarial=[
        payload(decoy,selected),
        payload("",selected),
        payload(selected+" extra",selected),
        payload(selected,error=True),
        json.dumps([{"type":"user","result":selected}]),
        json.dumps([{"type":"result","is_error":False,"result":selected}]*2),
        json.dumps({"type":"result","is_error":False,"result":selected}),
        "not JSON",
        json.dumps([{"type":"result","is_error":False,"result":["VALUE=SELECTED"]}]),
    ]
    for bad in adversarial:
        assert not verify_selected(bad,selected,decoy),"bad assistant final accepted"
    print(json.dumps({"schema":"qwen-r12-strict-final-oracle/v1","state":"PASS","positives":1,"negatives":len(adversarial)}))

if __name__=="__main__":
    selftest()
