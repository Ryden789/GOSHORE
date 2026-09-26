"""一次性脚本：对所有已入库真题重新应用 parser（使 P2-7 最快解法剥离生效），保留 doc id。"""
import json
from pathlib import Path
from app import db, parser
from app.config import load_settings

vault = Path(load_settings()["vault_path"])
conn = db.connect()
rows = conn.execute("SELECT id, path, data FROM documents WHERE kind='真题'").fetchall()
fixed = stripped = 0
for r in rows:
    fp = vault / r["path"]
    if not fp.exists():
        continue
    p = parser.parse(r["path"], fp.read_text(encoding="utf-8"))
    old = json.loads(r["data"] or "{}")
    new = p.data
    # 只更新受影响的字段
    if old.get("reasoning") != new.get("reasoning") or old.get("fastest") != new.get("fastest"):
        old["reasoning"] = new.get("reasoning", "")
        old["fastest"] = new.get("fastest", "")
        conn.execute("UPDATE documents SET data=? WHERE id=?", (json.dumps(old, ensure_ascii=False), r["id"]))
        fixed += 1
        if "最快解法" not in (new.get("reasoning") or ""):
            stripped += 1
conn.commit()
print(f"total={len(rows)} fixed={fixed} stripped={stripped}")
