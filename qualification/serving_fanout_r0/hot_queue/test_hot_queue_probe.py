import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import hot_queue_probe as q

def rows(statuses,spread=10.0):
    return [{"request_index":i,"http_status":s,
             "offered_offset_ms":i*spread,
             "finished_offset_ms":1000.0+i*200,
             "ttft_ms":None if s!=200 else 10.0,
             "output_tokens":0 if s!=200 else 64,
             "input_tokens":0 if s!=200 else 480}
            for i,s in enumerate(statuses)]

class Handler(BaseHTTPRequestHandler):
    status_code=200
    def log_message(self,*args):pass
    def do_POST(self):
        payload=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        assert payload["stream"] is True and payload["think"] is False
        assert payload["options"]["num_predict"]==64
        self.send_response(type(self).status_code)
        self.end_headers()
        if type(self).status_code==200:
            for part in ({"response":"okay","done":False},
                         {"response":"","done":True,"prompt_eval_count":480,"eval_count":64}):
                self.wfile.write((json.dumps(part)+"\n").encode());self.wfile.flush()

class TestBoundaries(unittest.TestCase):
    def test_hot_loaded_global_bound_bypass_counterexample(self):
        r=rows([200]*6)
        self.assertEqual(q.classify(r),"EXCESS_REQUESTS_COMPLETED_OUTSIDE_GLOBAL_1_PLUS_1_BOUND")
    def test_all_but_two_rejected_compatible_not_proven(self):
        r=rows([200,200,503,503,503,503])
        self.assertEqual(q.classify(r),"GLOBAL_BOUND_COMPATIBLE_FOR_THIS_TRIAL")
    def test_skewed_arrival_and_invalid_result_are_not_overpromoted(self):
        self.assertEqual(q.classify(rows([200]*6,spread=150)),
            "INCONCLUSIVE_ARRIVAL_OVERLAP")
        self.assertEqual(q.classify(rows([200,503,500,503,200,503])),
            "UNEXPECTED_HTTP_RESULT")
    def test_missing_and_duplicate_evidence_fails_closed(self):
        with self.assertRaises(ValueError):q.classify(rows([200]*5))
        xs=rows([200]*6);xs[-1]["request_index"]=0
        with self.assertRaises(ValueError):q.classify(xs)
    def test_loopback_stream_and_rejection(self):
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        t=threading.Thread(target=server.serve_forever,daemon=True);t.start()
        try:
            url="http://127.0.0.1:%d"%server.server_port
            Handler.status_code=200
            o=q.one_request(url,"qwen3:1.7b",0,threading.Barrier(1),__import__("time").monotonic())
            self.assertEqual(o["http_status"],200)
            self.assertEqual(o["output_tokens"],64)
            Handler.status_code=503
            other=q.one_request(url,"qwen3:1.7b",1,threading.Barrier(1),__import__("time").monotonic())
            self.assertEqual(other["http_status"],503)
            self.assertIsNone(other["ttft_ms"])
        finally:
            server.shutdown();server.server_close();t.join()
if __name__=="__main__":unittest.main()
