#!/usr/bin/env python3
"""Direct-packet LLM actuator for Model Spelunker qualification tasks.

IMPORTANT BOUNDARY (R05):
This adapter is a single-shot direct-packet file-replacement actuator
(`kind: direct-packet-actuator`, `whole_actor_equivalent: false`), NOT a
whole-actor multi-turn tool-loop harness (`openworker`, `goose`, `codex-exec`).
It enforces:
1. Strict workspace path confinement (no absolute paths, `..`, or symlink escapes).
2. Hard local fail-closed cost guardrails (blocks paid `deepseek` and unapproved
   metered routes locally before any network I/O).
3. Secret/token redaction on all error and diagnostic surfaces.
4. Explicit usage-source attribution (`api-reported` vs `heuristic-char-div-4`).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

APPROVED_ZERO_COST_BYOK_PROVIDERS = frozenset({
    "google-ai-studio",
    "groq",
    "mistral",
    "nvidia",
})

BLOCKED_PAID_PROVIDERS = frozenset({
    "deepseek",
    "sambanova",
})


class ActuatorPolicyError(ValueError):
    """Raised when path confinement or fail-closed cost policy is violated."""


def sanitize_text(text: str, secret: str = "") -> str:
    """Redact API keys, Bearer tokens, and explicit secret strings from output."""
    out = text or ""
    if secret and len(secret) >= 6:
        out = out.replace(secret, "[REDACTED_SECRET]")
    out = re.sub(r"Bearer\s+[A-Za-z0-9._\-]+", "Bearer [REDACTED_TOKEN]", out)
    out = re.sub(r"sk-or-v1-[A-Za-z0-9._\-]+", "[REDACTED_OR_KEY]", out)
    return out


def resolve_confined_target(
    write_target_rel: str,
    workspace_root: Path | None = None,
    allowed_write_paths: list[str] | None = None,
) -> Path:
    """Resolve and validate write_target_rel strictly inside workspace_root."""
    root = (workspace_root or Path.cwd()).resolve()
    if not write_target_rel or not write_target_rel.strip():
        raise ActuatorPolicyError("PATH_CONFINEMENT_VIOLATION: empty write target")

    raw_rel = Path(write_target_rel)
    if raw_rel.is_absolute():
        raise ActuatorPolicyError(
            f"PATH_CONFINEMENT_VIOLATION: absolute path prohibited: {write_target_rel}"
        )
    if ".." in raw_rel.parts:
        raise ActuatorPolicyError(
            f"PATH_CONFINEMENT_VIOLATION: parent traversal prohibited: {write_target_rel}"
        )

    normalized_rel = raw_rel.as_posix()
    if allowed_write_paths is not None:
        normalized_allowed = {Path(p).as_posix() for p in allowed_write_paths if p}
        if normalized_rel not in normalized_allowed:
            raise ActuatorPolicyError(
                f"PATH_CONFINEMENT_VIOLATION: {normalized_rel!r} not in allowed_write_paths"
            )

    # Walk every path component from root to reject symlinks inside the workspace
    current = root
    for part in raw_rel.parts:
        current = current / part
        if current.is_symlink():
            raise ActuatorPolicyError(
                f"PATH_CONFINEMENT_VIOLATION: symlink component prohibited: {write_target_rel}"
            )

    resolved = current.resolve()
    if not resolved.is_relative_to(root):
        raise ActuatorPolicyError(
            f"PATH_CONFINEMENT_VIOLATION: target escapes workspace root: {write_target_rel}"
        )
    return resolved


def extract_code(text: str) -> str:
    pattern = r"```(?:python)?\s*\n(.*?)\n```"
    matches = re.findall(pattern, text, re.DOTALL)
    if matches:
        return matches[-1].strip() + "\n"
    return text.strip() + "\n"


def resolve_provider_order(model: str) -> list[str]:
    explicit = os.environ.get("MODEL_SPELUNKER_PROVIDER_PIN", "").strip().lower()
    if explicit:
        return [explicit]
    lower = model.lower()
    if lower.startswith("google/"):
        return ["google-ai-studio"]
    if lower.startswith("mistralai/"):
        return ["mistral"]
    if "groq" in lower or lower.startswith("meta-llama/") or lower.startswith("openai/gpt-oss"):
        return ["groq"]
    if "nvidia" in lower:
        return ["nvidia"]
    return []


def check_route_policy(model: str) -> tuple[str, list[str]]:
    """Enforce fail-closed local cost gate before any network call."""
    raw_model = model.replace("openrouter/", "", 1).strip()
    lower_model = raw_model.lower()
    order = resolve_provider_order(raw_model)

    for blocked in BLOCKED_PAID_PROVIDERS:
        if blocked in lower_model or blocked in order:
            raise ActuatorPolicyError(
                f"PAID_PROVIDER_BLOCKED: provider/model {model!r} is blocked by local fail-closed cost policy"
            )

    is_cloud = model.startswith("openrouter/") or "/" in model
    if is_cloud:
        is_explicit_free = lower_model == "free" or lower_model.endswith(":free")
        is_approved_byok = bool(order) and all(
            p in APPROVED_ZERO_COST_BYOK_PROVIDERS for p in order
        )
        allow_paid = os.environ.get("MODEL_SPELUNKER_ALLOW_PAID") == "1"
        if not (is_explicit_free or is_approved_byok or allow_paid):
            raise ActuatorPolicyError(
                f"UNAPPROVED_CLOUD_ROUTE_BLOCKED: {model!r} is neither a ':free' endpoint "
                f"nor pinned to an audited zero-cost BYOK provider ({sorted(APPROVED_ZERO_COST_BYOK_PROVIDERS)})"
            )

    return raw_model, order


def query_llm(model: str, prompt: str) -> tuple[int, str, dict, dict]:
    raw_model, order = check_route_policy(model)
    if model.startswith("openrouter/") or "/" in model:
        api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if not api_key:
            secrets_path = Path.home() / ".config" / "goose" / "secrets.yaml"
            if secrets_path.exists():
                for line in secrets_path.read_text(encoding="utf-8").splitlines():
                    if line.startswith("OPENROUTER_API_KEY:"):
                        api_key = line.split(":", 1)[1].strip().strip('"').strip("'")
                        break
        max_tokens = int(os.environ.get("MODEL_SPELUNKER_MAX_TOKENS", "1024"))
        payload: dict = {
            "model": raw_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.0,
        }
        if order:
            payload["provider"] = {"order": order, "allow_fallbacks": False}

        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://github.com/SemperSupra/model-spelunker",
                "X-Title": "model-spelunker-actuator",
            },
        )
        profile_meta = {
            "kind": "direct-packet-actuator",
            "whole_actor_equivalent": False,
            "single_shot": True,
            "transport": "openrouter-http",
            "provider_order": order,
            "allow_fallbacks": False if order else True,
            "timeout_seconds": 30,
        }
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                content = data["choices"][0]["message"]["content"]
                usage = data.get("usage", {})
                has_exact = "prompt_tokens" in usage and "completion_tokens" in usage
                profile_meta["usage_source"] = "api-reported" if has_exact else "heuristic-char-div-4"
                return 0, content, {
                    "input": usage.get("prompt_tokens", len(prompt) // 4),
                    "output": usage.get("completion_tokens", len(content) // 4),
                    "cache_read": 0,
                    "cache_write": 0,
                }, profile_meta
        except urllib.error.HTTPError as e:
            err_msg = sanitize_text(e.read().decode("utf-8", errors="replace"), api_key)
            return 1, f"HTTP_{e.code}: {err_msg}", {}, profile_meta
        except Exception as e:
            return 1, sanitize_text(str(e), api_key), {}, profile_meta
    else:
        llm_bin = shutil.which("llm") or str(Path.home() / ".local" / "bin" / "llm")
        profile_meta = {
            "kind": "direct-packet-actuator",
            "whole_actor_equivalent": False,
            "single_shot": True,
            "transport": "local-llm-cli",
            "usage_source": "heuristic-char-div-4",
            "timeout_seconds": 60,
        }
        proc = subprocess.run(
            [llm_bin, "-m", model, prompt],
            text=True,
            capture_output=True,
            timeout=60,
        )
        if proc.returncode != 0:
            return proc.returncode, sanitize_text(proc.stderr), {}, profile_meta
        content = proc.stdout
        return 0, content, {
            "input": len(prompt) // 4,
            "output": len(content) // 4,
            "cache_read": 0,
            "cache_write": 0,
        }, profile_meta


def main() -> int:
    instruction = sys.stdin.read().strip()
    write_target_rel = os.environ.get("MODEL_SPELUNKER_WRITE_TARGET", "src/retry.py")
    allowed_env = os.environ.get("MODEL_SPELUNKER_ALLOWED_WRITE_PATHS", "").strip()
    allowed_list = [p.strip() for p in allowed_env.split(",") if p.strip()] if allowed_env else None

    try:
        target_path = resolve_confined_target(
            write_target_rel,
            workspace_root=Path.cwd(),
            allowed_write_paths=allowed_list,
        )
    except ActuatorPolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if not target_path.exists():
        print(f"Target file {write_target_rel} does not exist", file=sys.stderr)
        return 2

    original_content = target_path.read_text(encoding="utf-8")
    model = os.environ.get("MODEL_SPELUNKER_MODEL", "local-coder")

    prompt = (
        f"You are an expert software engineer.\n"
        f"TASK: {instruction}\n\n"
        f"EXISTING FILE ({write_target_rel}):\n"
        f"```python\n{original_content}\n```\n\n"
        f"Output ONLY the complete, corrected replacement content for {write_target_rel}.\n"
        f"If the file is python code, wrap it in a single ```python codeblock.\n"
        f"Do not include any explanation or commentary."
    )

    try:
        code, response_text, usage, profile_meta = query_llm(model, prompt)
    except ActuatorPolicyError as exc:
        print(str(exc), file=sys.stderr)
        return 3

    if code != 0:
        print(f"LLM execution failed: {response_text}", file=sys.stderr)
        return code

    repaired_code = extract_code(response_text)
    target_path.write_text(repaired_code, encoding="utf-8")

    # Emit standard telemetry markers for run_task parser plus explicit direct-packet boundary
    print(f"MODEL_SPELUNKER_USAGE={json.dumps(usage)}")
    print(f"MODEL_SPELUNKER_ACTUATOR_PROFILE={json.dumps(profile_meta, sort_keys=True)}")
    print("MODEL_SPELUNKER_TOOL_CALLS=1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
