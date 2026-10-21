#!/usr/bin/env python3
"""把桌面端单库 data/goshor.db 拆成 content.db（题库）+ user.db（个人数据）。

用法：
  python tools/migrate_split.py                # 迁移 data/goshor.db
  python tools/migrate_split.py --dry-run      # 只统计，不落盘
  python tools/migrate_split.py --db D:\\GOSHORE\\data\\goshor.db

设计要点（为什么这么做）：
1. **绝不原地改源库**。先把源库用 SQLite 在线备份 API 复制到同目录的临时文件，
   所有读写都在副本上做；最后才用 `os.replace` 把新库换到正式文件名，并把原库
   改名成 `goshor.db.migrated` 保留（不删）。任何一步失败都清掉临时文件，
   原库一个字节都不动。
2. **临时文件放在源库同目录**：`os.replace` 只有在同一个卷上才是原子的；放系统
   临时目录可能跨卷，退化成「复制 + 删除」，中途断电就半残。
3. **校验行数守恒**。题库三张表 + 所有个人表逐表比对源/目标行数，`_meta`
   的 schema_version 必须是本程序支持的版本，全部通过才落盘。
4. FTS 表（docs_fts）是**普通 fts5 表**（不是 external content 表），
   `INSERT INTO docs_fts(docs_fts) VALUES('rebuild')` 对它无效，
   只能逐行复制 rowid/title/content。
"""
import argparse
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db as appdb  # noqa: E402  （需要 ROOT 在 sys.path 上）

# 题库表（进 content.db）
SHARED_TABLES = ("documents", "docs_fts", "shizheng")
# fts5 的影子表（docs_fts_data / _idx / _content / _docsize / _config），不单独搬
_SHADOW_PREFIX = "docs_fts_"


def _out(msg: str = "") -> None:
    print(msg, flush=True)


def _table_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    ).fetchall()
    return [r[0] for r in rows]


def _is_shadow(name: str) -> bool:
    return name.startswith(_SHADOW_PREFIX) or name.startswith("sqlite_")


def _personal_tables(conn: sqlite3.Connection) -> list[str]:
    """个人表 = 源库里除题库表、fts 影子表、sqlite 内部表之外的全部表。"""
    return [
        n for n in _table_names(conn)
        if n not in SHARED_TABLES and not _is_shadow(n)
    ]


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    return row is not None


def _clone_table_schema(dst: sqlite3.Connection, table: str) -> None:
    """按源库（ATTACH 为 src）的 DDL 在目标库补建表 + 索引。

    运行期动态建的表不会出现在 PERSONAL_SCHEMA / _migrate 里，但它们装着真实
    个人数据（例如 variants、bank_meta），必须原样搬过去。索引的建表语句里可能
    有与目标库已有索引重名的，逐个 try 掉即可，不影响数据。
    """
    row = dst.execute(
        "SELECT sql FROM src.sqlite_master WHERE type='table' AND name=?",
        (table,)).fetchone()
    if not row or not row[0]:
        raise RuntimeError(f"源库没有表 {table} 的建表语句，无法迁移")
    dst.execute(row[0])
    idx_rows = dst.execute(
        "SELECT sql FROM src.sqlite_master WHERE type='index' AND tbl_name=? "
        "AND sql IS NOT NULL", (table,)).fetchall()
    for (sql,) in idx_rows:
        try:
            dst.execute(sql)
        except sqlite3.OperationalError:
            # 索引已存在（或与目标库同名）时跳过：数据完整性不依赖索引
            pass


def _count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _columns(conn: sqlite3.Connection, table: str, schema: str = "main") -> list[str]:
    return [r[1] for r in conn.execute(f'PRAGMA {schema}.table_info("{table}")')]


