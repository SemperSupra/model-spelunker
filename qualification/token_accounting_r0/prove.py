"""Framework-only token accounting controls, actual tokenizer comparison, no inference."""
import hashlib,json,math,pathlib,sys
import tiktoken
from importlib.metadata import version
def digest(b):return "sha256:"+hashlib.sha256(b).hexdigest()
def metric(n,d):
    if n is None or d is None:return None
    if type(n) is not int or n<0 or type(d) not in (float,int) or not math.isfinite(d) or d<=0:raise ValueError("invalid count or duration")
    return n/d
def phase(r):
    if not r.get("tokenizer_identity") or not r.get("timing_source"):raise ValueError("missing identity or source")
    return {"prefill_tokens_per_second":metric(r["evaluated_input_tokens"],r["prefill_seconds"]),"decode_tokens_per_second":metric(r["generated_tokens"],r["decode_seconds"]),"visible_utf8_bytes_per_second":metric(r["visible_output_bytes"],r["client_wall_seconds"])}
def main():
    out=pathlib.Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True)
    corpus={"en":"The experiment completed successfully. Verify the evidence before accepting the result.","de":"Die Messung ist abgeschlossen. Überprüfen Sie die Ergebnisse und die Ressourcenverwendung.","th":"การทดลองเสร็จสิ้นแล้ว โปรดตรวจสอบหลักฐานและการใช้ทรัพยากร","code":"def verify(receipt):\n    return receipt['accepted'] and receipt['digest'] is not None\n","json":'{"status":"UNKNOWN","accepted":false,"cpu_seconds":0.125}',"mixed":"Status: bereit / พร้อม / ready — result_id=17."}
    rows=[]
    for name in ("cl100k_base","o200k_base"):
        enc=tiktoken.get_encoding(name)
        # Stable identity of public encoding rules, including special tokens and regex.
        identity=digest(json.dumps({"ranks":sorted((k.hex(),v) for k,v in enc._mergeable_ranks.items()),"special":enc._special_tokens,"pattern":enc._pat_str},sort_keys=True,separators=(",",":")).encode())
        for label,text in corpus.items():
            ids=enc.encode_ordinary(text)
            assert enc.decode(ids)==text
            rows.append({"fixture":label,"text_sha256":digest(text.encode()),"utf8_bytes":len(text.encode()),"unicode_codepoints":len(text),"encoding":name,"tokenizer_identity":identity,"native_text_tokens":len(ids),"bytes_per_token":len(text.encode())/len(ids)})
    assert any(rows[i]["native_text_tokens"]!=rows[i+6]["native_text_tokens"] for i in range(6))
    assert all(rows[i]["text_sha256"]==rows[i+6]["text_sha256"] for i in range(6))
    fixture={"tokenizer_identity":"synthetic","timing_source":"synthetic control","evaluated_input_tokens":120,"prefill_seconds":2,"generated_tokens":30,"decode_seconds":3,"visible_output_bytes":90,"client_wall_seconds":10}
    assert phase(fixture)=={"prefill_tokens_per_second":60,"decode_tokens_per_second":10,"visible_utf8_bytes_per_second":9}
    assert phase({**fixture,"prefill_seconds":None})["prefill_tokens_per_second"] is None
    for change in ({"prefill_seconds":0},{"generated_tokens":-1},{"decode_seconds":float("nan")},{"tokenizer_identity":None}):
        try:phase({**fixture,**change})
        except ValueError:pass
        else:raise AssertionError("invalid fixture accepted")
    result={"scope":"FRAMEWORK_PROVING_ONLY","tiktoken_version":version("tiktoken"),"tokenizer_source_release":"97e49cbadd500b5cc9dbb51a486f0b42e6701bee","rows":rows,"phase_controls":"PASS","missing_phase":"UNKNOWN","limitations":"actual text tokenization, synthetic phase timing only; no chat template, model inference, or operational comparison"}
    (out/"receipt.json").write_text(json.dumps(result,indent=2)+"\n")
    print("TOKEN_ACCOUNTING="+json.dumps(result),flush=True)
if __name__=="__main__":main()
