#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时政内容自动化流水线（功能 2.2）。

一条命令跑完：人民网抓取 → 按月归档 → 半月期次入库 → AI 生成自测题 → 写 manifest。

用法：
    python scripts/update_shizheng.py                 # 全流程
    python scripts/update_shizheng.py --no-ai         # 只抓取入库，不调用 AI
    python scripts/update_shizheng.py --periods 3     # 只更新最近 3 期
    python scripts/update_shizheng.py --pages 6       # 只抓前 6 页
    python scripts/update_shizheng.py --html-file x.html   # 离线：只解析本地 HTML，不联网

退出码：
    0  成功（包含「本次没有新增」）
    2  网络不可用（优雅退出，不打印堆栈）
    3  未配置 DeepSeek API Key（抓取入库已完成，仅跳过 AI 出题）
    1  其他异常

定时运行（Windows 计划任务，每周一 08:00）：
    schtasks /Create /TN "GOSHORE时政更新" /TR "python D:\\GOSHORE\\scripts\\update_shizheng.py" ^
             /SC WEEKLY /D MON /ST 08:00 /F
（或直接双击 tools/run_shizheng_weekly.bat）
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

BASE = "http://politics.people.com.cn/GB/1024/"

# 高价值关键词（筛选考点条目）
KEYWORDS = [
    "习近平", "李强", "赵乐际", "王沪宁", "蔡奇", "丁薛祥", "李希",
    "中共中央政治局", "国务院常务", "国务院令",
    "重要讲话", "重要指示", "回信", "贺信", "致贺", "会谈", "会见",
    "国事访问", "调研", "考察", "座谈", "签署",
    "开幕", "致辞", "庆祝", "纪念", "烈士",
    "代表大会", "全会", "峰会", "论坛",
    "法律", "条例", "规定", "办法", "规划",
]
NOISE = [
    "回到北京", "抵达", "机场", "离京", "圆满结束",
    "出席.*欢迎", "同.*茶叙", "同.*合影", "小范围交流",
]
MAX_PER_PERIOD = 20


class LinkParser(HTMLParser):
    """提取人民网高层动态列表页的文章链接（/n1/YYYY/MMDD/ 形式）。"""

    def __init__(self):
        super().__init__()
        self.items: list[dict] = []
        self._href = None
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href":
                    self._href = v
                    self._text = []

    def handle_data(self, data):
        if self._href is not None:
            self._text.append(data)

    def handle_endtag(self, tag):
        if tag != "a" or self._href is None:
            return
        text = "".join(self._text).strip()
        m = re.search(r"/n1/(\d{4})/(\d{4})/", self._href)
        if m and len(text) >= 6:
            year, md = m.group(1), m.group(2)
            href = self._href
            url = (href if href.startswith("http")
                   else ("http://politics.people.com.cn" + href if href.startswith("/")
                         else BASE + href))
            self.items.append({"date": f"{year}-{md[:2]}-{md[2:]}",
                               "title": text, "url": url})
        self._href = None
        self._text = []


def fetch(url: str, timeout: int = 20) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) goshore-sz"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("gb18030", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def _collect(parser: LinkParser) -> list[dict]:
    """把解析出的链接按 (date, title) 去重后返回。"""
    seen: set[tuple] = set()
    out: list[dict] = []
    for it in parser.items:
        key = (it["date"], it["title"])
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def scrape(pages: int, html_file: str | None = None) -> list[dict] | None:
    """抓取列表页 → 条目列表；网络不可用返回 None。

    html_file 非空时只读该本地文件（离线 / CI 回归解析逻辑用），不发任何网络请求。
    """
    if html_file:
        try:
            html = Path(html_file).read_text(encoding="utf-8", errors="ignore")
        except Exception as e:                      # noqa: BLE001
            print(f"  [warn] 读取本地 HTML 失败 {html_file}: {e}")
            return None
        parser = LinkParser()
        try:
            parser.feed(html)
        except Exception as e:                      # noqa: BLE001
            print(f"  [warn] 解析本地 HTML 失败 {html_file}: {e}")
            return None
        out = _collect(parser)
        print(f"  [local] {Path(html_file).name}: 链接 {len(parser.items)} 条，去重后 {len(out)}")
        return out

    page_names = ["index.html"] + [f"index{i}.html" for i in range(2, pages + 1)]
    out: list[dict] = []
    ok_pages = 0
    for pg in page_names:
        try:
            html = fetch(BASE + pg)
        except Exception as e:                      # noqa: BLE001
            print(f"  [warn] 抓取失败 {pg}: {e}")
            continue
        ok_pages += 1
        parser = LinkParser()
        try:
            parser.feed(html)
        except Exception as e:                      # noqa: BLE001
            print(f"  [warn] 解析失败 {pg}: {e}")
            continue
        merged = _collect(parser)
        known = {(it["date"], it["title"]) for it in out}
        out.extend(it for it in merged if (it["date"], it["title"]) not in known)
        print(f"  {pg}: 链接 {len(parser.items)} 条，累计 {len(out)}")
        time.sleep(0.4)
    if ok_pages == 0:
        return None                                  # 全页失败 → 视为无网
    return out


