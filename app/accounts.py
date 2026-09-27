"""本地账户系统（离线）。

- PBKDF2-HMAC-SHA256 加盐哈希存储密码；
- 注册 / 登录 / 登出 / 会话持久化；
- 游客（uid=0）数据迁入新账号；
- 老版本（单用户库）升级时把个人数据迁到游客名下。

不依赖任何网络与第三方库。
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import shutil
import sqlite3
import time
from pathlib import Path

from . import db

_ITERS = 200000
_GUEST = 0

# 全部个人表（清空游客/迁移时使用）
PERSONAL_TABLES = [
    "answers", "marks", "speed_rounds", "speed_items",
    "wordfill_questions", "wordfill_answers",
    "wrong_reasons", "review_plan",
    "cards", "card_reviews", "card_plan",
    "essay_grades",
    "formula_rounds", "formula_items",
    "doubts", "explain_cache",
    "my_documents", "doc_overrides", "shizheng_quiz",
]


class AuthError(Exception):
    """账号操作的可展示错误（信息可直接给用户看）。"""


_users_dir: Path | None = None


# ---------------- 初始化 ----------------

def configure(users_dir: Path) -> None:
    global _users_dir
    _users_dir = Path(users_dir)
    _users_dir.mkdir(parents=True, exist_ok=True)
    with _accounts_conn() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS accounts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            salt TEXT NOT NULL,
            pw_hash TEXT NOT NULL,
            created_at REAL)""")


def _accounts_conn() -> sqlite3.Connection:
    if _users_dir is None:
        raise RuntimeError("accounts 未 configure")
    c = sqlite3.connect(_users_dir / "accounts.db")
    c.row_factory = sqlite3.Row
    return c


# ---------------- 密码哈希 ----------------

def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt), _ITERS
    ).hex()


# ---------------- 校验 ----------------

_USERNAME_RE = re.compile(r"^[^\s]{2,20}$")


def _validate(username: str, password: str) -> str:
    u = (username or "").strip()
    if not _USERNAME_RE.match(u):
        raise AuthError("用户名需为 2-20 个字符，且不能包含空格")
    if not password or len(password) < 6:
        raise AuthError("密码至少 6 位")
    if len(password) > 128:
        raise AuthError("密码过长")
    return u


# ---------------- 注册 / 登录 / 登出 ----------------

def register(username: str, password: str, migrate_guest: bool = False) -> dict:
    u = _validate(username, password)
    with _accounts_conn() as c:
        exists = c.execute(
            "SELECT 1 FROM accounts WHERE username=?", (u,)
        ).fetchone()
        if exists:
            raise AuthError("该用户名已被注册")
        salt = secrets.token_hex(16)
        cur = c.execute(
            "INSERT INTO accounts(username,salt,pw_hash,created_at) VALUES(?,?,?,?)",
            (u, salt, _hash(password, salt), time.time()),
        )
        uid = cur.lastrowid
    if migrate_guest:
        _adopt_guest(uid)
    set_session(uid)
    db.set_user(uid)
    return me()


def login(username: str, password: str) -> dict:
    u = (username or "").strip()
    with _accounts_conn() as c:
        row = c.execute(
            "SELECT id,salt,pw_hash FROM accounts WHERE username=?", (u,)
        ).fetchone()
    # 无论用户是否存在都执行一次比较，减少侧信道差异
    ref = row["pw_hash"] if row else "0"
    salt = row["salt"] if row else secrets.token_hex(16)
    if not row or not hmac.compare_digest(_hash(password, salt), ref):
        raise AuthError("用户名或密码错误")
    set_session(row["id"])
    db.set_user(row["id"])
    return me()


def logout() -> dict:
    set_session(_GUEST)
    db.set_user(_GUEST)
    return me()


def use_guest() -> dict:
    set_session(_GUEST)
    db.set_user(_GUEST)
    return me()


def me() -> dict:
    uid = get_session()
    if uid == _GUEST:
        return {"uid": 0, "username": None, "isGuest": True}
    with _accounts_conn() as c:
        row = c.execute("SELECT username FROM accounts WHERE id=?", (uid,)).fetchone()
    if not row:
        set_session(_GUEST)
        return {"uid": 0, "username": None, "isGuest": True}
    return {"uid": uid, "username": row["username"], "isGuest": False}


def profiles() -> list[dict]:
    """已注册账号清单（仅 id/用户名，供登录页选择）。"""
    with _accounts_conn() as c:
        rows = c.execute("SELECT id,username FROM accounts ORDER BY id").fetchall()
    return [{"uid": r["id"], "username": r["username"]} for r in rows]


# ---------------- 会话持久化 ----------------

def _session_path() -> Path:
    assert _users_dir is not None
    return _users_dir / "session.json"


def get_session() -> int:
    try:
        return int(json.loads(_session_path().read_text("utf-8")).get("uid", 0))
    except Exception:
        return 0


def set_session(uid: int) -> None:
    p = _session_path()
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"uid": int(uid)}), encoding="utf-8")
    tmp.replace(p)


# ---------------- 游客数据迁入 ----------------

def _data_path(uid: int) -> Path:
    assert _users_dir is not None
    return _users_dir / f"data_{uid}.db"


def _checkpoint(uid: int) -> None:
    db.set_user(uid)
    c = db.connect()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()


def _adopt_guest(uid: int) -> None:
    """把游客库整体过继给新账号。"""
    # 确保游客库存在且已落盘
    db.set_user(_GUEST)
    db.connect().close()
    _checkpoint(_GUEST)
    src, dst = _data_path(_GUEST), _data_path(uid)
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)
    for ext in ("-wal", "-shm"):
        f = Path(str(dst) + ext)
        if f.exists():
            f.unlink()
    # 清空游客库
    db.set_user(_GUEST)
    c = db.connect()
    for t in PERSONAL_TABLES:
        c.execute(f"DELETE FROM {t}")
    c.commit()
    c.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c.close()


# ---------------- 老版本数据升级 ----------------

def migrate_legacy_if_needed(shared_db: Path) -> dict:
    """旧版单用户库 → data_0（游客）。幂等，完成后写标记。"""
    assert _users_dir is not None
    marker = _users_dir / ".legacy-done"
    if marker.exists():
        return {"skipped": True}

    # 先建好游客个人库
    db.set_user(_GUEST)
    db.connect().close()

    legacy = sqlite3.connect(shared_db)
    c0 = db.connect()
    moved = {}
    existing = {
        r[0]
        for r in legacy.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    for t in PERSONAL_TABLES:
        if t not in existing:
            continue
        old_cols = [r[1] for r in legacy.execute(f"PRAGMA table_info({t})")]
        new_cols = [r[1] for r in c0.execute(f"PRAGMA table_info({t})")]
        cols = [x for x in old_cols if x in new_cols]
        if not cols:
            continue
        collist = ",".join(cols)
        rows = legacy.execute(f"SELECT {collist} FROM {t}").fetchall()
        if rows:
            ph = ",".join("?" * len(cols))
            c0.executemany(
                f"INSERT INTO {t}({collist}) VALUES({ph})", rows
            )
            moved[t] = len(rows)
    c0.commit()
    c0.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    c0.close()
    legacy.close()

    marker.write_text(json.dumps(moved, ensure_ascii=False), encoding="utf-8")
    set_session(_GUEST)
    return {"moved": moved}
