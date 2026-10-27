"""备份包清单与校验（P1 数据可靠性）。

锁住三件事：
1. 导出包含 manifest.json，db_sha256 与实际 goshor.db 一致；
2. 导入校验清单，损坏包拒绝覆盖；
3. 旧版无清单 zip 仍兼容（verified=false）。
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, main


@pytest.fixture()
def client(temp_db, tmp_path, monkeypatch):
    monkeypatch.setattr(main, "DATA_DIR", tmp_path)
    monkeypatch.setattr(main, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(config, "SETTINGS_PATH", tmp_path / "settings.json")
    with TestClient(main.app) as c:
        yield c


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_export_contains_manifest_and_hash(client):
    r = client.get("/api/backup/export")
    assert r.status_code == 200
    z = zipfile.ZipFile(io.BytesIO(r.content))
    assert "manifest.json" in z.namelist()
    m = json.loads(z.read("manifest.json"))
    db = z.read("goshor.db")
    assert m["format"] == 1
    assert m["db_bytes"] == len(db)
    assert m["db_sha256"] == _sha(db)


def test_import_verifies_manifest(client):
    r = client.get("/api/backup/export")
    r2 = client.post("/api/backup/import",
                     files={"file": ("backup.zip", r.content, "application/zip")})
    j = r2.json()
    assert j["ok"] is True
    assert j["verified"] is True


def test_import_rejects_tampered_db(client):
    r = client.get("/api/backup/export")
    src = zipfile.ZipFile(io.BytesIO(r.content))
    db = src.read("goshor.db")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("goshor.db", db)
        z.writestr("manifest.json", json.dumps({
            "format": 1, "db_bytes": len(db), "db_sha256": "0" * 64,
        }))
    bad = client.post("/api/backup/import",
                      files={"file": ("bad.zip", buf.getvalue(), "application/zip")})
    j = bad.json()
    assert j["ok"] is False
    assert "校验失败" in j["error"]


def test_status_reports_empty_new_user(client):
    j = client.get("/api/backup/status").json()
    assert j["ok"] is True
    assert j["integrity"] == "ok"
    assert j["answers"] == 0
    assert j["user_bytes"] > 0
    assert j["last_backup_at"] == ""


def test_export_records_last_backup_time(client):
    client.get("/api/backup/export")
    j = client.get("/api/backup/status").json()
    assert j["last_backup_at"]


def test_mobile_backup_status_is_wired():
    src = (Path(__file__).resolve().parents[1] / "static" / "m" / "m.js").read_text(encoding="utf-8")
    assert 'id="bkDiag"' in src
    assert 'api("/api/backup/status")' in src
    assert "上次导出" in src


def test_import_accepts_legacy_zip_without_manifest(client):
    r = client.get("/api/backup/export")
    src = zipfile.ZipFile(io.BytesIO(r.content))
    db = src.read("goshor.db")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("goshor.db", db)
    old = client.post("/api/backup/import",
                      files={"file": ("old.zip", buf.getvalue(), "application/zip")})
    j = old.json()
    assert j["ok"] is True
    assert j["verified"] is False
