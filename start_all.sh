#!/usr/bin/env bash
cd "$(dirname "$0")" || exit 1

PY="$PWD/.venv/bin/uvicorn"
ROOT="$PWD"
mkdir -p logs

for port in 8000 8001 8002 8003; do
  if lsof -iTCP:"$port" -sTCP:LISTEN -P -n >/dev/null 2>&1; then
    echo "Portas $port jau uzimtas:"
    lsof -iTCP:"$port" -sTCP:LISTEN -P -n | tail -n +2 | sed 's/^/  /'
    exit 1
  fi
done

start() {
  local name="$1" port="$2"; shift 2
  (
    cd "$ROOT/$name" || exit 1
    env "$@" nohup "$PY" main:app --port "$port" >"$ROOT/logs/$name.log" 2>&1 &
    echo $! >"$ROOT/logs/$name.pid"
  )
  printf "  %-10s :%s\n" "$name" "$port"
}

echo "Paleidziami servisai:"
start auth 8001
start catalog 8002
start order 8003 CATALOG_URL="http://127.0.0.1:8002"
start gateway 8000 AUTH_URL="http://127.0.0.1:8001" \
      CATALOG_URL="http://127.0.0.1:8002" ORDER_URL="http://127.0.0.1:8003"

sleep 4
echo
echo "Busena:"
curl -s http://127.0.0.1:8000/health | python3 -m json.tool 2>/dev/null | sed 's/^/  /'
echo
echo "  Gateway:  http://127.0.0.1:8000/docs"
echo "  Stabdyti: ./stop_all.sh"
