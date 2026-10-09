"""手机端个人库（`users/data_<uid>.db`）首次并发初始化的回归测试。

背景（2026-10-09 定位）：
手机端首页首屏会并发打 `/api/stats` + `/api/study-plan` + `/api/paper-drafts`
（见 `static/m/m.js` 里那处 Promise.all），三个请求各开一条 SQLite 连接。
如果个人库是**新建**的（新账号 / 新设备第一次打开），多条连接会同时去创建
同一个库文件 —— 实测这会让其中一条连接在写建表语句时报
`attempt to write a readonly database`，前端表现为首页「加载失败」。

定位过程（可复现脚本口径）：
  - 6 线程并发对**空库**跑 `executescript(PERSONAL_SCHEMA)` → 挂 1~4 条；
  - 库**建好之后**（文件非空）6 线程并发跑同样语句 → 0 报错；
  - 切不切 WAL 与它无关（把 `_ensure_wal` 置空仍复现）。
即：不安全的是「并发首次创建同一个库文件」这一步本身。

修法见 `app/db.py` 的 `_personal_db_blank` / `_init_personal_db`：
首次建库整段串行，且必须在**开长期连接之前**完成（对着 0 字节文件开出来的
连接不能再写）。
"""
from __future__ import annotations

import inspect
import re
import threading
import traceback

from app import db

# 并发参数：每轮换一个 uid ⇒ 每轮都是一个全新的个人库文件
ROUNDS = 5
THREADS = 8


def test_schema_version_constant_matches_migrate():
    """SCHEMA_VERSION 必须等于 `_migrate()` 写入的最高版本号。

    `connect()` 用「`_meta.schema_version` 是否达到 SCHEMA_VERSION」判断
    个人库是否已初始化完成。常量一旦落后于迁移，已建好的库会被反复判成
    「需要初始化」，把并发竞态又请回来；常量超前则会让迁移被整体跳过。
    """
    src = inspect.getsource(db._migrate)
    versions = [int(m) for m in re.findall(r"schema_version','(\d+)'", src)]
    assert versions, "没在 _migrate() 里找到任何 schema_version 写入"
    assert db.SCHEMA_VERSION == max(versions), (
        f"db.SCHEMA_VERSION={db.SCHEMA_VERSION}，但 _migrate() 最高只写到 "
        f"{max(versions)}")


def test_personal_db_blank_detects_missing_and_empty(tmp_path):
    """`_personal_db_blank` 必须把「不存在」和「0 字节」都判为未初始化。"""
    path = tmp_path / "users" / "data_1.db"
    assert db._personal_db_blank(path) is True      # 文件还不存在
    path.parent.mkdir(parents=True)
    path.write_bytes(b"")
    assert db._personal_db_blank(path) is True      # 存在但 0 字节
    path.write_bytes(b"SQLite format 3\x00" + b"\x00" * 16)
    assert db._personal_db_blank(path) is False     # 已有内容


def test_concurrent_first_connect_does_not_hit_readonly(mobile_db):
    """并发首次 `connect()` 同一个新个人库：不得出现任何异常。

    这是本次修复的核心回归断言 —— 旧实现下每轮 8 线程里会挂 1~4 条
    `attempt to write a readonly database`。
    """
    errors: list[str] = []
    lock = threading.Lock()

    def worker(uid: int) -> None:
        # contextvars 不跨线程继承，必须在线程内设置身份，否则 connect()
        # 会走桌面单库分支、测不到手机多身份路径
        db.set_user(uid)
        try:
            conn = db.connect()
            try:
                conn.execute(
                    "INSERT OR REPLACE INTO answers(doc_id,selected,correct,ms,created_at)"
                    " VALUES(1,'A',1,120,1.0)")
                conn.commit()
            finally:
                conn.close()
        except Exception:                          # noqa: BLE001
            with lock:
                errors.append(f"[uid={uid}]\n{traceback.format_exc()}")

    for r in range(ROUNDS):
        uid = 900 + r
        threads = [threading.Thread(target=worker, args=(uid,)) for _ in range(THREADS)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

    assert not errors, "并发首次建个人库出现异常：\n" + "\n".join(errors[:3])


def test_connect_retries_when_connection_not_writable(mobile_db, monkeypatch):
    """可写探测失败时必须**换一条新连接重试**，而不是把不可用连接交给调用方。

    这条是确定性用例（不依赖时序）：直接让第一次探测返回 False，模拟首次建库
    竞态下拿到的只读连接，断言 connect() 会重试到成功、且返回的连接真能写。
    """
    calls = {"n": 0}
    real = db._personal_writable

    def flaky(conn):
        calls["n"] += 1
        if calls["n"] == 1:
            return False                           # 第一次：假装拿到只读连接
        return real(conn)

    monkeypatch.setattr(db, "_personal_writable", flaky)
    db.set_user(1)
    conn = db.connect()
    try:
        assert calls["n"] >= 2, "没有触发重试"
        conn.execute(
            "INSERT OR REPLACE INTO answers(doc_id,selected,correct,ms,created_at)"
            " VALUES(1,'A',1,120,1.0)")
        conn.commit()
        row = conn.execute("SELECT correct FROM answers WHERE doc_id=1").fetchone()
        assert row is not None and int(row["correct"]) == 1
    finally:
        conn.close()


def test_personal_db_reaches_latest_schema_version(mobile_db):
    """首次 connect() 后个人库必须建齐表且版本到达 SCHEMA_VERSION。"""
    db.set_user(1)
    conn = db.connect()
    try:
        row = conn.execute(
            "SELECT value FROM _meta WHERE key='schema_version'").fetchone()
        assert row is not None, "个人库没有写入 schema_version"
        assert int(row["value"]) == db.SCHEMA_VERSION
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        for table in ("answers", "mastery", "study_plan", "paper_drafts",
                      "doc_notes", "interview_logs", "shizheng_seen"):
            assert table in names, f"个人库缺表：{table}"
    finally:
        conn.close()


def test_connect_migrates_outdated_personal_db(mobile_db):
    """版本落后的个人库仍必须被迁移（初始化判定不能变成「一次性的进程缓存」）。

    手机端备份还原会替换 users/ 下的库文件；若判定写成进程内布尔缓存，
    还原出来的旧库会跳过迁移、缺列缺表。
    """
    db.set_user(7)
    conn = db.connect()
    conn.execute("INSERT OR REPLACE INTO _meta(key,value) VALUES('schema_version','3')")
    conn.execute("DROP TABLE IF EXISTS doc_notes")   # v12 才加的表
    conn.commit()
    conn.close()

    conn = db.connect()                              # 应触发迁移补齐
    try:
        row = conn.execute(
            "SELECT value FROM _meta WHERE key='schema_version'").fetchone()
        assert int(row["value"]) == db.SCHEMA_VERSION
        names = {r["name"] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "doc_notes" in names, "落后版本的个人库没有被迁移"
    finally:
        conn.close()
