"""Operator entry point; configuration errors never print rejected values."""

import argparse
import os
from pathlib import Path

from .config import load_settings
from .contracts import RunFailure


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["serve", "check-config"], default="serve", nargs="?")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path(os.environ.get("CLAUDE_HOST_CONFIG", "/run/secrets/host-config.json")),
    )
    args = parser.parse_args()
    try:
        settings = load_settings(args.config)
        if args.command == "check-config":
            print("configuration_valid")
            return
        import uvicorn

        from .api import create_app

        uvicorn.run(
            create_app(args.config, settings=settings),
            host="0.0.0.0",
            port=8080,
            access_log=False,
            log_level="warning",
            limit_concurrency=128,
            timeout_graceful_shutdown=10,
        )
    except RunFailure as error:
        parser.exit(1, error.code + "\n")


if __name__ == "__main__":
    main()
