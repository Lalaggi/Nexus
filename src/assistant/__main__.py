"""CLI entry point."""

from __future__ import annotations

import argparse

import uvicorn

from .config import CONFIG


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Assistant web app")
    parser.add_argument("--host", default=CONFIG.host)
    parser.add_argument("--port", type=int, default=CONFIG.port)
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    if args.reload:
        uvicorn.run(
            "assistant.main:app",
            host=args.host,
            port=args.port,
            reload=True,
            reload_dirs=[str(CONFIG.data_dir.parent / "src")],
        )
    else:
        uvicorn.run(
            "assistant.main:app",
            host=args.host,
            port=args.port,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
        )


if __name__ == "__main__":
    main()