def period_of(date_str: str) -> str:
    """'2026-09-24' → '2026年9月下半月'。"""
    y, m, d = date_str.split("-")
    return f"{int(y)}年{int(m)}月{'上半月' if int(d) <= 15 else '下半月'}"


def is_valuable(title: str) -> bool:
    if any(k in title for k in KEYWORDS):
        return not any(re.search(p, title) for p in NOISE)
    return False


def build_content(period: str, items: list[dict]) -> str:
    """生成该期 Markdown 内容（真实来源标注）。"""
    lines = [f"# {period}时政常识（真实·人民网来源）", "",
             f"> 数据来源：人民网·高层动态频道 | 更新时间：{datetime.now():%Y-%m-%d %H:%M}",
             f"| 条目数：{len(items)}", "", "## 一、国内要闻", ""]
    for it in items:
        lines.append(f"- **{it['date'][5:]}** {re.sub(r'\\s+', ' ', it['title']).strip()}")
    lines += ["", "## 二、备考提示", "",
              "- 以上均为人民网官方发布的高层动态。",
              "- 重点关注：重要活动/讲话、中央政治局会议、国务院常务会议、重大纪念日、法律法规颁布。",
              "- 外事活动注意把握：访问国家、双方重要共识、签署的合作文件。", ""]
    return "\n".join(lines)


