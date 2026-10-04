"""Run the agent service: python -m mavmind_agent"""

from __future__ import annotations

import argparse
import logging

import uvicorn

from .api import create_app
from .config import load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="MAVMind agent service")
    parser.add_argument("--config", help="path to agent.yaml (default config/agent.yaml)")
    parser.add_argument("--vehicle-url", help="vehicle service base URL (overrides config)")
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = load_config(args.config)
    if args.vehicle_url:
        cfg.vehicle_url = args.vehicle_url
    app = create_app(cfg)
    uvicorn.run(app, host=args.host or cfg.host, port=args.port or cfg.port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
