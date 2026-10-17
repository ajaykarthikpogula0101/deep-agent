#!/usr/bin/env bash
# With DATABASE_URL set (compose, Cloud Run, Neon) this is a plain `exec uvicorn`.
# Without it, run Postgres 16 + pgvector inside the container, restore the newest snapshot from the
# Worker's R2 bucket, and keep snapshotting it (docker/backup.py). Made for Cloudflare Containers,
# whose disk is wiped on every host restart.
set -euo pipefail
if [ -n "${DATABASE_URL:-}" ]; then
  exec "$@"
fi
PGDATA=/var/lib/postgresql/data
PGBIN=/usr/lib/postgresql/16/bin
BOOTLOG=/tmp/boot.log; : > $BOOTLOG
# Cloudflare exposes no container stdout: a failed boot ships its log to R2 as boot.log (read it with backup.py GET).
trap 'rc=$?; if [ $rc -ne 0 ]; then cat "$PGDATA/postgresql.log" >> $BOOTLOG 2>/dev/null; python3 docker/backup.py put boot.log < $BOOTLOG || true; fi' EXIT
exec 2>>$BOOTLOG
set -x
export DATABASE_URL="postgresql://assistant@127.0.0.1:5432/assistant"   # loopback only, trust auth: nothing else can reach it
mkdir -p "$PGDATA" && chown postgres "$PGDATA"
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  su postgres -c "$PGBIN/initdb -D $PGDATA --auth=trust -U postgres" >/dev/null
  # Keep sockets with PGDATA: Cloudflare's ephemeral /run has no postgresql directory.
  printf "listen_addresses='127.0.0.1'\nunix_socket_directories='$PGDATA'\nshared_buffers=32MB\nmax_connections=30\n" >> "$PGDATA/postgresql.conf"
fi
su postgres -c "$PGBIN/pg_ctl -D $PGDATA -w -l $PGDATA/postgresql.log start" >/dev/null
# The marker exists only after a restore completed. A container restart on the same disk after a failed or
# partial restore must retry from a clean database, or the app starts empty and the loop overwrites the snapshot.
if [ ! -e "$PGDATA/.restored" ]; then
  su postgres -c "psql -h 127.0.0.1 -U postgres -d postgres -q -c 'DROP DATABASE IF EXISTS assistant' -c 'DROP ROLE IF EXISTS assistant' -c 'CREATE ROLE assistant LOGIN SUPERUSER' -c 'CREATE DATABASE assistant OWNER assistant'"
  python3 docker/backup.py restore
  touch "$PGDATA/.restored"
fi
(while :; do python3 docker/backup.py loop || true; sleep 5; done) &
set +x
trap - EXIT
# Stay PID 1 so a stop (deploy, host drain) can take one last snapshot after the app has exited.
"$@" &
APP=$!
trap 'kill -TERM $APP 2>/dev/null; wait $APP; python3 docker/backup.py once; exit 0' TERM INT
wait $APP
