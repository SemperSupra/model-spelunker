import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
from loopback_proxy import Proxy


class PublicLoopbackContract(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix="qwen-proxy-tests-")
        self.state=Path(self.tmp.name,"metadata.json")
        self.server=Proxy(("127.0.0.1",0),self.state)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.url="http://127.0.0.1:"+str(self.server.server_port)

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=4)
        self.tmp.cleanup()

    def test_loopback_only_health_and_listed_model(self):
        self.assertEqual(self.server.server_address[0],"127.0.0.1")
        with urllib.request.urlopen(self.url+"/health",timeout=5) as r:
            self.assertEqual(json.load(r)["status"],"OK")
        with urllib.request.urlopen(self.url+"/v1/models",timeout=5) as r:
            self.assertEqual(json.load(r)["data"][0]["id"],"qwen3:1.7b")

    def test_no_generic_forwarding_or_secret_logging(self):
        req=urllib.request.Request(self.url+"/v1/other",
            data=b'{"Authorization":"Bearer fake-only","private":"synthetic"}',
            headers={"Content-Type":"application/json"})
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(req,timeout=5)
        self.assertEqual(e.exception.code,404)
        contents=self.state.read_text()
        self.assertEqual(json.loads(contents)["events"][0]["phase"],"unexpected-path")
        self.assertNotIn("fake-only",contents)
        self.assertNotIn("synthetic",contents)
        self.assertNotIn("Bearer",contents)

    def test_get_unknown_path_refused(self):
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.url+"/latest/allsecrets",timeout=5)
        self.assertEqual(e.exception.code,404)


if __name__=="__main__":
    unittest.main()
