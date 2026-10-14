#!/usr/bin/env bash
set -euo pipefail

# Resolve resources from the project root even when launched elsewhere.
PROJECT_DIR="$(CDPATH='' cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd -- "$PROJECT_DIR"

# LAN only: this bridge exposes local operations; do not publish it online.
export PYTHONDONTWRITEBYTECODE=1
exec uv run --no-sync uvicorn h3_backend.api:app --host 0.0.0.0 --port 8888 --timeout-graceful-shutdown 5
