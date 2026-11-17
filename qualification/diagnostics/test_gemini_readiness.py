"""Offline PS5.1 + loopback HTTP tests. Never loads an operator credential."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

ROOT = Path(__file__).resolve().parent
GOOD = {"candidates": [{"content": {"parts": [{"text": "READY"}]}, "finishReason": "STOP"}], "modelVersion": "synthetic-version", "usageMetadata": {"totalTokenCount": 3}}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        size = int(self.headers.get("Content-Length", 0))
        self.rfile.read(size)
        with self.server.guard:
            self.server.routes.append(self.path)
            spec = self.server.responses.pop(0)
        if spec.get("delay"):
            time.sleep(spec["delay"])
        self.send_response(spec["status"])
        for key, value in spec.get("headers", {}).items():
            self.send_header(key, value)
        self.end_headers()
        try:
            self.wfile.write(spec.get("body", "").encode())
        except (BrokenPipeError, ConnectionResetError):
            pass


@unittest.skipUnless(os.name == 'nt', 'Native Windows PowerShell 5.1 required')
class DiagnosticTests(unittest.TestCase):
    def entry_rejection(self, failure):
        with tempfile.TemporaryDirectory(prefix="gemini-diag-admission-") as folder:
            folder = Path(folder)
            cell = folder / "cell"
            cell.mkdir()
            prompt = "Return exactly READY as a synthetic connectivity check without tools."
            (cell / "prompt.txt").write_text(prompt, encoding="utf-8")
            manifest = {"classification": "PUBLIC_RELEASE_APPROVED", "authority": "SemperSupra/model-spelunker#199", "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest()}
            proof = {"passed": 36, "failed": 0, "module_sha256": hashlib.sha256((ROOT / "GeminiReadiness.psm1").read_bytes()).hexdigest(), "entry_sha256": hashlib.sha256((ROOT / "Invoke-GeminiReadiness.ps1").read_bytes()).hexdigest()}
            expected = "synthetic data admission"
            if failure == "proof":
                proof["module_sha256"] = "0" * 64
                expected = "fake-test proof"
            elif failure == "extra":
                (cell / "unapproved.txt").write_text("synthetic", encoding="utf-8")
                expected = "unapproved workcell entries"
            elif failure == "classification":
                manifest["classification"] = "UNKNOWN"
            else:
                (cell / "prompt.txt").write_text("different synthetic prompt", encoding="utf-8")
            (cell / ".public-ai-approval.json").write_text(json.dumps(manifest), encoding="utf-8")
            (folder / "proof.json").write_text(json.dumps(proof), encoding="utf-8")
            powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT"}}
            env["USERPROFILE"] = str(folder / "empty-home")
            run = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-File", str(ROOT / "Invoke-GeminiReadiness.ps1"), "-Workcell", str(cell), "-TestProof", str(folder / "proof.json"), "-OutputPath", str(folder / "receipt.json"), "-SourceCommit", "0" * 40, "-BillingEvidenceRef", "unused-in-rejected-case"], env=env, capture_output=True, text=True, timeout=10)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn(expected, run.stderr)
            self.assertFalse((folder / "receipt.json").exists())

    def test_entry_stale_proof(self):
        self.entry_rejection("proof")

    def test_entry_changed_prompt(self):
        self.entry_rejection("prompt")

    def test_entry_unknown_classification(self):
        self.entry_rejection("classification")

    def test_entry_unapproved_file(self):
        self.entry_rejection("extra")

    def bridge(self, case):
        if os.name != "nt":
            self.skipTest("Native Windows PowerShell 5.1 required")
        with tempfile.TemporaryDirectory(prefix="gemini-diag-fake-") as folder:
            folder = Path(folder)
            script = folder / "bridge.ps1"
            script.write_text(r'''
param($ModulePath, $CaseFile)
$ErrorActionPreference = 'Stop'
Import-Module $ModulePath -Force
$case = Get-Content -LiteralPath $CaseFile -Raw | ConvertFrom-Json
if ($case.action -eq 'request') {
    $response = Invoke-GeminiHttp -Uri $case.uri -Method POST -ApiKey 'synthetic-test-key' -Body '{}' -AllowLoopbackForTest -TimeoutMs $case.timeout
} elseif ($case.action -eq 'treatment') {
    $result = Invoke-GeminiTreatment -ApiKey 'synthetic-test-key' -Body '{}' -BaseUri $case.uri -AllowLoopbackForTest
    $result | ConvertTo-Json -Depth 16 -Compress
    exit 0
} elseif ($case.action -eq 'route-deny') {
    try { [void](Invoke-GeminiHttp -Uri $case.uri -Method GET -ApiKey 'synthetic-test-key'); throw 'route unexpectedly admitted' }
    catch { if ($_.Exception.Message -ne 'Unapproved diagnostic route.') { throw }; @{denied=$true} | ConvertTo-Json -Compress; exit 0 }
} else {
    $response = @{}
    foreach ($property in $case.response.PSObject.Properties) { $response[$property.Name] = $property.Value }
    $response.headers = @{}
    foreach ($property in $case.response.headers.PSObject.Properties) { $response.headers[$property.Name] = $property.Value }
}
$observation = ConvertTo-GeminiObservation -Response $response -Model 'synthetic-model' -Secret 'synthetic-test-key'
$plan = Get-GeminiNextStep -Observation $observation -Attempt $case.attempt -Now ([datetime]'2026-11-17T00:00:00Z')
@{observation=$observation;plan=$plan;ps_version=$PSVersionTable.PSVersion.ToString()} | ConvertTo-Json -Depth 16 -Compress
''', encoding="utf-8-sig")
            case_file = folder / "case.json"
            case_file.write_text(json.dumps(case), encoding="utf-8")
            env = {k: v for k, v in os.environ.items() if k.upper() in {"SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PATH", "PATHEXT"}}
            env["USERPROFILE"] = str(folder / "empty-home")
            powershell = Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
            run = subprocess.run([str(powershell), "-NoProfile", "-NonInteractive", "-File", str(script), str(ROOT / "GeminiReadiness.psm1"), str(case_file)], env=env, capture_output=True, text=True, timeout=35)
            self.assertEqual(run.returncode, 0, run.stderr)
            return json.loads(run.stdout)

    def wire(self, specs, treatment=False, timeout=1000):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        server.responses = list(specs)
        server.routes = []
        server.guard = threading.Lock()
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            output = self.bridge({"action": "treatment" if treatment else "request", "uri": f"http://127.0.0.1:{server.server_port}/probe", "timeout": timeout, "attempt": 1})
            return output, list(server.routes)
        finally:
            server.shutdown()
            server.server_close()
            worker.join()

    def test_wire_success(self):
        result, routes = self.wire([{"status": 200, "body": json.dumps(GOOD)}])
        self.assertEqual(result["observation"]["classification"], "direct-synthetic-success")
        self.assertEqual(result["plan"]["action"], "stop")
        self.assertTrue(result["ps_version"].startswith("5.1."))
        self.assertEqual(len(routes), 1)

    def test_redaction_allowlist_and_bounds(self):
        body = {"error": {"code": 503, "status": "UNAVAILABLE", "message": "synthetic-test-key Bearer private-token Authorization: Bearer prefixed-secret api_key=another-token https://evil.invalid/?key=hidden C:\\Users\\name\\secret " + "x" * 2000, "details": ["must-not-copy"]}}
        result, _ = self.wire([{"status": 503, "body": json.dumps(body), "headers": {"Authorization": "never-copy-header", "Set-Cookie": "never-copy-cookie", "x-request-id": "synthetic-test-key", "Content-Type": "application/json"}}])
        encoded = json.dumps(result)
        for forbidden in ("synthetic-test-key", "private-token", "prefixed-secret", "another-token", "hidden", "never-copy-header", "never-copy-cookie", "must-not-copy", "C:\\\\Users"):
            self.assertNotIn(forbidden, encoded)
        self.assertLess(len(result["observation"]["error"]["message"]), 530)
        self.assertIn("[REDACTED]", encoded)

    def test_wire_timeout(self):
        result, _ = self.wire([{"status": 200, "delay": .4}], timeout=100)
        self.assertEqual(result["observation"]["classification"], "transport-timeout")
        self.assertFalse(result["observation"]["http_received"])

    def test_no_redirect_follow(self):
        result, routes = self.wire([{"status": 302, "headers": {"Location": "http://127.0.0.1:1/secret"}}])
        self.assertEqual(result["observation"]["http_status"], 302)
        self.assertEqual(len(routes), 1)

    def test_three_call_treatment_budget(self):
        result, routes = self.wire([{"status": 503}] * 3, treatment=True)
        self.assertEqual(result["total_generation_attempts"], 3)
        self.assertEqual([r.split("/")[-1] for r in routes], ["gemini-3.8-flash:generateContent"] * 2 + ["gemini-3.6-flash:generateContent"])

    def test_auth_never_tries_alternate(self):
        result, routes = self.wire([{"status": 403}], treatment=True)
        self.assertEqual(len(routes), 1)
        self.assertIn("HOLD", result["result"])

    def test_404_alternate_gets_only_one_call(self):
        result, routes = self.wire([{"status": 404}, {"status": 503}], treatment=True)
        self.assertEqual(len(routes), 2)
        self.assertEqual(result["total_generation_attempts"], 2)

    def test_early_success_stops(self):
        result, routes = self.wire([{"status": 200, "body": json.dumps(GOOD)}], treatment=True)
        self.assertEqual(len(routes), 1)
        self.assertEqual(result["result"], "DIRECT_CONNECTIVITY_ONLY")

    def test_large_retry_after_stops(self):
        result, routes = self.wire([{"status": 503, "headers": {"Retry-After": "120"}}], treatment=True)
        self.assertEqual(len(routes), 1)
        self.assertIn("30s-bound", result["result"])


def observe_test(status, body, classification, headers=None, action=None, wait=None, transport=None):
    def test(self):
        response = {"status": status, "body": body, "headers": headers or {}, "http_received": status is not None, "transport_error": transport, "elapsed_ms": 12, "truncated": False}
        result = self.bridge({"action": "observe", "response": response, "attempt": 1})
        self.assertEqual(result["observation"]["classification"], classification)
        if action:
            self.assertEqual(result["plan"]["action"], action)
        if wait is not None:
            self.assertEqual(result["plan"]["wait_seconds"], wait)
    return test


CASES = {
    "429": (429, '{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}', "http-quota-or-rate-limit", {}, "retry-first", 1),
    "503": (503, '{"error":{"code":503,"status":"UNAVAILABLE"}}', "http-service-unavailable", {}, "retry-first", 1),
    "retry_seconds": (503, '', "http-service-unavailable", {"retry-after": "4"}, "retry-first", 4),
    "retry_date": (503, '', "http-service-unavailable", {"retry-after": "Tue, 17 Nov 2026 00:00:07 GMT"}, "retry-first", 7),
    "retry_invalid": (503, '', "http-service-unavailable", {"retry-after": "not-a-delay"}, "retry-first", 1),
    "retry_negative": (503, '', "http-service-unavailable", {"retry-after": "-3"}, "retry-first", 1),
    "401": (401, '', "http-authentication", {}, "stop"),
    "403": (403, '', "http-permission-or-entitlement", {}, "stop"),
    "404": (404, '', "http-model-or-route-not-found", {}, "probe-verified-alternate"),
    "malformed": (503, '<html>gateway unavailable</html>', "http-service-unavailable"),
    "absent": (503, '', "http-service-unavailable"),
    "misleading": (503, json.dumps(GOOD), "http-service-unavailable"),
    "200_error": (200, '{"error":{"code":503,"message":"not success"}}', "http-200-invalid-or-unexpected", {}, "stop"),
    "200_empty": (200, '', "http-200-invalid-or-unexpected", {}, "stop"),
    "billing": (503, '{"error":{"message":"Billing required"}}', "http-service-unavailable", {}, "stop"),
    "retry_info": (429, '{"error":{"details":[{"@type":"type.googleapis.com/google.rpc.RetryInfo","retryDelay":"5s"}]}}', "http-quota-or-rate-limit", {}, "retry-first", 5),
    "dns": (None, '', "transport-dns", {}, "stop", 0, "NameResolutionFailure"),
    "tls": (None, '', "transport-tls", {}, "stop", 0, "TrustFailure"),
    "proxy": (None, '', "transport-proxy-dns", {}, "stop", 0, "ProxyNameResolutionFailure"),
}
for name, args in CASES.items():
    setattr(DiagnosticTests, "test_observe_" + name, observe_test(*args))

for status, classification in ((401, "http-authentication"), (403, "http-permission-or-entitlement"), (404, "http-model-or-route-not-found"), (429, "http-quota-or-rate-limit"), (503, "http-service-unavailable")):
    def test_wire_status(self, code=status, expected=classification):
        result, routes = self.wire([{"status": code, "body": json.dumps({"error": {"code": code, "status": "SYNTHETIC", "message": "original fake response"}}), "headers": {"Content-Type": "application/json", "Retry-After": "2"}}])
        self.assertEqual(result["observation"]["http_status"], code)
        self.assertEqual(result["observation"]["classification"], expected)
        self.assertEqual(result["observation"]["error"]["code"], str(code))
        self.assertEqual(len(routes), 1)
    setattr(DiagnosticTests, "test_wire_http_" + str(status), test_wire_status)

for name, route in {"query_key": "https://generativelanguage.googleapis.com/v1beta/models?key=synthetic", "wrong_host": "https://evil.invalid/", "plain_http": "http://generativelanguage.googleapis.com/"}.items():
    def test_route(self, uri=route):
        self.assertTrue(self.bridge({"action": "route-deny", "uri": uri})["denied"])
    setattr(DiagnosticTests, "test_route_" + name, test_route)


class ReceiptVerificationRuntimeTests(unittest.TestCase):
    def test_optimized_python_cannot_accept_a_receipt(self):
        # A security/evidence verifier must never succeed with assertions disabled.
        result = subprocess.run(
            [sys.executable, "-O", "-c",
             "from qualification.diagnostics.verify_gemini_receipt import verify; verify({}, {})"],
            cwd=ROOT.parents[1], capture_output=True, text=True, timeout=20
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("RECEIPT_VALIDATION_DISABLED_BY_OPTIMIZATION", result.stderr)


if __name__ == "__main__":
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__]))
    if result.wasSuccessful() and not result.skipped:
        proof = {"passed": result.testsRun, "failed": 0, "module_sha256": hashlib.sha256((ROOT / "GeminiReadiness.psm1").read_bytes()).hexdigest(), "entry_sha256": hashlib.sha256((ROOT / "Invoke-GeminiReadiness.ps1").read_bytes()).hexdigest(), "runtime": "native Windows PowerShell 5.1; Python stdlib loopback fake HTTP server", "live_calls": 0}
        target = os.environ.get("GEMINI_DIAG_TEST_PROOF")
        if target:
            Path(target).write_text(json.dumps(proof, indent=2) + "\n", encoding="utf-8")
    raise SystemExit(not result.wasSuccessful())
