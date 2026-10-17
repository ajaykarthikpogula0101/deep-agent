"""Embedded database snapshot transport must work through Cloudflare's edge."""
import gzip
import importlib.util
from pathlib import Path
import urllib.error
from unittest.mock import Mock

import pytest


@pytest.fixture
def backup(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://test@localhost/test")
    monkeypatch.setenv("BACKUP_URL", "https://assistant.example/__backup")
    monkeypatch.setenv("ADMIN_TOKEN", "test-only-token")
    spec = importlib.util.spec_from_file_location("container_backup", Path(__file__).parents[1] / "docker/backup.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_snapshot_requests_use_named_user_agent(backup, monkeypatch):
    send = Mock()
    monkeypatch.setattr(backup.urllib.request, "urlopen", send)
    for method, data in [("GET", None), ("PUT", b"snapshot")]:
        backup._req(method, "latest.sql.gz", data)
        request = send.call_args.args[0]
        assert request.get_header("User-agent") == "deependhq-assistant/0.1"
        assert request.get_header("X-admin-token") == "test-only-token"
        assert request.method == method
        assert request.data == data


def test_restore_never_treats_forbidden_as_empty(backup, monkeypatch):
    def forbidden(*args):
        raise urllib.error.HTTPError("https://assistant.example", 403, "forbidden", {}, None)
    monkeypatch.setattr(backup, "_req", forbidden)
    run = Mock()
    monkeypatch.setattr(backup.subprocess, "run", run)
    with pytest.raises(urllib.error.HTTPError):
        backup.restore()
    run.assert_not_called()


def test_restore_applies_snapshot_with_sql_errors_fatal(backup, monkeypatch):
    response = Mock()
    response.read.return_value = gzip.compress(b"SELECT 1;")
    monkeypatch.setattr(backup, "_req", Mock(return_value=response))
    run = Mock()
    monkeypatch.setattr(backup.subprocess, "run", run)
    backup.restore()
    assert run.call_args.kwargs == {"input": b"SELECT 1;", "check": True}
    assert "ON_ERROR_STOP=1" in run.call_args.args[0]
