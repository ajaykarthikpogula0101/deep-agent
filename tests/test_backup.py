"""Database backups (app/backup.py), the backup health check, and the launcher starting the Docker database
(app/launch.py). Fake commands only: nothing runs docker or pg_dump."""
import os
import subprocess
import time
from datetime import datetime, timezone
from types import SimpleNamespace

from app import backup, health
from app.config import settings


class FakeRun:
    """subprocess.run stand-in: `docker inspect` says running, pg_dump writes `payload` to stdout."""

    def __init__(self, running=True, payload=b"PGDMP" + b"x" * 4000, rc=0, err=b""):
        self.running, self.payload, self.rc, self.err, self.calls = running, payload, rc, err, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="true\n" if self.running else "false\n")
        if "stdout" in kw and hasattr(kw["stdout"], "write"):
            kw["stdout"].write(self.payload)
        return SimpleNamespace(returncode=self.rc, stderr=self.err)


def _setup(monkeypatch, tmp_path, keep=3):
    monkeypatch.setattr(settings, "backup_dir", str(tmp_path))
    monkeypatch.setattr(settings, "backup_keep", keep)
    monkeypatch.setattr(settings, "backup_docker_container", "deependhq-assistant-db-1")
    monkeypatch.setattr(settings, "database_url", "postgresql://assistant:assistant@127.0.0.1:5432/assistant")
    monkeypatch.setattr(backup.shutil, "which", lambda name: f"/usr/bin/{name}")


def test_backup_uses_docker_exec_and_keeps_the_newest(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, keep=3)
    run = FakeRun()
    for i in range(5):
        r = backup.take(run=run, now=datetime(2026, 10, 20 + i, 22, 20, tzinfo=timezone.utc))
        assert r["ok"] and r["bytes"] > 1024
    assert run.calls[1] == ["docker", "exec", "deependhq-assistant-db-1", "pg_dump", "-U", "assistant", "-d", "assistant", "-Fc"]
    names = [p.name for p in backup.backups()]
    assert len(names) == 3 and names[0] > names[1] > names[2]                      # newest first, oldest two pruned
    assert not list(tmp_path.glob("*.part"))


def test_failed_or_tiny_dump_leaves_no_file(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    r = backup.take(run=FakeRun(rc=1, err=b"pg_dump: error: connection refused"))
    assert not r["ok"] and "connection refused" in r["error"] and not list(tmp_path.iterdir())
    r = backup.take(run=FakeRun(payload=b""))
    assert not r["ok"] and "only 0 bytes" in r["error"] and not list(tmp_path.iterdir())


def test_without_docker_falls_back_to_pg_dump_or_says_why(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    assert backup.dump_command(FakeRun(running=False)) == ["pg_dump", "-Fc", "-d", settings.database_url]
    monkeypatch.setattr(backup.shutil, "which", lambda name: None)
    r = backup.take(run=FakeRun(running=False))
    assert not r["ok"] and "no way to back up" in r["error"]


def test_backup_health_check(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "backup_enabled", True)
    monkeypatch.setattr(settings, "llm_api_key", "k")
    monkeypatch.setattr(settings, "llm_base_url", "")
    get = lambda url, headers=None, timeout=None: SimpleNamespace(status_code=200, json=lambda: {})
    count = lambda sql, params: 0 if "count" in sql else 1
    assert health.run_checks(get=get, count=count)["checks"]["backup"]["level"] == "warn"      # none yet
    backup.take(run=FakeRun())
    fresh = health.run_checks(get=get, count=count)["checks"]["backup"]
    assert fresh["level"] == "ok" and str(tmp_path) in fresh["detail"]
    old = time.time() - 40 * 3600
    for p in backup.backups():
        os.utime(p, (old, old))
    assert health.run_checks(get=get, count=count)["checks"]["backup"]["level"] == "fail"       # nightly job broken


def test_restore_pipes_the_file_into_pg_restore(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    f = tmp_path / "deependhq-x.dump"
    f.write_bytes(b"PGDMP-data")
    seen = {}

    def run(cmd, **kw):
        if cmd[:2] == ["docker", "inspect"]:
            return SimpleNamespace(returncode=0, stdout="true\n")
        seen["cmd"], seen["stdin"] = cmd, kw["stdin"].read()
        return SimpleNamespace(returncode=0, stderr=b"")

    assert backup.restore(str(f), run=run) == 0
    assert seen["cmd"][:4] == ["docker", "exec", "-i", "deependhq-assistant-db-1"] and "--clean" in seen["cmd"]
    assert seen["stdin"] == b"PGDMP-data"
    assert backup.restore(str(tmp_path / "missing.dump"), run=run) == 2


# ---------------------------------------------------------------- launcher starts the Docker database
def test_launcher_starts_the_compose_db_instead_of_an_empty_embedded_one(monkeypatch):
    from app import launch

    calls, up = [], {"n": 0}

    def run(cmd, **kw):
        calls.append(cmd)
        return SimpleNamespace(returncode=0)

    def reachable(url, timeout=3.0):
        up["n"] += 1
        return up["n"] > 2          # unreachable at first, up once compose has started it

    monkeypatch.setattr(launch.shutil, "which", lambda name: "/usr/bin/docker")
    monkeypatch.setattr(launch, "reachable", reachable)
    monkeypatch.setattr(launch.time, "sleep", lambda s: None)
    url = "postgresql://assistant:assistant@127.0.0.1:5432/assistant"
    assert launch.start_compose_db(url, run=run) is True
    assert ["docker", "compose", "up", "-d", "db"] in calls
    assert launch.start_compose_db("postgresql://u:p@prod.internal:5432/x", run=run) is False      # never for other hosts
    monkeypatch.setattr(launch.shutil, "which", lambda name: None)
    assert launch.start_compose_db(url, run=run) is False                                          # no Docker installed


def test_launcher_uses_the_docker_db_when_it_comes_up(monkeypatch):
    from app import launch

    monkeypatch.setenv("DATABASE_URL", "postgresql://assistant:assistant@127.0.0.1:5432/assistant")
    monkeypatch.setattr(launch, "reachable", lambda url, timeout=3.0: False)
    monkeypatch.setattr(launch, "start_compose_db", lambda url: True)
    url, server = launch.pick_database()
    assert url.endswith("127.0.0.1:5432/assistant") and server is None
