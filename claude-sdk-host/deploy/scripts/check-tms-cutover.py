#!/usr/bin/env python3
"""Read-only source/config gate. Never switches a backend, contacts a server or queries a model."""

import argparse
import ast
import json
import subprocess
from pathlib import Path

REQUIRED = {
    "src/services/ai/llm_backend.py": ("CLAUDE_HOST",),
    "src/services/ai/claude_host_client.py": ("ClaudeHostClient",),
    "src/tms/agents/host/api.py": ("credentials",),
    "src/tms/agents/host/grants.py": ("repair_browser", "repair_author", "worker_attempt"),
    "src/tms/agents/host/adapters.py": ("bind_repair_claim", "HostTestAuthor"),
    "src/tms/agents/authoring/browser_pass.py": ("bind_repair_claim",),
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tms-root", type=Path, required=True)
    parser.add_argument("--required-ref", help="Require a tested integration commit to be an ancestor of this checkout")
    parser.add_argument("--config", type=Path, help="Operator host-config.json; values are never printed")
    args = parser.parse_args()
    root = args.tms_root.resolve()
    revision = subprocess.check_output(["git", "-C", str(root), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(["git", "-C", str(root), "status", "--porcelain", "--untracked-files=no"], text=True):
        raise ValueError("tms_tracked_changes_not_committed")
    if args.required_ref:
        subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", args.required_ref, "HEAD"],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    base = root / "test_importer_web/backend"
    for name, markers in REQUIRED.items():
        relative = f"test_importer_web/backend/{name}"
        subprocess.run(
            ["git", "-C", str(root), "ls-files", "--error-unmatch", relative],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        source = (base / name).read_text()
        ast.parse(source)
        if any(marker not in source for marker in markers):
            raise ValueError("tms_private_host_contract_missing")
    if args.config:
        cfg = json.loads(args.config.read_text())
        app = next(item for item in cfg["applications"] if item["id"] == "tms")
        needed = {"completion", "session:create", "session:read", "session:cancel"}
        if not needed <= set(app["scopes"]) or "claude-personal-default" not in app["models"]:
            raise ValueError("tms_host_scopes_or_model_mismatch")
        if "http://10.253.240.20:8000/mcp/tms-execution" not in app["mcp_endpoints"]:
            raise ValueError("tms_mcp_overlay_url_mismatch")
        provider = cfg["credential_providers"]["tms"]
        if provider["url"] != "https://10.253.240.21:8443/api/v1/internal/claude-host/credentials":
            raise ValueError("tms_provider_overlay_url_mismatch")
        if provider.get("tunnel_host") != "10.253.240.22":
            raise ValueError("tms_tunnel_overlay_mismatch")
        if cfg.get("max_agent_seconds", 14400) < 14400 or cfg.get("max_agent_tokens", 2000000) < 10000000:
            raise ValueError("host_cap_smaller_than_authoring_ui_range")
    print(
        json.dumps(
            {
                "status": "source_contract_ready",
                "tms_revision": revision,
                "mode": "read-only",
                "live_inference_verified": False,
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError):
        raise SystemExit("cutover_source_or_config_check_failed; no backend or server changed") from None
