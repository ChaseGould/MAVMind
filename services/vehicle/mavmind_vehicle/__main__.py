"""Run the vehicle service: python -m mavmind_vehicle --profile sitl"""

from __future__ import annotations

import argparse
import logging
import os

import uvicorn

from .api import create_app
from .config import load_profile
from .service import VehicleService


def main() -> None:
    parser = argparse.ArgumentParser(description="MAVMind vehicle service")
    parser.add_argument("--profile", default=os.environ.get("MAVMIND_PROFILE", "sitl"), help="profile name or path")
    parser.add_argument("--host", help="bind address (default from the profile)")
    parser.add_argument("--port", type=int, help="port (default from the profile)")
    parser.add_argument(
        "--no-connect", action="store_true", help="start without connecting; pick a profile from the UI"
    )
    parser.add_argument("--log-level", default="info")
    args = parser.parse_args()

    logging.basicConfig(level=args.log_level.upper(), format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    profile = load_profile(args.profile)
    host = args.host or profile.host
    port = args.port or profile.port
    app = create_app(VehicleService(), profile=None if args.no_connect else args.profile, host=host)
    uvicorn.run(app, host=host, port=port, log_level=args.log_level.lower())


if __name__ == "__main__":
    main()
