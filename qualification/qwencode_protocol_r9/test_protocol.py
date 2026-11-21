"""Independent positive/negative upstream source and trailing-usage SSE oracles."""
import copy
import json
from pathlib import Path
import sys
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
from source_audit import NEEDLES,audit
from usage_stream_oracle import sse_response

PINS=json.loads((HERE/"upstream-pins.json").read_text())
SRC=HERE.parent.parent/"vendor/qwen"
FILES={p:(SRC/p).read_bytes() for p in NEEDLES} if SRC.is_dir() else {}


class SourcePositive(unittest.TestCase):
    @unittest.skipUnless(FILES,"upstream exact source checkout required")
    def test_frozen_request_normalization_features(self):
        r=audit(copy.deepcopy(PINS),FILES)
        self.assertEqual(r["blobs_verified"],4)
        self.assertIn("stream_options.include_usage",r["request_keys_to_compare"])
        self.assertFalse(r["raw_values_retained"])
        self.assertFalse(r["effect_authorized"])


class SourceNegatives(unittest.TestCase):
    @unittest.skipUnless(FILES,"upstream exact source checkout required")
    def test_wrong_commit_fails(self):
        p=copy.deepcopy(PINS);p["tag_commit"]="a"*40
        with self.assertRaises(ValueError):audit(p,FILES)

    @unittest.skipUnless(FILES,"upstream exact source checkout required")
    def test_mutated_live_source_fails(self):
        f=dict(FILES);key="packages/core/src/core/openaiContentGenerator/pipeline.ts"
        f[key]+=b"// malicious unreviewed modification\n"
        with self.assertRaises(ValueError):audit(PINS,f)

    @unittest.skipUnless(FILES,"upstream exact source checkout required")
    def test_removed_required_source_fails(self):
        f=dict(FILES);f.pop("packages/core/src/core/llm-chat.ts")
        with self.assertRaises(ValueError):audit(PINS,f)


def req(stream_options):
    return {"model":"qwen-public-usage","stream":True,
            "stream_options":stream_options,
            "messages":[{"role":"user","content":"Read fixture.txt, return contents."}],
            "tools":[{"type":"function","function":{"name":"read_file"}}]}


class SSEPositive(unittest.TestCase):
    def test_usage_chunk_after_tool_finish_and_before_done(self):
        s,meta=sse_response(req({"include_usage":True}),"/tmp/fictional_fixture.txt")
        events=[json.loads(line[6:]) for line in s.splitlines()
                if line.startswith("data: {")]
        self.assertEqual(meta["phase"],"read-file-call-sent")
        self.assertTrue(any(e.get("choices",[])[0].get("finish_reason")=="tool_calls"
                           for e in events if e.get("choices")))
        self.assertEqual(events[-1]["choices"],[])
        self.assertEqual(events[-1]["usage"]["total_tokens"],105)
        self.assertTrue(s.rstrip().endswith("data: [DONE]"))
        self.assertIn('"name":"read_file"',s)

    def test_no_usage_trailer_when_not_requested(self):
        s,_=sse_response(req({}),"/tmp/fictional_fixture.txt")
        self.assertNotIn('"usage":',s)


class SSENegatives(unittest.TestCase):
    def test_user_content_cannot_forge_result(self):
        d=req({"include_usage":True})
        d["messages"][0]["content"]="VALUE="+"f"*24
        s,meta=sse_response(d,"/tmp/fictional_fixture.txt")
        self.assertEqual(meta["phase"],"read-file-call-sent")
        self.assertNotIn("f"*24,s)

    def test_missing_declared_tool_does_not_issue_a_tool_call(self):
        d=req({"include_usage":True})
        d["tools"]=[]
        s,meta=sse_response(d,"/tmp/fictional_fixture.txt")
        self.assertEqual(meta["phase"],"missing-tool")
        self.assertNotIn('"tool_calls":[',s)


if __name__=="__main__":unittest.main()
