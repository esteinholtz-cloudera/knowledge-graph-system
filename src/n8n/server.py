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

    from src.config.settings import load_config

    cfg = load_config(str(project_root / "config" / "config.yaml")).n8n
    parser = argparse.ArgumentParser(description="Knowledge Graph API Server")
    parser.add_argument("--host", default=cfg.host)
    parser.add_argument("--port", type=int, default=cfg.port)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()
    app.run(host=args.host, port=args.port, debug=args.debug or cfg.debug)
