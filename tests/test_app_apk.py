"""`/api/app-apk` 的归档名回归测试（2026-10-21）。

背景：APK 归档从 `dist/goshor.apk` 改名为 `dist/goshor-20261021.apk` 后，
接口仍写死旧名，手机端「下载安装包」入口变成 404。这里锁住「按实际产物
文件名下载」，同时保留对旧名的兼容。
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import main


def test_app_apk_serves_archived_filename(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    apk = dist / "goshor-20261021.apk"
    apk.write_bytes(b"fake-apk")
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)

    r = main.api_app_apk()

    assert Path(r.path) == apk
    assert r.filename == "goshor-20261021.apk"
    assert r.media_type == "application/vnd.android.package-archive"


def test_app_apk_serves_file_beside_exe_in_dist(tmp_path, monkeypatch):
    """本机开发时 exe 本身就在 dist/，APK 与 exe 同级。"""
    exe_dir = tmp_path / "dist"
    exe_dir.mkdir()
    apk = exe_dir / "goshor-20261021.apk"
    apk.write_bytes(b"fake-apk")
    monkeypatch.setattr(main, "BASE_DIR", exe_dir)

    r = main.api_app_apk()

    assert Path(r.path) == apk


def test_app_apk_prefers_newest_file(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    dist.mkdir()
    old = dist / "goshor.apk"
    new = dist / "goshor-20261021.apk"
    old.write_bytes(b"old")
    new.write_bytes(b"new")
    os.utime(old, (1_600_000_000, 1_600_000_000))
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)

    r = main.api_app_apk()

    assert Path(r.path) == new


def test_app_apk_404_when_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "BASE_DIR", tmp_path)

    with pytest.raises(HTTPException) as exc:
        main.api_app_apk()

    assert exc.value.status_code == 404
