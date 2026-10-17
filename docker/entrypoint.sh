#!/usr/bin/env bash
# With DATABASE_URL set (compose, Cloud Run, Neon) this is a plain `exec uvicorn`.
# Without it, run Postgres 16 + pgvector inside the container, restore the newest snapshot from the
# Worker's R2 bucket, and keep snapshotting it (docker/backup.py). Made for Cloudflare Containers,
# whose disk is wiped on every host restart.
set -euo pipefail
if [ -z "${DATABASE_URL:-}" ]; then
  PGDATA=/var/lib/postgresql/data
  PGBIN=/usr/lib/postgresql/16/bin
  BOOTLOG=/tmp/boot.log; : > $BOOTLOG
  # Cloudflare exposes no container stdout: a failed boot ships its log to R2 as boot.log (read it with backup.py GET).
  trap 'rc=$?; if [ $rc -ne 0 ]; then cat "$PGDATA/postgresql.log" >> $BOOTLOG 2>/dev/null; python3 docker/backup.py put boot.log < $BOOTLOG || true; fi' EXIT
  exec 2>>$BOOTLOG
  set -x
  export DATABASE_URL="postgresql://assistant@127.0.0.1:5432/assistant"   # loopback only, trust auth: nothing else can reach it
  mkdir -p "$PGDATA" && chown postgres "$PGDATA"
  fresh=0
  if [ ! -s "$PGDATA/PG_VERSION" ]; then
    fresh=1
    su postgres -c "$PGBIN/initdb -D $PGDATA --auth=trust -U postgres" >/dev/null
    # mmap: Firecracker VMs may have no usable /dev/shm for POSIX shared memory
    printf "listen_addresses='127.0.0.1'\nshared_buffers=32MB\nmax_connections=30\ndynamic_shared_memory_type=mmap\n" >> "$PGDATA/postgresql.conf"
  fi
  su postgres -c "$PGBIN/pg_ctl -D $PGDATA -w -l $PGDATA/postgresql.log start" >/dev/null
  if [ "$fresh" = 1 ]; then
    su postgres -c "psql -q -c \"CREATE ROLE assistant LOGIN SUPERUSER\" -c \"CREATE DATABASE assistant OWNER assistant\""
    python3 docker/backup.py restore
  fi
  python3 docker/backup.py loop &
  set +x
  trap - EXIT
fi
exec "$@"
