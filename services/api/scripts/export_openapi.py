"""Write the API's OpenAPI document to packages/contracts/openapi.json.

The web app generates its TypeScript types from this file (ADR-0011). CI re-runs this script
and fails if the committed file differs, so the contract and the code can't drift apart.

Usage: uv run python services/api/scripts/export_openapi.py
"""

import json
import sys
from pathlib import Path

from workforce_api.config import Settings
from workforce_api.main import create_app

OUTPUT = Path(__file__).resolve().parents[3] / "packages" / "contracts" / "openapi.json"


def main() -> int:
    # "test" settings include the dev sign-in route, which the web app uses locally.
    app = create_app(Settings(env="test", log_level="WARNING"))
    document = app.openapi()
    OUTPUT.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")
    print(
        f"Wrote {OUTPUT.relative_to(Path.cwd()) if OUTPUT.is_relative_to(Path.cwd()) else OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
