"""pytest 公共夹具。

所有测试都跑在临时数据库上，**不会触碰 data/goshor.db**。
运行：python -m pytest tests -q
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

# Windows + Python 3.13.9：os.mkdir(mode=0o700) 会落一条只允许当前用户的 DACL，
# DSH 沙箱的受限令牌随后连目录列表都拿不到 —— pytest 的 tmp_path 全程用 0o700，
# 于是所有用临时目录的用例都在 setup 阶段 PermissionError。
# Windows 上 mode 本应被忽略（见 os.mkdir 文档），这里恢复该语义；只影响测试进程。
if os.name == "nt":
    _os_mkdir = os.mkdir

    def _mkdir_ignore_mode(path, mode=0o777, *, dir_fd=None):
        return _os_mkdir(path, 0o777) if dir_fd is None else _os_mkdir(path, 0o777, dir_fd=dir_fd)

    os.mkdir = _mkdir_ignore_mode

# 让 tests/ 能 import app 包（仓库根目录入 sys.path）
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def find_node() -> str | None:
    """优先用 PATH 里的 node，其次用 WorkBuddy 托管运行时。找不到返回 None。"""
    exe = shutil.which("node")
    if exe:
        return exe
    for pat in (
        os.path.expanduser("~/.workbuddy-ai/binaries/node/versions/*/node.exe"),
        os.path.expanduser("~/.workbuddy-ai/binaries/node/versions/*/bin/node"),
    ):
        hits = sorted(glob.glob(pat))
        if hits:
            return hits[-1]
    return None


@pytest.fixture()
def node_exe() -> str:
    """本机 node 可执行文件；没有就跳过（前端静态校验类用例共用）。"""
    exe = find_node()
    if not exe:
        pytest.skip("本机没有 node，跳过前端静态校验")
    return exe


# 仓库里的真实库；测试绝不允许碰它
REAL_DB = ROOT / "data" / "goshor.db"


def _db_signature() -> list[tuple]:
    """真实库（含 -wal/-shm）的存在性/大小/mtime 指纹。"""
    out = []
    for p in (REAL_DB, Path(str(REAL_DB) + "-wal"), Path(str(REAL_DB) + "-shm")):
        if p.exists():
            st = p.stat()
            out.append((p.name, st.st_size, st.st_mtime_ns))
        else:
            out.append((p.name, None, None))
    return out


@pytest.fixture(scope="session", autouse=True)
def _guard_real_db():
    """守卫：整套测试跑完后，真实库 `data/goshor.db` 必须一字未动。

    有任何用例绕过临时库直接打到真实库，都会在这里被抓出来（这正是建议6 里
    「确认没有用例读写真实库」那条验收）。注意快照在收集之后才取，因此模块
    导入阶段的影响不在覆盖范围内。
    """
    before = _db_signature()
    yield
    after = _db_signature()
    assert before == after, (
        "有测试改动了真实库 data/goshor.db！所有用例都必须只跑在临时库上。\n"
        f"  之前: {before}\n  之后: {after}")


@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """把 db.DB_PATH 指向临时库，初始化 schema 后交给用例使用。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    # 拆分模式的两个路径也要指到 tmp_path：否则本机 data/ 一旦迁移过，
    # split_enabled() 会看到真实的 content.db/user.db，整套用例就会跑在
    # 测试自己造的临时 goshor.db 之外（这里刻意让它们不存在 = legacy 模式）
    monkeypatch.setattr(db, "CONTENT_DB_PATH", tmp_path / "content.db")
    monkeypatch.setattr(db, "USER_DB_PATH", tmp_path / "user.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    return db


@pytest.fixture()
def mobile_db(tmp_path, monkeypatch):
    """手机端多身份库：共享库 + 个人库 + TEMP VIEW。"""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "CONTENT_DB_PATH", tmp_path / "content.db")
    monkeypatch.setattr(db, "USER_DB_PATH", tmp_path / "user.db")
    monkeypatch.setattr(db, "IS_MOBILE", False)
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    db.enable_mobile()
    db.set_user(1)
    yield db
    db.IS_MOBILE = False


@pytest.fixture(autouse=True)
def _isolate_split_paths(tmp_path, monkeypatch):
    """默认把所有用例隔离在 legacy 单库模式。

    拆分模式判定只看 `content.db` / `user.db` 是否存在。本机 `data/` 一旦跑过
    `tools/migrate_split.py`，只 patch `db.DB_PATH` 的老用例就会掉进 split 模式，
    读写**真实**的 user.db —— 这里统一把三个路径都指到 tmp_path（不创建文件，
    因此 `split_state()` 仍是 `legacy`）。

    为什么连 `DB_PATH` 也要 patch：`split_state()` 还会看
    `goshor.db` 和 `goshor.db.migrated` 是否存在。开发机迁移过之后真实
    `data/goshor.db.migrated` 常在，只 patch 两个新库路径的话，
    判定会凭空得到 `broken`，让一批无关用例红掉。
    """
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "goshor.db")
    monkeypatch.setattr(db, "CONTENT_DB_PATH", tmp_path / "content.db")
    monkeypatch.setattr(db, "USER_DB_PATH", tmp_path / "user.db")


def seed_docs(conn, docs: list[dict]) -> None:
    """向 documents 表写入测试题目。"""
    for i, d in enumerate(docs, 1):
        conn.execute(
            """INSERT INTO documents
               (id,path,kind,title,module,daclass,region,year,kaodian,data,search_text)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (i, f"p{i}", d.get("kind", "真题"), d["title"], d.get("module", ""),
             d.get("daclass", ""), d.get("region", ""), d.get("year", ""),
             d.get("kaodian", ""), json.dumps(d.get("data", {}), ensure_ascii=False),
             d.get("search_text", d["title"])),
        )
    conn.commit()
