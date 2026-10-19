"""Offline tests for the explicit local-only OpenWorker model route."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "adapters" / "local_openai_route.py"
spec = importlib.util.spec_from_file_location("local_openai_route", SOURCE)
assert spec and spec.loader
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def fake_dns(*ips):
    return [(0, 0, 0, "", (ip, 8080)) for ip in ips]


class ExplicitLocalRouteTests(unittest.TestCase):
    def test_no_implicit_or_public_default(self):
        for env in ({}, {"OPENAI_BASE_URL": "https://api.openai.com/v1"}):
            with self.assertRaises(route.LocalOpenAIRouteHold) as caught:
                route.resolve_local_openai_route("local-openai:code", env)
            self.assertEqual(str(caught.exception), "LOCAL_ENDPOINT_FORMAT_HOLD")

    def test_only_explicit_provider_prefix(self):
        with self.assertRaises(route.LocalOpenAIRouteHold) as caught:
            route.resolve_local_openai_route(
                "openai:code",
                {"MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "http://10.1.1.1:8080/v1"},
            )
        self.assertEqual(str(caught.exception), "LOCAL_MODEL_BINDING_REQUIRED")

    def test_exact_private_routes_and_placeholder_auth(self):
        for ip, host in (
            ("10.1.2.3", "10.1.2.3"),
            ("192.168.1.7", "private.invalid"),
            ("100.100.20.30", "100.100.20.30"),
            ("fd00::2", "[fd00::2]"),
            ("127.0.0.1", "127.0.0.1"),
        ):
            with self.subTest(ip=ip), patch.object(
                route.socket, "getaddrinfo", return_value=fake_dns(ip)
            ):
                url = f"http://{host}:8080/v1"
                model, base, key = route.resolve_local_openai_route(
                    "local-openai:qwen3-coder-30b",
                    {"MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": url},
                )
                self.assertEqual((model, base, key), ("qwen3-coder-30b", url, "local-no-auth"))

    def test_mixed_public_dns_must_fail(self):
        with patch.object(
            route.socket, "getaddrinfo", return_value=fake_dns("10.1.1.2", "8.8.8.8")
        ):
            with self.assertRaises(route.LocalOpenAIRouteHold) as caught:
                route.resolve_local_openai_route(
                    "local-openai:code",
                    {"MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "http://mixed.invalid/v1"},
                )
            self.assertEqual(str(caught.exception), "LOCAL_PRIVATE_ROUTE_REQUIRED")

    def test_no_authentication_over_http(self):
        with self.assertRaises(route.LocalOpenAIRouteHold) as caught:
            route.resolve_local_openai_route(
                "local-openai:code",
                {
                    "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "http://10.1.2.3:8080/v1",
                    "MODEL_SPELUNKER_LOCAL_OPENAI_API_KEY": "example-test-placeholder",
                },
            )
        self.assertEqual(str(caught.exception), "LOCAL_AUTHENTICATED_HTTP_HOLD")
        self.assertNotIn("example-test-placeholder", str(caught.exception))

    def test_authenticated_private_https(self):
        with patch.object(
            route.socket, "getaddrinfo", return_value=fake_dns("192.168.1.2")
        ):
            model, base, key = route.resolve_local_openai_route(
                "local-openai:code",
                {
                    "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "https://local.invalid/v1",
                    "MODEL_SPELUNKER_LOCAL_OPENAI_API_KEY": "example-test-placeholder",
                },
            )
        self.assertEqual(model, "code")
        self.assertEqual(base, "https://local.invalid/v1")
        self.assertEqual(key, "example-test-placeholder")

    def test_malformed_urls_and_model_ids(self):
        for url in (
            "http://[bad/v1",
            "https://user:pass@10.1.1.1/v1",
            "https://10.1.1.1/v1?secret=value",
            "https://10.1.1.1/other",
            "https://api.openai.com/v1",
            "",
        ):
            # Force every resolution to the public-IP negative fixture.
            # This test must never consult live DNS or the model endpoint.
            with self.subTest(url="sanitized"), patch.object(
                route.socket, "getaddrinfo", return_value=fake_dns("8.8.8.8")
            ):
                with self.assertRaises(route.LocalOpenAIRouteHold):
                    route.resolve_local_openai_route(
                        "local-openai:code",
                        {"MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": url},
                    )
        for model in ("local-openai:", "local-openai:code with spaces", "local-openai:code\n"):
            with self.subTest(model="invalid"):
                with self.assertRaises(route.LocalOpenAIRouteHold):
                    route.resolve_local_openai_route(
                        model,
                        {"MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "http://10.1.1.1/v1"},
                    )

    def test_inherited_proxy_never_carries_private_inference(self):
        for key in ("HTTP_PROXY", "http_proxy", "HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy"):
            env = {
                "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "http://10.1.2.3:8080/v1",
                key: "http://untrusted.invalid:3128",
            }
            with self.subTest(key=key), self.assertRaises(route.LocalOpenAIRouteHold) as caught:
                route.resolve_local_openai_route("local-openai:code", env)
            self.assertEqual(str(caught.exception), "LOCAL_AMBIENT_PROXY_HOLD")
            self.assertNotIn("untrusted.invalid", str(caught.exception))

    def test_empty_proxy_config_is_not_blocking(self):
        env = {
            "MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "http://10.1.2.3:8080/v1",
            "HTTPS_PROXY": "",
            "NO_PROXY": "*",
        }
        with patch.object(route.socket, "getaddrinfo", return_value=fake_dns("10.1.2.3")):
            model, _, key = route.resolve_local_openai_route("local-openai:code", env)
        self.assertEqual(model, "code")
        self.assertEqual(key, "local-no-auth")

    def test_dns_failure_redacts(self):
        with patch.object(route.socket, "getaddrinfo", side_effect=OSError("sensitive machine name")):
            with self.assertRaises(route.LocalOpenAIRouteHold) as caught:
                route.resolve_local_openai_route(
                    "local-openai:code",
                    {"MODEL_SPELUNKER_LOCAL_OPENAI_BASE_URL": "http://hidden.invalid/v1"},
                )
        self.assertEqual(str(caught.exception), "LOCAL_RESOLUTION_HOLD")
        self.assertNotIn("sensitive machine", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
