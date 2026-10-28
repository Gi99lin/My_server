#!/usr/bin/env python3
"""Explicit local-owner live acceptance: two tool-free SDK turns, no private task data."""

import argparse
import json
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:18080")
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--model", default="claude-personal-default")
    parser.add_argument("--run", action="store_true", help="Actually spend two model turns after official owner login")
    args = parser.parse_args()
    target = urlsplit(args.url)
    if target.scheme not in {"http", "https"} or not target.hostname or target.username or target.password:
        parser.error("invalid private host URL")
    if not args.run:
        print("DRY RUN: two tool-free completion requests; no token read or network call. Add --run after owner login.")
        return
    token = args.token_file.read_text().strip()
    opener = build_opener(ProxyHandler({}))
    for streaming in (False, True):
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": "Reply exactly LOCAL_SMOKE_OK"}],
            "stream": streaming,
        }
        if streaming:
            payload["stream_options"] = {"include_usage": True}
        request = Request(
            args.url.rstrip("/") + "/v1/chat/completions",
            data=json.dumps(payload).encode(),
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        )
        with opener.open(request, timeout=310) as response:
            if not streaming:
                body = json.load(response)
                text, usage = body["choices"][0]["message"]["content"], body["usage"]
            else:
                text, usage, done = "", None, False
                for line in response:
                    if not line.startswith(b"data:"):
                        continue
                    raw = line[5:].strip()
                    if raw == b"[DONE]":
                        done = True
                        break
                    body = json.loads(raw)
                    if "error" in body:
                        raise ValueError("live_stream_failed")
                    usage = body.get("usage") or usage
                    text += "".join(choice.get("delta", {}).get("content", "") for choice in body.get("choices", []))
                if not done:
                    raise ValueError("live_stream_incomplete")
        if text.strip() != "LOCAL_SMOKE_OK" or not usage or usage["total_tokens"] <= 0:
            raise ValueError("live_response_contract_failed")
        print(json.dumps({"stream": streaming, "status": "passed", "usage": usage}))


if __name__ == "__main__":
    try:
        main()
    except (OSError, HTTPError, URLError, ValueError, KeyError):
        raise SystemExit("live_smoke_failed; inspect private host status (no response body or token printed)") from None
