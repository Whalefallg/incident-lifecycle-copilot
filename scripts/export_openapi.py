"""Export the FastAPI schema for frontend client generation."""

import json
import os
import sys
from pathlib import Path

CALLER_DIRECTORY = Path.cwd()
PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))
os.chdir(PROJECT_ROOT)


def main() -> None:
    from app import create_app

    if len(sys.argv) != 2:
        raise SystemExit("usage: export_openapi.py OUTPUT_PATH")
    output = (CALLER_DIRECTORY / sys.argv[1]).resolve()
    output.write_text(
        json.dumps(create_app().openapi(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
