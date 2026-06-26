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

    from src.config.settings import (
        ConfigOverrideError,
        add_override_arg,
        apply_cli_overrides,
        load_config,
    )

    config_path = str(project_root / "config" / "config.yaml")
    parser = argparse.ArgumentParser(description="Knowledge Graph API Server")
    add_override_arg(parser)
    parser.add_argument("--host", default=None, help="Default: n8n.host from config")
    parser.add_argument("--port", type=int, default=None, help="Default: n8n.port from config")
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    try:
        apply_cli_overrides(args.config_set, config_path)
    except ConfigOverrideError as e:
        parser.error(str(e))

    cfg = load_config(config_path).n8n
    host = args.host if args.host is not None else cfg.host
    port = args.port if args.port is not None else cfg.port
    debug = args.debug or cfg.debug
    app.run(host=host, port=port, debug=debug)
