"""在隔离库中验收真实 vault 重扫、换源及排期/掌握度续写。

用法：python tools/verify_qid_reindex.py --vault <源目录> --out reports/qid-reindex.json
仅复制 Markdown 到临时目录；不修改源目录、应用设置或正式数据库。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def _snapshot():
    conn = db.connect()
    try:
        return {
            table: [dict(r) for r in conn.execute(f"SELECT * FROM {table} ORDER BY doc_id")]
            for table in ("review_plan", "mastery")
        } | {"answers": conn.execute("SELECT COUNT(*) FROM answers").fetchone()[0]}
    finally:
        conn.close()


def verify(vault: Path, work: Path, split: bool) -> dict:
    settings = {"vault_path": str(vault)}
    with (patch.object(db, "DB_PATH", work / "goshor.db"),
          patch.object(db, "CONTENT_DB_PATH", work / "content.db"),
          patch.object(db, "USER_DB_PATH", work / "user.db"),
          patch.object(db, "IS_MOBILE", False),
          patch.object(db, "load_settings", lambda: settings)):
        conn = db.connect()
        db.init_db(conn)
        conn.close()
        if split:
            source = sqlite3.connect(db.DB_PATH)
            try:
                for target_path in (db.CONTENT_DB_PATH, db.USER_DB_PATH):
                    target = sqlite3.connect(target_path)
                    try:
                        source.backup(target)
                    finally:
                        target.close()
            finally:
                source.close()
            db.DB_PATH.unlink()

        scans = [db.reindex()]
        assert scans[0]["ok"], scans[0]
        conn = db.connect()
        try:
            rows = conn.execute(
                "SELECT id,qid,path FROM documents WHERE kind='真题' AND qid<>'' "
                "AND (SELECT COUNT(*) FROM documents d WHERE d.qid=documents.qid)=1 "
                "ORDER BY id LIMIT 20").fetchall()
            total = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        finally:
            conn.close()
        assert rows, "没有可用于验收的稳定题号"
        for row in rows:
            db.add_answer(row["id"], "B", False, 1000)
            db.add_answer(row["id"], "A", True, 1000)
        db.save_paper_draft("normal", "换源验收", [r["id"] for r in rows], {})
        before = _snapshot()
        checks = {}
        for i in range(2):
            scans.append(db.reindex())
            assert scans[-1]["ok"], scans[-1]
            assert _snapshot() == before, f"第 {i + 1} 次重扫改变了进度"
        checks["repeat_scan_preserves_progress"] = True

        # 改变每份文档的相对路径并反转排序，确实触发删除、重建及数字 id 重排。
        files = []
        for directory, dirs, names in os.walk(vault):
            dirs[:] = [d for d in dirs if not d.startswith(".")]
            files.extend(Path(directory) / n for n in names if n.endswith(".md"))
        files.sort()
        relocated = work / "relocated-vault"
        for i, source in enumerate(files):
            relative = source.relative_to(vault)
            target = relocated / relative.parent / f"{len(files) - i:06d}-{relative.name}"
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        settings["vault_path"] = str(relocated)
        scans.append(db.reindex())
        assert scans[-1]["ok"], scans[-1]
        assert scans[-1]["changed"] == scans[-1]["removed"] == total
        assert _snapshot() == before, "换源重建改变了进度"
        checks["relocated_scan_preserves_progress"] = True
        current = {r["qid"]: db.doc_id_by_qid(r["qid"]) for r in rows}
        moved = sum(current[r["qid"]] != r["id"] for r in rows)
        assert moved > 0, "验收没有触发数字 id 变化"
        for row in rows:
            doc_id = current[row["qid"]]
            assert db.mastery_map()[doc_id] == before["mastery"][0]["score"]
            db.add_answer(doc_id, "A", True, 1000)
        after = _snapshot()
        assert len(after["review_plan"]) == len(rows)
        assert len(after["mastery"]) == len(rows)
        assert all(r["stage"] == 3 for r in after["review_plan"])
        assert all(abs(r["score"] - 0.57) < 1e-9 for r in after["mastery"])
        assert after["answers"] == before["answers"] + len(rows)
        checks["answers_continue_progress"] = True
        conn = db.connect()
        try:
            blank = conn.execute(
                "SELECT COUNT(*) FROM review_plan WHERE COALESCE(qid,'')=''").fetchone()[0]
            lost = conn.execute(
                "SELECT COUNT(*) FROM review_plan p WHERE NOT EXISTS "
                "(SELECT 1 FROM documents d WHERE d.qid=p.qid)").fetchone()[0]
        finally:
            conn.close()
        assert blank == lost == 0
        checks["review_plan_has_no_blank_or_lost_qid"] = True
        return {"mode": "split" if split else "legacy", "documents": total,
                "sample_questions": len(rows), "changed_sample_ids": moved,
                "scans": scans, "checks": checks, "progress_before": before,
                "progress_after": after}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vault", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--split", action="store_true")
    args = parser.parse_args(argv)
    vault = args.vault.resolve()
    if not vault.is_dir():
        parser.error("vault 必须为现有目录")
    scratch = ROOT / ".tmp"
    scratch.mkdir(exist_ok=True)
    started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="qid-reindex-", dir=scratch) as raw:
        result = verify(vault, Path(raw), args.split)
    result["elapsed_seconds"] = round(time.perf_counter() - started, 2)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if not k.startswith("progress_")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
