"""一键拉起模拟器 APP（演示页「安装并打开安卓 APP」按钮的后端）。

验收：
  1. `/api/open_app` 立即返回，长耗时的开机/安装流程在后台线程里跑；
  2. `/api/open_app/status` 能报出 booting / launching / done / error 四态；
  3. 没有模拟器时给出**可执行**的错误原因，而不是静默失败；
  4. 已有任务在跑时，重复点击复用同一任务，不会并发开两个模拟器。

运行：python -m pytest tests/test_open_app.py -q
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import main as app_main

CLIENT = TestClient(app_main.app)


def _reset():
    with app_main._OPEN_APP_LOCK:
        app_main._OPEN_APP.update({"state": "idle", "msg": "", "started": 0.0})


@pytest.fixture(autouse=True)
def _clean_state():
    _reset()
    yield
    _reset()


def _wait_state(expected: str, timeout: float = 8.0) -> str:
    end = time.time() + timeout
    state = "?"
    while time.time() < end:
        state = CLIENT.get("/api/open_app/status").json()["state"]
        if state == expected:
            return state
        time.sleep(0.05)
    return state


def _stub(monkeypatch, *, devices, emulator=None, launch=None, mumu=None):
    """把外部依赖（进程、adb、模拟器）换成桩，只验证状态机。"""
    monkeypatch.setattr(app_main, "_adb_path", lambda: Path("adb.exe"))
    monkeypatch.setattr(app_main, "_run", lambda *a, **k: None)
    monkeypatch.setattr(app_main, "_devices", lambda adb: devices)
    monkeypatch.setattr(app_main, "_emulator_path", lambda: emulator)
    monkeypatch.setattr(app_main, "_mumu_cli", lambda: mumu)
    monkeypatch.setattr(app_main, "_boot_completed", lambda adb, serial: True)
    monkeypatch.setattr(app_main, "_list_avds", lambda emu: ["goshor34"])
    if launch is not None:
        monkeypatch.setattr(app_main, "_launch_apk", launch)


def test_health_endpoint():
    r = CLIENT.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "app": "goshore"}


def test_status_starts_idle():
    d = CLIENT.get("/api/open_app/status").json()
    assert d["state"] == "idle"
    assert d["ok"] is True
    assert d["elapsed"] == 0


def test_connected_device_installs_and_launches(monkeypatch):
    _stub(monkeypatch, devices=["emulator-5554"],
          launch=lambda adb, serial: (True, "APP 已在模拟器中启动"))
    body = CLIENT.post("/api/open_app").json()
    assert body["ok"] is True
    assert body["reused"] is False
    assert _wait_state("done") == "done"
    assert "已在模拟器中启动" in CLIENT.get("/api/open_app/status").json()["msg"]


def test_missing_emulator_gives_actionable_error(monkeypatch):
    _stub(monkeypatch, devices=[], emulator=None)
    CLIENT.post("/api/open_app")
    assert _wait_state("error") == "error"
    msg = CLIENT.get("/api/open_app/status").json()["msg"]
    assert "emulator.exe" in msg or "模拟器" in msg


def test_no_avd_gives_actionable_error(monkeypatch):
    _stub(monkeypatch, devices=[], emulator=Path("emulator.exe"))
    monkeypatch.setattr(app_main, "_list_avds", lambda emu: [])
    CLIENT.post("/api/open_app")
    assert _wait_state("error") == "error"
    assert "AVD" in CLIENT.get("/api/open_app/status").json()["msg"]


def test_launch_failure_surfaces_reason(monkeypatch):
    _stub(monkeypatch, devices=["emulator-5554"],
          launch=lambda adb, serial: (False, "APK 安装或启动失败"))
    CLIENT.post("/api/open_app")
    assert _wait_state("error") == "error"
    assert "失败" in CLIENT.get("/api/open_app/status").json()["msg"]


def test_second_click_while_busy_reuses_task(monkeypatch):
    _stub(monkeypatch, devices=["emulator-5554"],
          launch=lambda adb, serial: (True, "ok"))
    first = CLIENT.post("/api/open_app").json()
    assert first["reused"] is False
    with app_main._OPEN_APP_LOCK:            # 模拟仍在开机中
        app_main._OPEN_APP["state"] = "booting"
    second = CLIENT.post("/api/open_app").json()
    assert second["reused"] is True
    assert second["state"] == "booting"


def test_worker_exception_lands_in_error(monkeypatch):
    _stub(monkeypatch, devices=["emulator-5554"])

    def boom():
        raise RuntimeError("boom")

    monkeypatch.setattr(app_main, "_open_app_pipeline", boom)
    app_main._open_app_worker()
    assert CLIENT.get("/api/open_app/status").json()["state"] == "error"
    assert "boom" in CLIENT.get("/api/open_app/status").json()["msg"]


# ---------------- MuMu 模拟器分支 ----------------

def test_mumu_cli_honours_home_env(monkeypatch, tmp_path):
    """MUMU_HOME 指向的安装目录必须被认出来（盘符拼接曾写成"D:"相对路径）。"""
    cli = tmp_path / "nx_main" / "mumu-cli.exe"
    cli.parent.mkdir(parents=True)
    cli.write_bytes(b"MZ")
    monkeypatch.setenv("MUMU_HOME", str(tmp_path))
    assert app_main._mumu_cli() == cli


def test_mumu_path_boots_and_launches(monkeypatch):
    """没有现成设备时，先拉 MuMu，连上后安装并打开 APP。"""
    booted = {"n": 0}
    seen = {}

    def devices(adb):
        booted["n"] += 1
        return ["127.0.0.1:16384"] if booted["n"] > 1 else []

    def launch(adb, serial):
        seen["serial"] = serial
        return True, "APP 已启动"

    _stub(monkeypatch, devices=[], mumu=Path("mumu-cli.exe"), launch=launch)
    monkeypatch.setattr(app_main, "_devices", devices)
    monkeypatch.setattr(app_main, "_mumu_launch", lambda cli: True)

    CLIENT.post("/api/open_app")
    assert _wait_state("done") == "done"
    assert seen["serial"] == "127.0.0.1:16384"


def test_mumu_failure_falls_back_to_avd(monkeypatch):
    """MuMu 起不来时不能直接判死，要继续尝试 AVD。"""
    _stub(monkeypatch, devices=[], emulator=Path("emulator.exe"),
          mumu=Path("mumu-cli.exe"), launch=lambda adb, serial: (True, "APP 已启动"))
    monkeypatch.setattr(app_main, "_mumu_launch", lambda cli: False)
    monkeypatch.setattr(app_main, "_list_avds", lambda emu: [])   # AVD 也没有

    CLIENT.post("/api/open_app")
    assert _wait_state("error") == "error"
    assert "AVD" in CLIENT.get("/api/open_app/status").json()["msg"]
