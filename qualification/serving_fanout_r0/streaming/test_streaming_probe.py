import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import streaming_probe as m

class Handler(BaseHTTPRequestHandler):
    fail = ""
    calls = 0
    lock = threading.Lock()
    def log_message(self,*args): pass
    def do_GET(self):
        if self.path!="/api/tags":self.send_error(404);return
        body=json.dumps({"models":[{"name":"qwen3:1.7b","digest":"8f68893c685c"+("a"*52)}]}).encode()
        self.send_response(200);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(body)));self.end_headers();self.wfile.write(body)
    def do_POST(self):
        if self.path!="/api/generate":self.send_error(404);return
        obj=json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))))
        if obj["stream"] is not True or obj["think"] is not False or not obj["prompt"].startswith("Synthetic cohort"):
            self.send_error(400);return
        with type(self).lock:type(self).calls += 1
        if type(self).fail == "redirect":
            self.send_response(302);self.send_header("Location","https://example.com/");self.end_headers();return
        self.send_response(200);self.send_header("Content-Type","application/x-ndjson");self.end_headers()
        chunks=[{"response":"hello","done":False},
                {"done":True,"total_duration":8000000,"prompt_eval_duration":3000000,
                 "eval_duration":4000000,"load_duration":1000000,
                 "eval_count":3,"prompt_eval_count":25}]
        if type(self).fail=="no_done":chunks=chunks[:1]
        if type(self).fail=="no_first":chunks=chunks[1:]
        for item in chunks:
            self.wfile.write((json.dumps(item)+"\n").encode());self.wfile.flush()

class TestStreaming(unittest.TestCase):
    def setUp(self):
        Handler.fail="";Handler.calls=0
        self.srv=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        self.thread=threading.Thread(target=self.srv.serve_forever,daemon=True)
        self.thread.start()
        self.base="http://127.0.0.1:"+str(self.srv.server_port)
        self.client=m.opener()
    def tearDown(self):
        self.srv.shutdown();self.srv.server_close();self.thread.join()
    def test_real_stream_counter_and_concurrency(self):
        self.assertEqual(len(m.digest(self.client,self.base)),64)
        a=m.condition(self.client,self.base,m.MODEL,1,4,"shared",31650)
        self.assertEqual(len(a["samples"]),4);self.assertEqual(Handler.calls,4)
        for item in a["samples"]:
            self.assertGreater(item["ttft_ms"],0)
            self.assertLessEqual(item["ttft_ms"],item["elapsed_ms"])
            self.assertEqual(item["prompt_tokens"],25)
        self.assertGreater(a["wall_ms"],0)
    def test_refuse_nonloopback(self):
        for raw in ("https://127.0.0.1:11434","http://example.com:11434",
                    "http://user:pass@127.0.0.1:11434","http://127.0.0.1:11434/other"):
            with self.assertRaises(ValueError):m.origin(raw)
    def test_negative_missing_stream_chunks(self):
        for failure in ("no_done","no_first","redirect"):
            Handler.fail=failure
            with self.assertRaises(Exception):
                m.stream_one(self.client,self.base,m.MODEL,123,0,"shared")
    def test_cohort_context_and_digest_drift(self):
        self.assertNotEqual(m.prompt(1,31650,"shared"),m.prompt(1,31651,"shared"))
        self.assertNotEqual(m.prompt(1,31650,"shared"),m.prompt(1,31650,"distinct"))
        with self.assertRaises(ValueError):m.digest(self.client,self.base,prefix="invalidprefix")
    def test_host_fingerprint_scope(self):
        info=m.fingerprint()
        self.assertIn("cpu_model",info);self.assertIn("cgroup_cpu_max",info)
        self.assertNotIn("hostname",info)
if __name__=="__main__":unittest.main()
