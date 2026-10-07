#!/usr/bin/env bash
# Local full-stack dev launcher: vite dev server + Django runserver.
#
#   ./dev.sh                  # vite :5274, Django :8274
#   DJANGO_PORT=8001 ./dev.sh
#   VITE_PORT=5275 ./dev.sh   # must match DJANGO_VITE dev_server_port
#                             # (both read VITE_PORT, so this is fine)
#
# Vite serves the React entries straight from frontend/src, so the
# browser always runs the latest frontend code — no `npm run build`
# or collectstatic needed in this mode. Ctrl-C stops both servers.
set -euo pipefail
cd "$(dirname "$0")"

# Non-default ports on both sides — :5173/:8000 are the most common
# dev ports, so other projects' servers can shadow them.
VITE_PORT="${VITE_PORT:-5274}"
DJANGO_PORT="${DJANGO_PORT:-8274}"
PY=venv/bin/python
# This is the URL django-vite emits for the dashboard entry in dev
# mode (STATIC_URL + entry path). Only THIS project's vite answers
# 200 to it, so the probe doubles as a foreign-server detector —
# another project's vite on the same port used to shadow the asset
# URLs and the page sat on "Loading React app…".
VITE_PROBE="http://localhost:${VITE_PORT}/static/src/dashboard/main.tsx"

vite_up() { curl -sf --max-time 2 -o /dev/null "$VITE_PROBE"; }

port_taken() {
    lsof -nP -iTCP:"$VITE_PORT" -sTCP:LISTEN >/dev/null 2>&1
}

vite_pid=""
cleanup() {
    if [ -n "$vite_pid" ]; then
        kill "$vite_pid" 2>/dev/null || true
    fi
}
trap cleanup EXIT

if [ ! -x "$PY" ]; then
    echo "[dev] $PY missing — create the venv first" >&2
    exit 1
fi

# Non-interactive shells don't inherit the interactive nvm PATH —
# source nvm, else prepend the newest installed node bin dir.
if ! command -v npm >/dev/null 2>&1; then
    if [ -s "$HOME/.nvm/nvm.sh" ]; then
        # shellcheck disable=SC1091
        . "$HOME/.nvm/nvm.sh" >/dev/null 2>&1 || true
        nvm use --silent default >/dev/null 2>&1 || true
    fi
    if ! command -v npm >/dev/null 2>&1; then
        node_bin="$(ls -d "$HOME"/.nvm/versions/node/*/bin \
            2>/dev/null | sort -V | tail -1)"
        [ -n "$node_bin" ] && PATH="$node_bin:$PATH"
    fi
fi
if ! command -v npm >/dev/null 2>&1; then
    echo "[dev] npm not found — install node via nvm first" >&2
    exit 1
fi

if vite_up; then
    echo "[dev] vite already serving this project on :$VITE_PORT" \
        "— reusing it"
elif port_taken; then
    cat >&2 <<EOF
[dev] ERROR: :$VITE_PORT is listening but is NOT this project's
      vite dev server (probe $VITE_PROBE failed). A foreign vite
      used to shadow the asset URLs and the page sat on
      "Loading React app…". Free the port or run with
      VITE_PORT=<free-port>.
EOF
    exit 1
else
    echo "[dev] starting vite dev server on :$VITE_PORT"
    # DJANGO_PORT keeps vite's proxy target pointed at this Django.
    (cd frontend && VITE_PORT="$VITE_PORT" DJANGO_PORT="$DJANGO_PORT" \
        npm run dev) &
    vite_pid=$!
fi

echo "[dev] waiting for vite to serve src/dashboard/main.tsx …"
for _ in $(seq 1 60); do
    if vite_up; then
        break
    fi
    if [ -n "$vite_pid" ] && ! kill -0 "$vite_pid" 2>/dev/null; then
        echo "[dev] ERROR: vite exited early — see output above" >&2
        exit 1
    fi
    sleep 0.5
done
if ! vite_up; then
    echo "[dev] ERROR: vite did not come up on :$VITE_PORT" \
        "within 30s" >&2
    exit 1
fi

cat <<EOF

  ──────────────────────────────────────────────
   App (open this):  http://localhost:${DJANGO_PORT}/
   vite dev server:  http://localhost:${VITE_PORT}/
  ──────────────────────────────────────────────

EOF

# DEBUG=true is exported because DJANGO_VITE.dev_mode is
# `DEBUG and VITE_DEV=1` — with DEBUG=False (as in this checkout's
# .env) VITE_DEV alone silently falls back to manifest mode.
# PYTHONUNBUFFERED: runserver's "Starting development server at
# http://…" banner is stdout print() — block-buffered when output is
# piped/redirected, so it can stay invisible for minutes otherwise.
DEBUG=true VITE_DEV=1 VITE_PORT="$VITE_PORT" PYTHONUNBUFFERED=1 \
    "$PY" manage.py runserver "$DJANGO_PORT"
