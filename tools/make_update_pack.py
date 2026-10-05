#!/usr/bin/env python3
"""
GOSHORE APP 热更新包制作脚本
生成符合 _mobile_update_apply() 校验标准的 zip 包。

用法：
  python make_update_pack.py --out "D:\\GOSHORE\\dist\\goshor-update-v2.zip"
  python make_update_pack.py --db "D:\\GOSHORE\\data\\goshor.db" --ver 2 --out "xxx.zip"
"""
import argparse
import json
import sqlite3
import zipfile
import time
from pathlib import Path

DEFAULT_DB = Path(r"D:\GOSHORE\data\goshor.db")
DEFAULT_OUT = Path(r"D:\GOSHORE\dist\goshor-update-v2.zip")


def ensure_bank_meta(conn: sqlite3.Connection, version: int, docs: int) -> None:
    """确保 bank_meta 表存在并写入版本信息。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS bank_meta (key TEXT PRIMARY KEY, value TEXT)"
    )
    conn.execute(
        "INSERT OR REPLACE INTO bank_meta(key, value) VALUES(?, ?)",
        ("version", str(version)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO bank_meta(key, value) VALUES(?, ?)",
        ("docs", str(docs)),
    )
    conn.execute(
        "INSERT OR REPLACE INTO bank_meta(key, value) VALUES(?, ?)",
        ("date", time.strftime("%Y-%m-%d")),
    )
    conn.commit()


def make_pack(db_path: Path, version: int, out_path: Path) -> dict:
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    # 1. 读取当前题数
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]

    # 2. 写入/更新 bank_meta（临时操作，落盘后再打包）
    ensure_bank_meta(conn, version, docs)
    conn.close()

    # 3. 重新连接校验 + 统计时政期数
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    integ = conn.execute("PRAGMA integrity_check").fetchone()[0]
    docs2 = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM bank_meta")}
    sz_count = conn.execute("SELECT COUNT(*) FROM shizheng").fetchone()[0]
    conn.close()

    if integ != "ok":
        raise RuntimeError(f"数据库完整性校验失败: {integ}")
    if docs2 <= 0:
        raise RuntimeError("题库为空，无法打包")

    # 4. 创建 manifest
    manifest = {
        "version": version,
        "docs": docs2,
        "date": meta.get("date", ""),
        "note": f"含 {docs2} 题 + {sz_count} 期时政",
    }

    # 5. 打包
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        z.write(db_path, "goshor.db")

    return {
        "out": str(out_path),
        "version": version,
        "docs": docs2,
        "size": out_path.stat().st_size,
        "integrity": integ,
    }


def main():
    parser = argparse.ArgumentParser(description="制作 GOSHORE APP 热更新包")
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"源数据库（默认: {DEFAULT_DB}）")
    parser.add_argument("--ver", type=int, default=2, help="版本号（默认: 2）")
    parser.add_argument("--out", default=str(DEFAULT_OUT), help=f"输出 zip（默认: {DEFAULT_OUT}）")
    args = parser.parse_args()

    db_path = Path(args.db)
    out_path = Path(args.out)

    print(f"[1/3] 准备数据库: {db_path}")
    print(f"[2/3] 制作更新包 v{args.ver} -> {out_path}")
    try:
        info = make_pack(db_path, args.ver, out_path)
    except Exception as e:
        print(f"[ERR] {e}", file=__import__("sys").stderr)
        __import__("sys").exit(1)

    print(f"[3/3] 打包完成")
    print(f"      版本: v{info['version']}")
    print(f"      题数: {info['docs']}")
    print(f"      完整: {info['integrity']}")
    print(f"      大小: {info['size'] / 1024 / 1024:.1f} MB")
    print(f"[OK] 更新包: {info['out']}")


if __name__ == "__main__":
    main()
