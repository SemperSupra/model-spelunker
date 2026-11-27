#!/usr/bin/env python3
"""Strict Qwen JSON result oracle; never interpret tool output as final completion."""
import json

class InvalidResult(ValueError):
    pass

def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise InvalidResult("duplicate JSON key")
        value[key] = item
    return value


def _reject_constant(value):
    raise InvalidResult("non-finite JSON constant")


def _valid_fixture(expected: str, decoy: str) -> bool:
    return isinstance(expected, str) and isinstance(decoy, str) and bool(expected) and bool(decoy) and expected != decoy


def extract_final_response(stdout: str) -> str:
    try:
        messages=json.loads(stdout, object_pairs_hook=_unique_object, parse_constant=_reject_constant)
    except (json.JSONDecodeError, TypeError) as exc:
        raise InvalidResult("invalid CLI JSON") from exc
    if not isinstance(messages,list) or any(not isinstance(v,dict) for v in messages):
        raise InvalidResult("batch JSON must be a list of objects")
    results=[v for v in messages if isinstance(v,dict) and v.get("type")=="result"]
    if len(results)!=1:
        raise InvalidResult("missing/duplicate final result")
    result=results[0]
    if result.get("is_error") is not False or not isinstance(result.get("result"),str):
        raise InvalidResult("error or missing final text")
    return result["result"].strip()

def verify_selected(stdout: str, expected: str, decoy: str) -> bool:
    try:
        return _valid_fixture(expected, decoy) and extract_final_response(stdout)==expected
    except InvalidResult:
        return False

def classify_final(stdout: str, expected: str, decoy: str) -> str:
    if not _valid_fixture(expected, decoy):
        return "INVALID_OR_MISSING_RESULT"
    try:
        result=extract_final_response(stdout)
    except InvalidResult:
        return "INVALID_OR_MISSING_RESULT"
    if result==expected:
        return "EXACT_FINAL"
    if decoy in result:
        return "DECOY_IN_FINAL"
    if expected in result:
        return "EXPECTED_WITH_EXTRA"
    if not result:
        return "EMPTY_FINAL"
    return "WRONG_FINAL"


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
    assert classify_final(payload(selected),selected,decoy)=="EXACT_FINAL"
    adversarial=[
        payload(decoy,selected),
        payload("",selected),
        payload(selected+" extra",selected),
        payload(selected,error=True),
        json.dumps([{"type":"user","result":selected}]),
        json.dumps([{"type":"result","is_error":False,"result":selected}]*2),
        json.dumps({"type":"result","is_error":False,"result":selected}),
        "not JSON",
        '[{"type":"result","is_error":true,"is_error":false,"result":"VALUE=SELECTED"}]',
        '[17,{"type":"result","is_error":false,"result":"VALUE=SELECTED"}]',
        '[{"type":"result","is_error":false,"result":"VALUE=SELECTED","metric":NaN}]',
        json.dumps([{"type":"result","is_error":False,"result":["VALUE=SELECTED"]}]),
    ]
    for bad in adversarial:
        assert not verify_selected(bad,selected,decoy),"bad assistant final accepted"
    assert classify_final(payload(selected+" extra"),selected,decoy)=="EXPECTED_WITH_EXTRA"
    assert classify_final(payload(decoy),selected,decoy)=="DECOY_IN_FINAL"
    assert classify_final(payload(""),selected,decoy)=="EMPTY_FINAL"
    assert classify_final("not JSON",selected,decoy)=="INVALID_OR_MISSING_RESULT"
    for expected, other, final in ((selected, selected, selected), ("", decoy, ""), (selected, "", selected)):
        assert not verify_selected(payload(final),expected,other)
        assert classify_final(payload(final),expected,other)=="INVALID_OR_MISSING_RESULT"
    print(json.dumps({"schema":"qwen-r12-strict-final-oracle/v1","state":"PASS","positives":1,"negatives":len(adversarial)+3}))

if __name__=="__main__":
    selftest()
