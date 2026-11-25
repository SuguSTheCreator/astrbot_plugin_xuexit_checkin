#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
echo "============================================"
echo "  Xuexit Login Helper"
echo "  Ctrl+C to stop the tunnel."
echo "============================================"
if command -v python3 >/dev/null 2>&1; then PY=python3; else PY=python; fi
exec "$PY" login_proxy.py --config helper.json