def generate_quiz(period: str, content: str) -> list[dict] | None:
    """调用 AI 生成自测题；未配置 Key 返回 None。"""
    import asyncio
    from app import ai
    prompt = ai.build_shizheng_quiz_prompt(content)
    try:
        raw = asyncio.run(ai.chat_once([{"role": "user", "content": prompt}],
                                       temperature=0.4))
    except RuntimeError as e:                        # 未配置 Key 等
        print(f"  [skip] AI 出题失败：{e}")
        return None
    except Exception as e:                           # noqa: BLE001
        print(f"  [warn] AI 出题异常：{e}")
        return None
    return ai.parse_shizheng_quiz_json(raw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="时政内容自动化流水线")
    ap.add_argument("--db", default=str(ROOT / "data" / "goshor.db"))
    ap.add_argument("--out", default=str(ROOT / "data" / "shizheng_scraped.json"))
    ap.add_argument("--manifest", default=str(ROOT / "data" / "shizheng_manifest.json"))
    ap.add_argument("--periods", type=int, default=6, help="最多更新最近 N 期")
    ap.add_argument("--pages", type=int, default=12, help="抓取页数")
    ap.add_argument("--no-ai", action="store_true", help="跳过 AI 出题")
    ap.add_argument("--html-file", default=None,
                    help="从本地 HTML 读取列表页，不联网（离线 / 测试用）")
    args = ap.parse_args(argv)

    # 让 app.db 指向目标库
    from app import db
    db.DB_PATH = Path(args.db)
    if not db.DB_PATH.exists():
        print(f"[error] 数据库不存在：{db.DB_PATH}")
        return 1

    manifest: dict = {"run_at": datetime.now().isoformat(timespec="seconds"),
                      "db": str(db.DB_PATH), "scraped_total": 0, "new_urls": 0,
                      "updated_periods": [], "quizzes": [], "skipped": []}

    print("[1/4] 抓取人民网高层动态…")
    items = scrape(max(1, args.pages), html_file=args.html_file)
    if items is None:
        print("[exit] 网络不可用，已优雅退出（未做任何修改）")
        manifest["skipped"].append("network_unavailable")
        _write_manifest(args.manifest, manifest)
        return 2
    manifest["scraped_total"] = len(items)
    print(f"  共抓取 {len(items)} 条")

    # 按月归档
    by_month: dict[str, list[dict]] = {}
    for it in items:
        by_month.setdefault(it["date"][:7], []).append(it)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(by_month, ensure_ascii=False, indent=2),
                              encoding="utf-8")
    print(f"[2/4] 已按月归档 → {args.out}（{len(by_month)} 个月）")

    # 增量：与 shizheng_seen 对比
    seen = db.seen_shizheng_urls()
    new_items = [it for it in items if it["url"] not in seen]
    manifest["new_urls"] = len(new_items)
    print(f"  新增 URL {len(new_items)} 条（历史已见 {len(seen)} 条）")

    # 按半月期次聚合（用全量快照重建内容，保证每期完整）
    by_period: dict[str, list[dict]] = {}
    for it in items:
        by_period.setdefault(period_of(it["date"]), []).append(it)
    new_periods = {period_of(it["date"]) for it in new_items}
    periods = sorted(by_period.keys(), reverse=True)[:max(1, args.periods)]

    print("[3/4] 入库高价值条目…")
    n_content = 0
    for period in periods:
        plist = [it for it in by_period[period] if is_valuable(it["title"])]
        plist.sort(key=lambda x: x["date"], reverse=True)
        dedup: list[dict] = []
        titles: set[str] = set()
        for it in plist:
            norm = re.sub(r"[\s　：:，,。.!！?？]", "", it["title"])
            if norm in titles:
                continue
            titles.add(norm)
            dedup.append(it)
        dedup = dedup[:MAX_PER_PERIOD]
        if not dedup:
            print(f"  [skip] {period}：无高价值条目")
            continue
        exists = db.get_shizheng(period) is not None
        if exists and period not in new_periods:
            print(f"  [skip] {period}：无新增，保持原内容")
            continue
        content = build_content(period, dedup)
        db.save_shizheng(period, f"{period}时政常识", content)
        manifest["updated_periods"].append(period)
        n_content += 1
        print(f"  [ok] {period}：{len(dedup)} 条")

    # AI 出题
    if args.no_ai:
        print("[4/4] --no-ai：跳过 AI 出题")
        manifest["skipped"].append("ai_disabled")
        code = 0
    else:
        print("[4/4] AI 生成自测题…")
        code = 0
        for period in manifest["updated_periods"]:
            if db.get_shizheng_quiz(period):
                print(f"  [skip] {period}：已有自测题")
                continue
            item = db.get_shizheng(period)
            qs = generate_quiz(period, item["content"] if item else "")
            if not qs:
                if not _has_api_key():
                    manifest["skipped"].append("no_api_key")
                    code = 3
                continue
            db.save_shizheng_quiz(period, json.dumps(qs, ensure_ascii=False))
            manifest["quizzes"].append({"period": period, "n": len(qs)})
            print(f"  [ok] {period}：{len(qs)} 题")

    # 记录已见 URL
    n_marked = db.mark_shizheng_seen([(it["url"], period_of(it["date"])) for it in items])
    print(f"  去重表新增 {n_marked} 条")

    _write_manifest(args.manifest, manifest)
    print(f"完成：更新 {n_content} 期，新增自测 {len(manifest['quizzes'])} 期 → {args.manifest}")
    return code


def _has_api_key() -> bool:
    try:
        from app.config import load_settings
        return bool(load_settings().get("deepseek_api_key"))
    except Exception:                                # noqa: BLE001
        return False


def _write_manifest(path: str, manifest: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                          encoding="utf-8")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n[exit] 已中断")
        sys.exit(1)
    except Exception as e:                           # noqa: BLE001
        print(f"[error] {e}")
        sys.exit(1)
