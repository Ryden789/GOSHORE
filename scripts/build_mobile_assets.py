"""构建独立版安卓 App 的打包资产（.tools/mobile_prep/mobile_assets）

1) VACUUM 数据库副本并删除 FTS 表（手机端不做全文搜索）
2) 扫描题目 JSON，收集实际引用的图片
3) 生成 payload.zip：数据库（DEFLATE）+ 图片（STORED）
4) 复制手机前端 static/m → assets/web/m

配合 android/ 工程构建出手机独立运行的 APK（无需电脑）。
"""
import json
import os
import re
import shutil
import sqlite3
import urllib.parse
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(BASE_DIR, "data", "goshor.db")
SETTINGS = os.path.join(BASE_DIR, "data", "settings.json")
PREP = os.path.join(BASE_DIR, ".tools", "mobile_prep")

with open(SETTINGS, encoding="utf-8") as f:
    VAULT = json.load(f)["vault_path"]

ASSETS = os.path.join(PREP, "mobile_assets")
os.makedirs(ASSETS, exist_ok=True)

# 1) VACUUM 副本；手机端不用全文搜索，删除 FTS 全部表后再压缩
dst_db = os.path.join(PREP, "goshor.db")
if not os.path.exists(dst_db):
    print("复制数据库…")
    shutil.copy2(SRC, dst_db)
conn = sqlite3.connect(dst_db)
fts_tables = [r[0] for r in conn.execute(
    "SELECT name FROM sqlite_master WHERE name LIKE 'docs_fts%'")]
if fts_tables:
    print("删除 FTS 表 %d 个…" % len(fts_tables))
    conn.execute("DROP TABLE IF EXISTS docs_fts")
    for t in fts_tables:
        conn.execute(f"DROP TABLE IF EXISTS '{t}'")
    conn.commit()
    conn.execute("VACUUM")
conn.close()
print("精简库: %.1f MB" % (os.path.getsize(dst_db) / 1024 / 1024))

# 2) 收集引用图片（JSON 里 src 以 " 结尾，排除反斜杠）
pat = re.compile(r'/img\?path=([^"\'&\\ ]+)')
conn = sqlite3.connect(SRC)
rows = conn.execute("SELECT data FROM documents WHERE data LIKE '%/img?path=%'").fetchall()
paths = set()
for (data,) in rows:
    for m in pat.findall(data):
        paths.add(urllib.parse.unquote(m))
conn.close()

found = total_sz = 0
for p in paths:
    fp = os.path.join(VAULT, p.replace("/", os.sep))
    if os.path.exists(fp):
        found += 1
        total_sz += os.path.getsize(fp)
print("引用图片 %d 个，存在 %d 个，%.1f MB" % (len(paths), found, total_sz / 1024 / 1024))

# 3) payload.zip：数据库（DEFLATE 压缩）+ 图片（STORED，图片已压缩）
zip_path = os.path.join(ASSETS, "payload.zip")
if not os.path.exists(zip_path):
    print("打包 payload.zip…")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(dst_db, "goshor.db", compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        for p in sorted(paths):
            fp = os.path.join(VAULT, p.replace("/", os.sep))
            if os.path.exists(fp):
                zf.write(fp, "img/" + p, compress_type=zipfile.ZIP_STORED)
print("payload.zip: %.1f MB" % (os.path.getsize(zip_path) / 1024 / 1024))

# 4) 手机前端放入 web 目录
web_dst = os.path.join(ASSETS, "web")
if os.path.exists(web_dst):
    shutil.rmtree(web_dst)
shutil.copytree(os.path.join(BASE_DIR, "static", "m"), os.path.join(web_dst, "m"))
print("资产目录就绪:", ASSETS)
for f in sorted(os.listdir(ASSETS)):
    fp = os.path.join(ASSETS, f)
    print("  %s  %.1f MB" % (f, os.path.getsize(fp) / 1024 / 1024))