def _schema_version(conn: sqlite3.Connection) -> int:
    try:
        row = conn.execute(
            "SELECT value FROM _meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 0
    except sqlite3.OperationalError:
        return 0


def _fmt_size(n: int) -> str:
    if n >= 1024 ** 3:
        return f"{n / 1024 ** 3:.2f} GB"
    if n >= 1024 ** 2:
        return f"{n / 1024 ** 2:.2f} MB"
    return f"{n / 1024:.1f} KB"


def _copy_table(dst: sqlite3.Connection, table: str) -> int:
    """把附加为 `src` 的源库里的 table 复制进目标主库，返回复制的列数。

    只复制两边**共有**的列：老版本源库可能缺新加的列（例如
    wrong_reasons.ai_category），目标表由 PERSONAL_SCHEMA 建好、缺的列取默认值；
    直接 `INSERT INTO t SELECT * FROM src.t` 会因列数不一致报错。

    用 `INSERT OR REPLACE`：目标库在复制前已经跑过一次 `_migrate`（为了建出
    `doc_notes` 这类只存在于迁移步骤里的表），`_meta` 里已经有 schema_version 行，
    普通 INSERT 会撞主键。其余表复制时还是空的，OR REPLACE 与 INSERT 等价。

    目标库没有的表（`annihilations` / `variants` / `bank_meta` 这些是**运行期
    动态建**的，既不在 PERSONAL_SCHEMA 也不在 _migrate 里）按源库的建表语句
    原样补建，索引一并补上，否则真实旧库会在这里报 no such table。
    """
    if not _table_exists(dst, table):
        _clone_table_schema(dst, table)
    dst_cols = _columns(dst, table)
    src_cols = set(_columns(dst, table, "src"))
    cols = [c for c in dst_cols if c in src_cols]
    if not cols:
        return 0
    q = ",".join(f'"{c}"' for c in cols)
    dst.execute(f'INSERT OR REPLACE INTO "{table}" ({q}) SELECT {q} FROM src."{table}"')
    return len(cols)


def _backup(src_conn: sqlite3.Connection, dest: Path) -> None:
    """用在线备份 API 复制源库（自动包含 WAL 里未 checkpoint 的事务）。"""
    out = sqlite3.connect(dest, timeout=15)
    try:
        src_conn.backup(out)
        out.commit()
    finally:
        out.close()


def _build_content(copy_path: Path, dest: Path) -> dict[str, int]:
    conn = sqlite3.connect(dest, timeout=15)
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(appdb.SHARED_SCHEMA)
        conn.execute("ATTACH DATABASE ? AS src", (str(copy_path),))
        counts = {}
        for t in ("documents", "shizheng"):
            _copy_table(conn, t)
            counts[t] = _count(conn, t)
        # fts5 表逐行复制（rebuild 只适用于 external-content 表；本表不是）
        conn.execute(
            "INSERT INTO docs_fts(rowid,title,content) "
            "SELECT rowid,title,content FROM src.docs_fts")
        counts["docs_fts"] = _count(conn, "docs_fts")
        # 旧题库可能缺 difficulty / material_fp 列 → 补列（target 已有）+
        # 回填材料指纹，与 legacy init_db 的行为对齐
        appdb._ensure_content_columns(conn)
        conn.commit()
        conn.execute("DETACH DATABASE src")
        return counts
    finally:
        conn.close()


def _build_user(copy_path: Path, dest: Path,
                tables: list[str]) -> dict[str, int]:
    conn = sqlite3.connect(dest, timeout=15)
    try:
        conn.row_factory = sqlite3.Row
        conn.executescript(appdb.PERSONAL_SCHEMA)
        # 先跑一次迁移：`doc_notes` / `paper_drafts` / `mastery` 等表只在这里建，
        # PERSONAL_SCHEMA 里没有；不先建好，复制旧库数据时会 no such table。
        appdb._migrate(conn)
        conn.commit()
        conn.execute("ATTACH DATABASE ? AS src", (str(copy_path),))
        counts = {}
        for t in tables:
            _copy_table(conn, t)
            counts[t] = _count(conn, t)
        conn.commit()
        conn.execute("DETACH DATABASE src")
        # 复制过来的 `_meta` 带着源库版本号（可能 < 当前）；再跑一次迁移，
        # 把版本补到最新并兜住「_meta 缺项」的极端情况。幂等。
        appdb._migrate(conn)
        conn.commit()
        conn.execute("PRAGMA journal_mode=WAL")
        return counts
    finally:
        conn.close()


def _verify_counts(src: sqlite3.Connection, new: sqlite3.Connection,
                   tables: list[str]) -> list[str]:
    bad = []
    for t in tables:
        a, b = _count(src, t), _count(new, t)
        if a != b:
            bad.append(f"{t}: 源 {a} 行 → 新 {b} 行")
    return bad


def migrate(db_path: Path | str = ROOT / "data" / "goshor.db",
            dry_run: bool = False) -> int:
    """执行迁移，返回进程退出码（0 成功 / 1 失败）。"""
    t0 = time.perf_counter()
    src = Path(db_path).resolve()
    parent = src.parent
    content_db = parent / "content.db"
    user_db = parent / "user.db"
    migrated = Path(str(src) + ".migrated")

    if not src.exists():
        _out(f"✗ 源库不存在：{src}")
        return 1
    # 「已迁移」判定：只要新库出现就拒绝继续，绝不覆盖用户已有的个人数据
    if content_db.exists() or user_db.exists():
        _out(f"✗ 目录里已存在 {content_db.name} 或 {user_db.name}，看起来已经迁移过。")
        _out("  为避免覆盖数据，本工具不重复执行（如需重跑，请先备份并手动移除新库）。")
        return 1
    if migrated.exists():
        _out(f"✗ 已存在 {migrated.name}（上一次迁移的备份），请先确认处理。")
        return 1

    src_conn = sqlite3.connect(src, timeout=15)
    src_conn.row_factory = sqlite3.Row
    try:
        personal = _personal_tables(src_conn)
        version = _schema_version(src_conn)
        if version > appdb.SCHEMA_VERSION:
            _out(f"✗ 源库 schema_version={version} 高于本程序支持的 "
                 f"{appdb.SCHEMA_VERSION}，请先升级程序。")
            return 1
        counts = {t: _count(src_conn, t) for t in SHARED_TABLES}
        counts.update({t: _count(src_conn, t) for t in personal})

        _out(f"源库：{src}")
        _out(f"       {_fmt_size(src.stat().st_size)}  "
             f"schema_version={version}（本程序 {appdb.SCHEMA_VERSION}）")
        _out("")
        _out(f"将迁入 content.db（题库 {len(SHARED_TABLES)} 张表）：")
        for t in SHARED_TABLES:
            _out(f"  {t:<28}{counts[t]:>8} 行")
        _out(f"将迁入 user.db（个人表 {len(personal)} 张）：")
        for t in personal:
            _out(f"  {t:<28}{counts[t]:>8} 行")
        _out("")

        if dry_run:
            _out("--dry-run：只统计，不写任何文件。")
            _out(f"耗时 {time.perf_counter() - t0:.2f}s")
            return 0

        # 临时目录必须和源库同一个卷，os.replace 才是原子的
        tmp = Path(tempfile.mkdtemp(prefix=".split-migrate-", dir=parent))
        try:
            copy_path = tmp / "source-copy.db"
            _backup(src_conn, copy_path)
            new_content = tmp / "content.db"
            new_user = tmp / "user.db"

            content_counts = _build_content(copy_path, new_content)
            user_counts = _build_user(copy_path, new_user, personal)

            # ---- 校验：逐表行数 + schema 版本 ----
            problems = []
            cc = sqlite3.connect(new_content, timeout=15)
            try:
                problems += _verify_counts(src_conn, cc, list(SHARED_TABLES))
            finally:
                cc.close()
            uc = sqlite3.connect(new_user, timeout=15)
            try:
                problems += _verify_counts(src_conn, uc, personal)
                new_version = _schema_version(uc)
            finally:
                uc.close()
            if new_version != appdb.SCHEMA_VERSION:
                problems.append(
                    f"_meta.schema_version={new_version}，应为 {appdb.SCHEMA_VERSION}")
            if problems:
                _out("✗ 校验失败，已放弃落盘（原库未改动）：")
                for p in problems:
                    _out(f"  - {p}")
                return 1

            # ---- 落盘：先放新库，最后改名原库；任一步失败回滚新库 ----
            # 必须先关掉源库连接：Windows 不允许 rename 一个仍被打开的文件
            # （os.replace 会抛 PermissionError）；关闭时也会把 -wal 里的
            # 事务 checkpoint 回主文件，保证 .migrated 那份备份是完整的。
            src_conn.close()

            placed = []
            try:
                os.replace(new_content, content_db)
                placed.append(content_db)
                os.replace(new_user, user_db)
                placed.append(user_db)
                os.replace(src, migrated)
                # WAL/SHM 跟着主库改名，保证 .migrated 这份备份仍然完整可读
                for suffix in ("-wal", "-shm"):
                    side = Path(str(src) + suffix)
                    if side.exists():
                        os.replace(side, Path(str(migrated) + suffix))
            except Exception:
                for p in placed:
                    try:
                        p.unlink()
                    except OSError:
                        pass
                raise
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

        elapsed = time.perf_counter() - t0
        _out("✓ 迁移完成")
        _out("")
        _out(f"content.db  {_fmt_size(content_db.stat().st_size)}  → {content_db}")
        for t in SHARED_TABLES:
            _out(f"  {t:<28}{content_counts[t]:>8} 行")
        _out(f"user.db     {_fmt_size(user_db.stat().st_size)}  → {user_db}")
        for t in personal:
            _out(f"  {t:<28}{user_counts[t]:>8} 行")
        _out("")
        _out(f"原库已改名保留：{migrated.name}（{_fmt_size(migrated.stat().st_size)}）")
        _out(f"耗时 {elapsed:.2f}s")
        return 0
    finally:
        src_conn.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="把 goshor.db 拆成 content.db（题库）+ user.db（个人数据）")
    ap.add_argument("--db", default=str(ROOT / "data" / "goshor.db"),
                    help="源库路径（默认 data/goshor.db）")
    ap.add_argument("--dry-run", action="store_true",
                    help="只打印将搬的表与行数，不落盘")
    args = ap.parse_args(argv)
    try:
        return migrate(Path(args.db), dry_run=args.dry_run)
    except Exception as e:  # noqa: BLE001  顶层兜底：原库必须保持原样
        _out(f"✗ 迁移失败：{e!r}")
        _out("  原库未被修改；临时文件已清理。")
        return 1


if __name__ == "__main__":
    sys.exit(main())
