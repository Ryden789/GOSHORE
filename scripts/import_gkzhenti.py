"""批量导入 gkzhenti.cn 行测真题（通过站点官方公开 API 取试卷列表）。

策略：
- 每个地区取最新一套（year>=2021），可用 --limit 控制本批套数，可反复运行（状态文件续跑）
- 全模块抓取（常识/言语/数量/判断/资料/综合），过滤含图题
- 题干指纹去重：对库内已有题 + 本批次内跨卷重复（联考省份共享题）均跳过
- 答案由 DeepSeek 两次温度0盲选一致才采信，并发4限速
- 每套卷单独提交入库，中断不丢进度

用法：
  python scripts/import_gkzhenti.py --dry            # 只列出将抓的试卷
  python scripts/import_gkzhenti.py --limit 10       # 本批抓 10 套
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from app import importer  # noqa: E402
from app.config import load_settings  # noqa: E402
from import_guokao import ALL_MODULES, fetch_questions, HEADERS  # noqa: E402

API = "https://gwy.gkzhenti.cn/api/json?cls=行测&province={}"
REGIONS = ["国考", "浙江", "江苏", "广东", "山东", "四川", "湖北", "河南", "上海", "北京"]
MIN_YEAR = 2021
STATE_FILE = ROOT / "data" / "import_state.json"
CONCURRENCY = 4

# 地区名 -> 题库 region 字段
REGION_MAP = {"国考": "国家"}


def stem_key(stem: str) -> str:
    """题干指纹：去空白标点前40字。"""
    s = re.sub(r"[\s　，。、；：？！“”‘’（）《》【】\d.\-]+", "", stem or "")
    return s[:40]


def load_state() -> dict:
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {"done": [], "imported": 0}


def save_state(st: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")


def list_papers(region: str) -> list[dict]:
    r = httpx.get(API.format(region), headers=HEADERS, timeout=30, follow_redirects=True)
    return r.json()


def pick_papers(limit: int, done: set[str]) -> list[dict]:
    """每个地区取最新一套未导入的（2021+）。"""
    picks = []
    for region in REGIONS:
        try:
            arr = list_papers(region)
        except Exception as e:
            print(f"  {region} 列表获取失败: {e}")
            continue
        for p in arr:
            title = p.get("Title", "")
            url = p.get("No", "")
            m = re.search(r"(20\d{2})年", title)
            year = int(m.group(1)) if m else 0
            if year >= MIN_YEAR and url not in done and "申论" not in title and "面试" not in title:
                picks.append({
                    "region": REGION_MAP.get(region, region),
                    "year": str(year),
                    "exam": re.sub(r"（?网友回忆版）?", "", title),
                    "url": url, "title": title,
                })
                break
        time.sleep(0.5)
        if len(picks) >= limit:
            break
    return picks


def existing_stem_keys() -> set[str]:
    """库内已有真题的题干指纹。"""
    from app import db
    conn = db.connect()
    rows = conn.execute("SELECT data FROM documents WHERE kind='真题'").fetchall()
    conn.close()
    keys = set()
    for r in rows:
        try:
            stem = json.loads(r["data"]).get("stem", "")
        except Exception:
            continue
        k = stem_key(stem)
        if k:
            keys.add(k)
    return keys


async def judge_all(tasks: list[dict], s: dict) -> None:
    """并发双盲判定，结果写回 task['answer']。"""
    from import_guokao import ai_answer
    sem = asyncio.Semaphore(CONCURRENCY)
    done_n = [0]

    async def one(t):
        async with sem:
            t["answer"] = await ai_answer(t, client, s)
            done_n[0] += 1
            if done_n[0] % 50 == 0:
                print(f"  AI判定进度 {done_n[0]}/{len(tasks)}")

    async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as client:
        await asyncio.gather(*(one(t) for t in tasks))


async def main():
    args = sys.argv[1:]
    dry = "--dry" in args
    limit = 10
    if "--limit" in args:
        limit = int(args[args.index("--limit") + 1])

    st = load_state()
    done = set(st["done"])
    picks = pick_papers(limit, done)
    print(f"本批将抓取 {len(picks)} 套试卷：")
    for p in picks:
        print(f"  {p['region']} {p['year']} | {p['title'][:50]}")
    if dry or not picks:
        return

    s = load_settings()
    if not s["deepseek_api_key"]:
        print("未配置 DeepSeek API Key"); return

    print("\n加载库内题干指纹去重…")
    seen = existing_stem_keys()
    print(f"  库内已有 {len(seen)} 条题干指纹")

    total_saved = 0
    for pi, p in enumerate(picks, 1):
        print(f"\n[{pi}/{len(picks)}] {p['title'][:50]}")
        try:
            qs = fetch_questions(p["url"], ALL_MODULES)
        except Exception as e:
            print(f"  抓取失败: {e}"); continue
        fresh = []
        for q in qs:
            k = stem_key(q["stem"])
            if k and k not in seen:
                seen.add(k)
                fresh.append(q)
        print(f"  抓到 {len(qs)} 题，去重后新增 {len(fresh)} 题")
        if not fresh:
            st["done"].append(p["url"]); save_state(st); continue

        await judge_all(fresh, s)
        items = []
        for q in fresh:
            if q.get("answer"):
                items.append({
                    "stem": q["stem"], "options": q["options"], "answer": q["answer"],
                    "analysis": "（AI 双盲一致判定，人工复核请走「疑点」页）",
                    "module": q["module"],
                })
        dropped = len(fresh) - len(items)
        if items:
            result = importer.commit_items(items, {
                "module": "", "year": p["year"], "exam": p["exam"], "region": p["region"],
            })
            total_saved += result["saved"]
            print(f"  入库 {result['saved']} 题（双盲不一致丢弃 {dropped}）")
        else:
            print(f"  全部 {dropped} 题双盲不一致，未入库")
        st["done"].append(p["url"])
        st["imported"] = st.get("imported", 0) + len(items)
        save_state(st)
        time.sleep(1)

    print(f"\n本批完成：新增 {total_saved} 题；历史累计导入 {st['imported']} 题")


if __name__ == "__main__":
    asyncio.run(main())
