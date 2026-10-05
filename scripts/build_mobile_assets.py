"""构建独立版安卓 App 的打包资产（.tools/mobile_prep/mobile_assets）

默认模式（完整构建）：
1) 数据库副本：删除 FTS 表与全部个人数据表（新架构下共享库只保留
   documents 题库与 shizheng 时政库），再 VACUUM
2) 扫描题目 JSON，收集实际引用的图片
3) 生成 payload.zip：数据库（DEFLATE）+ 图片（STORED）
4) 复制手机前端 static/m → assets/web/m

--pack-update 模式（题库热更新包）：
从 data/goshor.db 出 goshor-update-vN.zip（manifest.json + 剥离个人表并
VACUUM 的 goshor.db + 相对上一版新增的 img/ 图片）。
硬校验：新库必须包含上一版全部 doc_id（只增不删），否则拒绝出包。

配合 android/ 工程构建出手机独立运行的多账号 APK（无需电脑）。
"""
import datetime
import json
import os
import re
import shutil
import sqlite3
import sys
import urllib.parse
import zipfile

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)
from app.accounts import PERSONAL_TABLES  # noqa: E402

SRC = os.path.join(BASE_DIR, "data", "goshor.db")
SETTINGS = os.path.join(BASE_DIR, "data", "settings.json")
PREP = os.path.join(BASE_DIR, ".tools", "mobile_prep")
DIST = os.path.join(BASE_DIR, "dist")

with open(SETTINGS, encoding="utf-8") as f:
    VAULT = json.load(f)["vault_path"]

IMG_PAT = re.compile(r'/img\?path=([^"\'&\\ ]+)')


def _strip_and_vacuum(src: str, dst: str, version: int = 0,
                      date: str = "") -> int:
    """复制题库 → 删 FTS/个人表 → 写入 bank_meta（version>0 时）→ VACUUM。

    返回 documents 题数。journal_mode 置 DELETE：保证单文件完整、
    安卓端只读打开不依赖 -wal/-shm。
    """
    if os.path.exists(dst):
        os.remove(dst)
    shutil.copy2(src, dst)
    conn = sqlite3.connect(dst)
    for t in [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE name LIKE 'docs_fts%'")]:
        conn.execute(f"DROP TABLE IF EXISTS '{t}'")
    for t in PERSONAL_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS '{t}'")
    docs = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    if version > 0:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS bank_meta"
            "(key TEXT PRIMARY KEY, value TEXT)")
        conn.execute("INSERT OR REPLACE INTO bank_meta VALUES('version', ?)",
                     (str(version),))
        conn.execute("INSERT OR REPLACE INTO bank_meta VALUES('date', ?)",
                     (date,))
        conn.execute("INSERT OR REPLACE INTO bank_meta VALUES('docs', ?)",
                     (str(docs),))
    conn.commit()
    conn.execute("PRAGMA journal_mode=DELETE")
    conn.execute("VACUUM")
    conn.close()
    return docs


def _doc_ids(db_path: str) -> set:
    """库里全部 documents id 集合（显式关连接，Windows 下不留句柄）。"""
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute("SELECT id FROM documents")}
    finally:
        conn.close()


def _img_refs(db_path: str) -> set:
    """库里全部题目 JSON 实际引用的图片相对路径集合。"""
    conn = sqlite3.connect(db_path)
    rows = conn.execute(
        "SELECT data FROM documents WHERE data LIKE '%/img?path=%'").fetchall()
    conn.close()
    paths = set()
    for (data,) in rows:
        for m in IMG_PAT.findall(data):
            paths.add(urllib.parse.unquote(m))
    return paths


