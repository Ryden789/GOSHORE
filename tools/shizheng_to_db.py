#!/usr/bin/env python3
"""
把 scrape_people_shizheng.py 抓到的时政按半月期次整理：
- 2026年7月上半月/下半月、8月上半月/下半月、9月上半月/下半月、10月上半月
- 每期筛选高层动态中最具考点价值的条目（习近平/李强/政治局会议/国务院常务会/重大活动）
- 写入 shizheng 表（真实内容，标注信息来源）
"""
import json
import re
import sqlite3
import time
from pathlib import Path

DB = r"D:\GOSHORE\data\goshor.db"
SRC = r"D:\GOSHORE\data\shizheng_scraped.json"

# 高价值关键词（用于筛选考点条目）
KEYWORDS = [
    "习近平", "李强", "赵乐际", "王沪宁", "蔡奇", "丁薛祥", "李希",
    "中共中央政治局", "国务院常务", "国务院令",
    "重要讲话", "重要指示", "回信", "贺信", "致贺", "会谈", "会见",
    "国事访问", "调研", "考察", "座谈", "签署",
    "开幕", "致辞", "庆祝", "纪念", "烈士",
    "代表大会", "全会", "峰会", "论坛",
    "法律", "条例", "规定", "办法", "规划",
    "审计法", "中国人民银行法",
]

# 过滤冗余（领导活动报道重复的）
NOISE = [
    "回到北京", "抵达华盛顿", "机场", "离京", "圆满结束",
    "出席.*欢迎", "同.*茶叙", "同.*合影", "小范围交流",
]


def is_valuable(title: str) -> bool:
    if any(k in title for k in KEYWORDS):
        if not any(re.search(p, title) for p in NOISE):
            return True
    return False


def period_of(date: str) -> str:
    """date: '2026-09-24' -> '2026年9月下半月'"""
    y, m, d = date.split("-")
    half = "上半月" if int(d) <= 15 else "下半月"
    return f"{int(y)}年{int(m)}月{half}"


def main():
    data = json.loads(Path(SRC).read_text(encoding="utf-8"))

    # 按半月分组
    by_period = {}
    for month, items in data.items():
        for it in items:
            p = period_of(it["date"])
            by_period.setdefault(p, []).append(it)

    # 每期筛选 + 生成内容
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # 确保 quiz 列存在
    cols = {r[1] for r in conn.execute("PRAGMA table_info(shizheng)")}
    if "quiz" not in cols:
        conn.execute("ALTER TABLE shizheng ADD COLUMN quiz TEXT DEFAULT ''")

    n_saved = 0
    for period in sorted(by_period.keys()):
        items = by_period[period]
        # 筛选高价值
        valuable = [it for it in items if is_valuable(it["title"])]
        # 按日期排序（新→旧）
        valuable.sort(key=lambda x: x["date"], reverse=True)
        # 按标准化标题去重（同一新闻可能在不同日期重复发布，保留最新）
        seen_titles = set()
        deduped = []
        for it in valuable:
            # 标准化：去空白、去标点差异
            norm = re.sub(r"[\s　]+", "", it["title"])
            norm = re.sub(r"[：:，,。.!！?？]", "", norm)
            if norm in seen_titles:
                continue
            seen_titles.add(norm)
            deduped.append(it)
        # 取前 20 条
        top = deduped[:20]
        if not top:
            print(f"[skip] {period} 无高价值条目")
            continue

        # 生成 Markdown 内容
        lines = [
            f"# {period}时政常识（真实·人民网来源）",
            "",
            f"> 数据来源：人民网·高层动态频道 | 抓取时间：2026-10-05 | 条目数：{len(top)}",
            "",
            "## 一、国内要闻",
            "",
        ]
        for it in top:
            # 标题简化（去掉前导空白和多余修饰）
            title = re.sub(r"\s+", " ", it["title"]).strip()
            lines.append(f"- **{it['date'][5:]}** {title}")
        lines += [
            "",
            "## 二、备考提示",
            "",
            "- 以上均为2026年真实发生的高层动态，来自人民网官方发布。",
            "- 重点关注：习近平总书记重要活动/讲话、中央政治局会议、国务院常务会议、重大纪念日活动、法律法规颁布。",
            "- 外事活动（国事访问、会见）注意把握：访问国家、双方达成的重要共识、签署的合作文件。",
            "",
        ]
        content = "\n".join(lines)
        title = f"{period}时政常识"
        conn.execute(
            "INSERT OR REPLACE INTO shizheng(period,title,content,created_at) VALUES(?,?,?,?)",
            (period, title, content, time.time()),
        )
        n_saved += 1
        print(f"[OK] {period}: {len(top)} 条 (来自 {len(items)} 条原始)")

    conn.commit()
    conn.close()
    print(f"\n共入库 {n_saved} 期")


if __name__ == "__main__":
    main()
