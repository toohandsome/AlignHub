from __future__ import annotations

import argparse
import os

import uvicorn


def parse_args():
    parser = argparse.ArgumentParser(description="Start AgentScope backend server.")
    parser.add_argument("--host", default=os.getenv("APP_BIND_HOST", "0.0.0.0"), help="Bind host, default 0.0.0.0")
    parser.add_argument("--port", type=int, default=int(os.getenv("APP_PORT", "8000")), help="Bind port, default 8000")
    parser.add_argument(
        "--reload",
        action="store_true",
        default=os.getenv("APP_RELOAD", "false").lower() in {"1", "true", "yes", "on"},
        help="Enable auto reload",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    uvicorn.run("app.main:app", host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
