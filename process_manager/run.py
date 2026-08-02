"""Command-line entrypoint for the Process Manager service."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from .server import WILDCARD_HOSTS, create_server


def _default_audit_path() -> Path:
    return Path.home() / ".local" / "state" / "nv-process-manager" / "audit.jsonl"


def _read_token(args: argparse.Namespace) -> str:
    if args.token_file:
        return Path(args.token_file).read_text(encoding="utf-8").strip()
    return args.token or os.environ.get("PROCESS_MANAGER_TOKEN", "")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Authenticated Linux process manager")
    parser.add_argument("--host", default=os.environ.get("PROCESS_MANAGER_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PROCESS_MANAGER_PORT", "9001")))
    parser.add_argument("--token", help="development-only token; prefer PROCESS_MANAGER_TOKEN")
    parser.add_argument("--token-file")
    parser.add_argument(
        "--audit-log",
        type=Path,
        default=Path(os.environ.get("PROCESS_MANAGER_AUDIT_LOG", _default_audit_path())),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.host in WILDCARD_HOSTS and os.environ.get("PROCESS_MANAGER_ALLOW_WILDCARD") != "1":
        parser.error("wildcard host requires PROCESS_MANAGER_ALLOW_WILDCARD=1")
    token = _read_token(args)
    if not token:
        parser.error("provide --token-file, --token, or PROCESS_MANAGER_TOKEN")
    server = create_server(args.host, args.port, token=token, audit_log_path=args.audit_log)
    print(f"Process Manager listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
