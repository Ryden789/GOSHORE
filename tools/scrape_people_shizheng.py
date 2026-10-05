#!/usr/bin/env python3
"""
抓取人民网高层动态频道（http://politics.people.com.cn/GB/1024/index{N}.html）
分页1-20，提取标题+日期+URL，按月分组输出 JSON。
"""
import json
import re
import time
import urllib.request
from html.parser import HTMLParser

BASE = "http://politics.people.com.cn/GB/1024/"
# 第1页是 index.html，之后是 index2.html, index3.html ...
PAGES = ["index.html"] + [f"index{i}.html" for i in range(2, 21)]


class LinkParser(HTMLParser):
    """提取 <a href>...</a> 链接和紧邻的日期（人民网格式：标题后 *YYYY-MM-DD*）"""

    def __init__(self):
        super().__init__()
        self.items = []  # [(title, url)]
        self._cur_href = None
        self._cur_text = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            for k, v in attrs:
                if k == "href":
                    self._cur_href = v
                    self._cur_text = []

    def handle_data(self, data):
        if self._cur_href is not None:
            self._cur_text.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._cur_href is not None:
            text = "".join(self._cur_text).strip()
            href = self._cur_href
            # 只保留 /n1/YYYY/MMDD/ 形式的文章页
            m = re.search(r"/n1/(\d{4})/(\d{4})/", href)
            if m and text and len(text) >= 6:
                year, md = m.group(1), m.group(2)
                date = f"{year}-{md[:2]}-{md[2:]}"
                # 绝对化
                if href.startswith("http"):
                    url = href
                elif href.startswith("/"):
                    url = "http://politics.people.com.cn" + href
                else:
                    url = BASE + href
                self.items.append({"date": date, "title": text, "url": url})
            self._cur_href = None
            self._cur_text = []


def fetch(url: str) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0) goshore-sz"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
    # 人民网用 GB2312
    for enc in ("gb18030", "utf-8"):
        try:
            return raw.decode(enc)
        except Exception:
            continue
    return raw.decode("utf-8", "ignore")


def main():
    seen = set()
    all_items = []
    for pg in PAGES:
        url = BASE + pg
        print(f"fetch {url}")
        try:
            html = fetch(url)
        except Exception as e:
            print(f"  ERR: {e}")
            continue
        parser = LinkParser()
        try:
            parser.feed(html)
        except Exception as e:
            print(f"  parse err: {e}")
        n_new = 0
        for it in parser.items:
            key = (it["date"], it["title"])
            if key in seen:
                continue
            seen.add(key)
            all_items.append(it)
            n_new += 1
        print(f"  got {len(parser.items)} links, new {n_new}, total {len(all_items)}")
        # 翻到8月就够（C类备考关注近3月），但先抓全
        if all_items and all_items[-1]["date"] < "2026-04-01":
            print("  reached April, stop")
            break
        time.sleep(0.6)

    # 按月分组
    by_month = {}
    for it in all_items:
        m_key = it["date"][:7]  # 2026-09
        by_month.setdefault(m_key, []).append(it)

    out = "D:/GOSHORE/data/shizheng_scraped.json"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(by_month, f, ensure_ascii=False, indent=2)

    # 输出摘要
    for m in sorted(by_month.keys(), reverse=True):
        print(f"{m}: {len(by_month[m])} 条")
    print(f"已写入: {out}")


if __name__ == "__main__":
    main()
