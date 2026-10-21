"""从全量 content.db 抽一个小体积「示例题库」，随 exe 分发。

用途：全新安装的桌面版开箱就有题可刷（而不是「题库 0 道」的空壳）。
示例包只含少量真题 / 考点 / 材料 / 时政，用户之后导入自己的题库时是追加，
不会因为先有示例而丢数据。

用法：
    python tools/make_sample_db.py                        # 默认输出 assets/content-sample.db
    python tools/make_sample_db.py --per-module 60        # 每个模块抽 60 道
    python tools/make_sample_db.py --src data/content.db --out assets/content-sample.db

设计取舍：
- **保留原始 doc id**。个人记录里存的是 doc_id，id 一旦重排，示例库与用户之后的
  全量导入就对不上，错题本会指向别的题。
- 只复制 SHARED_SCHEMA 三张表，绝不带个人表——示例包里出现 `answers` 之类的表
  会让「只读题库」的边界变得可疑。
- FTS 是普通 fts5 表（非 external-content），只能逐行 INSERT，不能 rebuild。
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import SHARED_SCHEMA  # noqa: E402  只借用 schema 定义，保持单一来源

# 各模块默认抽多少道真题；模块名来自 documents.module
DEFAULT_PER_MODULE = 40
# 考点 / 材料 / 时政的默认抽样量（材料按题量比例自动多给一些）
DEFAULT_KAODIAN = 120
DEFAULT_MATERIAL = 40


def _rows(conn: sqlite3.Connection, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
    conn.row_factory = sqlite3.Row
    return conn.execute(sql, args).fetchall()


def build(src: Path, out: Path, per_module: int, kaodian: int, material: int) -> dict:
    if not src.exists():
        raise SystemExit(f"源库不存在：{src}")
    if out.exists():
        out.unlink()

    src_conn = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    src_conn.row_factory = sqlite3.Row
    try:
        modules = [
            r["module"]
            for r in src_conn.execute(
                "SELECT module, COUNT(*) c FROM documents WHERE kind='真题' "
                "GROUP BY module ORDER BY c DESC"
            )
            if r["module"]
        ]

        picked: list[sqlite3.Row] = []
        for mod in modules:
            picked += src_conn.execute(
                "SELECT * FROM documents WHERE kind='真题' AND module=? "
                "ORDER BY (difficulty='mid') DESC, RANDOM() LIMIT ?",
                (mod, per_module),
            ).fetchall()

        # 资料分析这类题型依赖材料，按 material_fp 把对应材料一并带上，
        # 否则示例库里的资料分析题会因为找不到材料而渲染成空白。
        fps = {r["material_fp"] for r in picked if r["material_fp"]}
        extra_materials = []
        if fps:
            extra_materials = src_conn.execute(
                "SELECT * FROM documents WHERE kind='材料' AND "
                f"material_fp IN ({','.join('?' * len(fps))})",
                tuple(fps),
            ).fetchall()

        kaodians = src_conn.execute(
            "SELECT * FROM documents WHERE kind='考点' ORDER BY RANDOM() LIMIT ?",
            (kaodian,),
        ).fetchall()

        have_fps = {r["material_fp"] for r in extra_materials}
        rand_materials = src_conn.execute(
            "SELECT * FROM documents WHERE kind='材料' "
            f"{('AND material_fp NOT IN (' + ','.join('?' * len(have_fps)) + ')') if have_fps else ''} "
            "ORDER BY RANDOM() LIMIT ?",
            (*tuple(have_fps), material) if have_fps else (material,),
        ).fetchall()

        docs: dict[int, sqlite3.Row] = {}
        for r in list(picked) + list(extra_materials) + list(kaodians) + list(rand_materials):
            docs[r["id"]] = r

        shizheng = src_conn.execute("SELECT * FROM shizheng").fetchall()
    finally:
        src_conn.close()

    out.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(out)
    try:
        conn.executescript(SHARED_SCHEMA)
        cols = [d[0] for d in sqlite3.connect(f"file:{src}?mode=ro", uri=True)
                .execute("SELECT * FROM documents LIMIT 0").description]
        placeholders = ",".join("?" * len(cols))
        collist = ",".join(cols)
        for r in docs.values():
            conn.execute(
                f"INSERT INTO documents({collist}) VALUES({placeholders})",
                tuple(r[c] for c in cols),
            )
            conn.execute(
                "INSERT INTO docs_fts(rowid,title,content) VALUES (?,?,?)",
                (r["id"], r["title"], r["search_text"]),
            )
        for r in shizheng:
            scols = list(r.keys())
            conn.execute(
                f"INSERT INTO shizheng({','.join(scols)}) VALUES({','.join('?' * len(scols))})",
                tuple(r[c] for c in scols),
            )
        conn.commit()

        stat = {
            "真题": conn.execute("SELECT COUNT(*) c FROM documents WHERE kind='真题'").fetchone()[0],
            "考点": conn.execute("SELECT COUNT(*) c FROM documents WHERE kind='考点'").fetchone()[0],
            "材料": conn.execute("SELECT COUNT(*) c FROM documents WHERE kind='材料'").fetchone()[0],
            "时政": conn.execute("SELECT COUNT(*) c FROM shizheng").fetchone()[0],
            "文档合计": len(docs),
            "FTS": conn.execute("SELECT COUNT(*) c FROM docs_fts").fetchone()[0],
            "体积MB": round(out.stat().st_size / 1024 / 1024, 2),
        }
    finally:
        conn.close()
    return stat


def main() -> int:
    ap = argparse.ArgumentParser(description="生成随 exe 分发的示例题库")
    ap.add_argument("--src", default=str(ROOT / "data" / "content.db"))
    ap.add_argument("--out", default=str(ROOT / "assets" / "content-sample.db"))
    ap.add_argument("--per-module", type=int, default=DEFAULT_PER_MODULE)
    ap.add_argument("--kaodian", type=int, default=DEFAULT_KAODIAN)
    ap.add_argument("--material", type=int, default=DEFAULT_MATERIAL)
    args = ap.parse_args()

    t0 = time.time()
    stat = build(Path(args.src), Path(args.out), args.per_module, args.kaodian, args.material)
    print(f"示例题库已生成：{args.out}（{time.time() - t0:.1f}s）")
    for k, v in stat.items():
        print(f"  {k:<6} {v}")

    # 自检：抽出的真题必须每道都有一致性（有选项、有答案或有解析）
    conn = sqlite3.connect(f"file:{args.out}?mode=ro", uri=True)
    try:
        rows = conn.execute(
            "SELECT COUNT(*) FROM documents WHERE kind='真题' AND (data='{}' OR data='')"
        ).fetchone()[0]
    finally:
        conn.close()
    if rows:
        print(f"⚠ 有 {rows} 道真题 data 为空，示例库里会是坏题")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
