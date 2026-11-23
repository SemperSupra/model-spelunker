import json
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import mixed_load as r

class MockModel(BaseHTTPRequestHandler):
    slots=threading.Semaphore(2)
    reject=False
    def log_message(self,*args):pass
    def do_GET(self):
        if self.path!="/api/tags":self.send_error(404);return
        raw=json.dumps({"models":[{"name":"qwen3:1.7b","digest":"8f68893c685c"+"b"*52}]}).encode()
        self.send_response(200);self.send_header("Content-Length",str(len(raw)));self.end_headers()
        self.wfile.write(raw)
    def do_POST(self):
        data=json.loads(self.rfile.read(int(self.headers.get("Content-Length","0"))))
        assert data.get("stream") is True and data.get("think") is False
        kind="interactive" if "Interactive request:" in data["prompt"] else "batch"
        with type(self).slots:
            time.sleep(.003 if kind=="interactive" else .025)
            self.send_response(200);self.end_headers()
            replies=[{"response":"safe","done":False},
                     {"done":True,"prompt_eval_count":30 if kind=="interactive" else 1300,
                      "eval_count":4 if kind=="interactive" else 45,
                      "prompt_eval_duration":2000000,"eval_duration":3000000}]
            if type(self).reject:replies=replies[:1]
            for reply in replies:
                self.wfile.write((json.dumps(reply)+"\n").encode());self.wfile.flush()

class PolicyTests(unittest.TestCase):
    def setUp(self):
        MockModel.reject=False
        self.server=ThreadingHTTPServer(("127.0.0.1",0),MockModel)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url="http://127.0.0.1:%d"%self.server.server_port
        self.client=r.base.opener()
    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
    def test_pair_is_observed_and_comparable(self):
        a=r.trial(self.client,self.url,"qwen3:1.7b","burst2_then_interactive",1,3168100)
        b=r.trial(self.client,self.url,"qwen3:1.7b","soft_reserve1",1,3168110)
        self.assertTrue(r.validate_pair(a,b))
        for obj in (a,b):
            self.assertEqual({j["job"] for j in obj["jobs"]},set(r.TASKS))
            self.assertEqual(len(obj["jobs"]),3)
            self.assertGreater(obj["interactive_ttft_ms"],0)
            self.assertGreater(obj["wall_ms"],0)
            self.assertTrue(all(j["output_tokens"]>0 for j in obj["jobs"]))
    def test_reject_forged_token_parity_and_treatment(self):
        a=r.trial(self.client,self.url,"qwen3:1.7b","burst2_then_interactive",1,3168100)
        b=r.trial(self.client,self.url,"qwen3:1.7b","soft_reserve1",1,3168110)
        b["jobs"][0]["prompt_tokens"]=1
        with self.assertRaises(ValueError):r.validate_pair(a,b)
        with self.assertRaises(ValueError):r.validate_pair(b,a)
        with self.assertRaises(ValueError):r.trial(self.client,self.url,"qwen3:1.7b","unsafe-unmanaged",1,99)
    def test_missing_stream_done_fails_closed(self):
        MockModel.reject=True
        with self.assertRaises(RuntimeError):
            r.stream_work(self.client,self.url,"qwen3:1.7b","interactive",99)
    def test_no_remote_endpoint_and_no_human_data(self):
        for url in ("https://127.0.0.1:11434","http://example.com:11434","http://127.0.0.1:11434/path"):
            with self.assertRaises(ValueError):r.base.origin(url)
        self.assertNotIn("password",r.prompt("interactive",3168100).lower())
        self.assertNotIn("password",r.prompt("batch",3168100).lower())
if __name__=="__main__":unittest.main()