def pack_update(src: str = SRC, prev_db: str = "", dist: str = DIST,
                ver_f: str = "", version: int = 0) -> str:
    """出题库热更新包 goshor-update-vN.zip（只增不删硬校验），返回 zip 路径。"""
    prev_db = prev_db or os.path.join(PREP, "goshor.db")
    ver_f = ver_f or os.path.join(PREP, "bank_version.json")
    if not os.path.exists(prev_db):
        raise RuntimeError(
            "缺少上一版题库 %s（先运行一次完整构建）" % prev_db)
    # 版本：上一版 +1（可用 --version N / 参数显式指定）
    prev_ver = 1
    if os.path.exists(ver_f):
        try:
            with open(ver_f, encoding="utf-8") as f:
                prev_ver = int(json.load(f)["version"])
        except Exception:
            pass
    if not version:
        version = prev_ver + 1
    date = datetime.date.today().isoformat()
    print("制包：v%d → v%d（%s）" % (prev_ver, version, date))

    # 1) 新库副本：剥离 FTS/个人表 + bank_meta + VACUUM
    tmp_db = os.path.join(os.path.dirname(prev_db), "update_new.db")
    print("复制并剥离新题库…")
    docs = _strip_and_vacuum(src, tmp_db, version, date)
    print("新库题数：%d（%.1f MB）"
          % (docs, os.path.getsize(tmp_db) / 1024 / 1024))

    # 2) 硬校验：新库必须包含上一版全部 doc_id（只增不删，
    #    否则个人库错题/收藏会成死链）
    prev_ids = _doc_ids(prev_db)
    new_ids = _doc_ids(tmp_db)
    missing = prev_ids - new_ids
    if missing:
        os.remove(tmp_db)
        raise RuntimeError(
            "拒绝出包：新库缺少上一版 %d 个 doc_id（只增不删），示例：%s\n"
            "要下线题目请标记「已废弃」，不要物理删除。"
            % (len(missing), sorted(missing)[:5]))
    print("硬校验通过：上一版 %d 题全部保留，新增 %d 题"
          % (len(prev_ids), len(new_ids - prev_ids)))

    # 3) 增量图片：新库引用 - 上一版引用
    delta = _img_refs(tmp_db) - _img_refs(prev_db)
    found = 0
    for p in delta:
        if os.path.exists(os.path.join(VAULT, p.replace("/", os.sep))):
            found += 1
    print("增量图片 %d 个（存在 %d 个）" % (len(delta), found))

    # 4) 出包
    os.makedirs(dist, exist_ok=True)
    zip_path = os.path.join(dist, "goshor-update-v%d.zip" % version)
    manifest = {"version": version, "docs": docs, "date": date}
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("manifest.json",
                    json.dumps(manifest, ensure_ascii=False, indent=2))
        zf.write(tmp_db, "goshor.db",
                 compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        for p in sorted(delta):
            fp = os.path.join(VAULT, p.replace("/", os.sep))
            if os.path.exists(fp):
                zf.write(fp, "img/" + p,
                         compress_type=zipfile.ZIP_STORED)
    os.remove(tmp_db)
    print("更新包：%s（%.1f MB）"
          % (zip_path, os.path.getsize(zip_path) / 1024 / 1024))

    # 5) 记录版本号，供下次制包递增
    with open(ver_f, "w", encoding="utf-8") as f:
        json.dump({"version": version, "date": date, "docs": docs},
                  f, ensure_ascii=False, indent=2)
    print("版本记录已更新：v%d" % version)
    return zip_path


def build_all() -> None:
    """完整构建：payload.zip（题库+图片）+ 手机前端 → mobile_assets。"""
    assets = os.path.join(PREP, "mobile_assets")
    os.makedirs(assets, exist_ok=True)

    # 版本号（默认 1；若此前出过更新包则沿用已记录的版本）
    ver_f = os.path.join(PREP, "bank_version.json")
    version = 1
    if os.path.exists(ver_f):
        try:
            with open(ver_f, encoding="utf-8") as f:
                version = int(json.load(f)["version"])
        except Exception:
            pass
    date = datetime.date.today().isoformat()

    # 1) 每次从源库重建：删 FTS + 个人表，VACUUM；手机端共享库只读
    dst_db = os.path.join(PREP, "goshor.db")
    print("复制数据库…")
    docs = _strip_and_vacuum(SRC, dst_db, version, date)
    print("共享库: %.1f MB（%d 题，v%d）"
          % (os.path.getsize(dst_db) / 1024 / 1024, docs, version))

    # 2) 收集引用图片（JSON 里 src 以 " 结尾，排除反斜杠）
    paths = _img_refs(SRC)

    found = total_sz = 0
    for p in paths:
        fp = os.path.join(VAULT, p.replace("/", os.sep))
        if os.path.exists(fp):
            found += 1
            total_sz += os.path.getsize(fp)
    print("引用图片 %d 个，存在 %d 个，%.1f MB"
          % (len(paths), found, total_sz / 1024 / 1024))

    # 3) payload.zip：数据库（DEFLATE 压缩）+ 图片（STORED，图片已压缩）
    zip_path = os.path.join(assets, "payload.zip")
    if os.path.exists(zip_path):
        os.remove(zip_path)
    print("打包 payload.zip…")
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.write(dst_db, "goshor.db",
                 compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
        for p in sorted(paths):
            fp = os.path.join(VAULT, p.replace("/", os.sep))
            if os.path.exists(fp):
                zf.write(fp, "img/" + p, compress_type=zipfile.ZIP_STORED)
    print("payload.zip: %.1f MB" % (os.path.getsize(zip_path) / 1024 / 1024))

    # 4) 手机前端放入 web 目录
    web_dst = os.path.join(assets, "web")
    if os.path.exists(web_dst):
        shutil.rmtree(web_dst)
    shutil.copytree(os.path.join(BASE_DIR, "static", "m"),
                    os.path.join(web_dst, "m"))
    # 申论/综应真题库随前端分发（小文件，每次启动覆盖，无升级遗漏）
    shutil.copy2(os.path.join(BASE_DIR, "data", "essay_questions.json"),
                 os.path.join(web_dst, "m", "essay_questions.json"))
    # 辨析卡题库放入 web/cards（服务器端导入各账号个人库，按 id 幂等）
    cards_dst = os.path.join(web_dst, "cards")
    if os.path.exists(cards_dst):
        shutil.rmtree(cards_dst)
    shutil.copytree(os.path.join(BASE_DIR, "data", "cards"), cards_dst)
    # PWA 资源（功能 3.1）：Service Worker 需位于根作用域，故放 web/ 顶层
    for name in ("sw.js", "offline.html", "manifest-desktop.webmanifest"):
        shutil.copy2(os.path.join(BASE_DIR, "static", name),
                     os.path.join(web_dst, name))
    icons_dst = os.path.join(web_dst, "icons")
    if os.path.exists(icons_dst):
        shutil.rmtree(icons_dst)
    shutil.copytree(os.path.join(BASE_DIR, "static", "icons"), icons_dst)
    print("资产目录就绪:", assets)
    for f in sorted(os.listdir(assets)):
        fp = os.path.join(assets, f)
        print("  %s  %.1f MB" % (f, os.path.getsize(fp) / 1024 / 1024))


if __name__ == "__main__":
    if "--pack-update" in sys.argv:
        ver = 0
        for i, a in enumerate(sys.argv):
            if a == "--version" and i + 1 < len(sys.argv):
                ver = int(sys.argv[i + 1])
        try:
            pack_update(version=ver)
        except RuntimeError as e:
            print(e)
            sys.exit(1)
    else:
        build_all()
