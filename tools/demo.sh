#!/usr/bin/env bash
# Start the whole system with one command: the server, then the camera worker.
#
#   tools/demo.sh SOURCE ZONES [extra worker options]
#
#   tools/demo.sh my_road.mp4 zones.json                 a video played like a camera
#   tools/demo.sh 0 zones.json --show                    the first webcam, with a preview
#   tools/demo.sh rtsp://192.168.1.20/stream zones.json  a network camera
#
# The grace period is 20 seconds so a demo does not take two minutes; pass
# --grace N after the zones file to change it. Stop everything with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")/.."

if [ $# -lt 2 ]; then
  sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'
  exit 1
fi
SOURCE=$1
ZONES=$2
shift 2

if [ ! -f "$ZONES" ]; then
  echo "Zones file not found: $ZONES"
  echo "Draw one first:  uv run python tools/draw_zone.py VIDEO --out zones.json"
  exit 1
fi
if [ ! -f dashboard/dist/index.html ]; then
  echo "The dashboard has not been built yet. Run these once:"
  echo "  npm --prefix dashboard install"
  echo "  npm --prefix dashboard run build"
  exit 1
fi
if [ ! -d models/yolo11n_openvino_model ]; then
  echo "Preparing the fast model (first run only)..."
  uv run python tools/export_openvino.py models/yolo11n.pt
fi

PORT=${API_PORT:-8000}
uv run uvicorn api.main:app --host 127.0.0.1 --port "$PORT" --log-level warning &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT

for _ in $(seq 1 40); do
  if curl -fs "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then break; fi
  if ! kill -0 $SERVER 2>/dev/null; then echo "The server failed to start."; exit 1; fi
  sleep 0.5
done

if [ -z "$(uv run python tools/create_officer.py --list)" ]; then
  echo
  echo "No dashboard login exists yet. Create one in another terminal:"
  echo "  uv run python tools/create_officer.py --name \"Your Name\" --username yourname"
fi
echo
echo "Dashboard:  http://127.0.0.1:$PORT"
echo "Stop with Ctrl+C."
echo

uv run python -m worker.run_live "$SOURCE" --zones "$ZONES" --grace 20 \
  --api "http://127.0.0.1:$PORT" --camera "Demo camera" "$@"
