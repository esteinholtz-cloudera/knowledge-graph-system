"""HTTP server for n8n integration and API v1."""
from pathlib import Path
import sys

project_root = Path(__file__).parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.app import create_app

app = create_app(project_root)


if __name__ == "__main__":
    import argparse

    from pydantic import ValidationError

    from src.config.settings import (
        load_config,
        overrides_from_cli,
        set_cli_overrides,
    )

    parser = argparse.ArgumentParser(description="Knowledge Graph API Server")
    parser.add_argument(
        "-c",
        "--set",
        action="append",
        dest="config_set",
        metavar="KEY=VALUE",
        default=[],
        help="Override config.yaml (dotted keys). Repeatable.",
    )
    parser.add_argument("--host", default=None, help="Default: n8n.host from config")
    parser.add_argument("--port", type=int, default=None, help="Default: n8n.port from config")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    if args.config_set:
        try:
            set_cli_overrides(overrides_from_cli(args.config_set))
            load_config(str(project_root / "config" / "config.yaml"))
        except ValueError as e:
            parser.error(str(e))
        except ValidationError as e:
            parser.error(f"Invalid config override: {e}")

    cfg = load_config(str(project_root / "config" / "config.yaml")).n8n
    host = args.host if args.host is not None else cfg.host
    port = args.port if args.port is not None else cfg.port
    debug = args.debug or cfg.debug
    app.run(host=host, port=port, debug=debug)
