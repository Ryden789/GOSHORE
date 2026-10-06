"""时政内容自动化流水线（功能 2.2）测试。

覆盖：抓取解析、期次归类、价值筛选、内容生成、AI 出题解析容错、
URL 增量去重、以及流水线 main() 的离线优雅退出与重复运行幂等。

**离线回归（建议3）**：`tests/fixtures/people_1024_sample.html` 是一份手工构造的
人民网列表页样例，`--html-file` 走它时全程不联网，CI 也能稳定回归「链接提取 /
噪声过滤 / 期次归档 / 去重」这些纯解析逻辑。

运行：python -m pytest tests/test_shizheng_pipeline.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from app import ai, db

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = Path(__file__).resolve().parent / "fixtures"
PEOPLE_HTML = FIXTURE_DIR / "people_1024_sample.html"

# 以文件路径加载 scripts/update_shizheng.py（scripts 非包）
_spec = importlib.util.spec_from_file_location(
    "update_shizheng", ROOT / "scripts" / "update_shizheng.py")
usz = importlib.util.module_from_spec(_spec)
sys.modules["update_shizheng"] = usz
_spec.loader.exec_module(usz)


FIXTURE_HTML = """
<html><body>
<a href="/n1/2026/0924/c1001-40012345.html">习近平主持召开中央政治局会议并发表重要讲话</a>
<a href="/n1/2026/0903/c1001-40011111.html">某地举办群众文化活动圆满结束</a>
<a href="http://politics.people.com.cn/n1/2026/0820/c1001-40000000.html">国务院常务会议部署经济工作</a>
<a href="/other/page.html">非文章页</a>
</body></html>
"""


# ---------------- 抓取与解析 ----------------

def test_scrape_parses_links(monkeypatch):
    monkeypatch.setattr(usz, "fetch", lambda url, timeout=20: FIXTURE_HTML)
    monkeypatch.setattr(usz.time, "sleep", lambda s: None)
    items = usz.scrape(1)
    assert items is not None
    urls = {i["url"] for i in items}
    assert any("40012345" in u for u in urls)
    # 非 /n1/ 链接被过滤
    assert all("/n1/" in u for u in urls)
    d = next(i for i in items if "40012345" in i["url"])
    assert d["date"] == "2026-09-24" and "政治局" in d["title"]


def test_scrape_returns_none_when_offline(monkeypatch):
    def boom(url, timeout=20):
        raise OSError("network down")
    monkeypatch.setattr(usz, "fetch", boom)
    monkeypatch.setattr(usz.time, "sleep", lambda s: None)
    assert usz.scrape(2) is None


def test_scrape_dedupes_same_title_date(monkeypatch):
    html = ('<a href="/n1/2026/0924/c1001-1.html">习近平出席重要活动并致辞</a>'
            '<a href="/n1/2026/0924/c1001-2.html">习近平出席重要活动并致辞</a>')
    monkeypatch.setattr(usz, "fetch", lambda url, timeout=20: html)
    monkeypatch.setattr(usz.time, "sleep", lambda s: None)
    assert len(usz.scrape(1)) == 1


# ---------------- 期次 / 筛选 / 内容 ----------------

def test_period_of():
    assert usz.period_of("2026-09-01") == "2026年9月上半月"
    assert usz.period_of("2026-09-15") == "2026年9月上半月"
    assert usz.period_of("2026-09-16") == "2026年9月下半月"
    assert usz.period_of("2026-12-31") == "2026年12月下半月"


def test_is_valuable_filters_noise_and_irrelevant():
    assert usz.is_valuable("习近平会见某国总统")
    assert usz.is_valuable("国务院常务会议部署经济工作")
    assert not usz.is_valuable("某地举办群众文化活动")      # 无关键词
    assert not usz.is_valuable("习近平圆满结束访问回到北京")  # 噪声词


def test_build_content_structure():
    items = [{"date": "2026-09-24", "title": "中央政治局会议召开", "url": "u1"}]
    md = usz.build_content("2026年9月下半月", items)
    assert md.startswith("# 2026年9月下半月时政常识")
    assert "09-24" in md and "中央政治局会议召开" in md
    assert "备考提示" in md


# ---------------- AI 出题解析 ----------------

def test_build_shizheng_quiz_prompt_contains_content():
    p = ai.build_shizheng_quiz_prompt("今天召开了重要会议")
    assert "今天召开了重要会议" in p and "JSON" in p


def test_parse_shizheng_quiz_json_valid():
    raw = json.dumps({"items": [
        {"q": "问题1", "options": ["A. 甲", "B. 乙", "C. 丙", "D. 丁"],
         "answer": "b", "note": "考点"},
        {"q": "问题2", "options": ["A. 甲", "B. 乙", "C. 丙", "D. 丁"],
         "answer": "C", "note": ""},
    ]}, ensure_ascii=False)
    items = ai.parse_shizheng_quiz_json(raw)
    assert len(items) == 2
    assert items[0]["answer"] == "B"          # 小写归一为大写


def test_parse_shizheng_quiz_json_fenced_and_noise():
    body = json.dumps({"items": [
        {"q": "q", "options": ["A. a", "B. b", "C. c", "D. d"],
         "answer": "A", "note": "n"}]}, ensure_ascii=False)
    assert ai.parse_shizheng_quiz_json(f"```json\n{body}\n```")
    assert ai.parse_shizheng_quiz_json("好的：\n" + body + "\n以上")


def test_parse_shizheng_quiz_json_rejects_bad_items():
    bad = json.dumps({"items": [
        {"q": "只有三个选项", "options": ["A", "B", "C"], "answer": "A"},
        {"q": "答案非法", "options": ["A", "B", "C", "D"], "answer": "E"},
        {"q": "", "options": ["A", "B", "C", "D"], "answer": "A"},
    ]}, ensure_ascii=False)
    assert ai.parse_shizheng_quiz_json(bad) is None
    assert ai.parse_shizheng_quiz_json("没有任何 JSON") is None
    assert ai.parse_shizheng_quiz_json("") is None


# ---------------- URL 增量去重 ----------------

def test_seen_urls_and_mark(temp_db):
    assert temp_db.seen_shizheng_urls() == set()
    n = temp_db.mark_shizheng_seen([
        ("http://a/1", "2026年9月上半月"),
        ("http://a/2", "2026年9月上半月")])
    assert n == 2
    assert temp_db.seen_shizheng_urls() == {"http://a/1", "http://a/2"}
    # 重复标记 → 新增 0
    assert temp_db.mark_shizheng_seen([("http://a/1", "x")]) == 0


# ---------------- 流水线 main() ----------------

def _make_db(path: Path) -> None:
    orig = db.DB_PATH
    db.DB_PATH = path
    db.IS_MOBILE = False          # 桌面模式，避免受 mobile_db 夹具的残留状态影响
    conn = db.connect()
    db.init_db(conn)
    conn.close()
    db.DB_PATH = orig


def test_main_exits_2_when_offline(tmp_path, monkeypatch):
    dbf = tmp_path / "t.db"
    _make_db(dbf)
    man = tmp_path / "man.json"
    monkeypatch.setattr(usz, "scrape", lambda pages, html_file=None: None)
    orig = db.DB_PATH
    try:
        code = usz.main(["--db", str(dbf), "--manifest", str(man),
                         "--out", str(tmp_path / "o.json")])
    finally:
        db.DB_PATH = orig
    assert code == 2
    m = json.loads(man.read_text(encoding="utf-8"))
    assert m["skipped"] == ["network_unavailable"]
    assert m["new_urls"] == 0


def test_main_full_run_and_idempotent(tmp_path, monkeypatch):
    """全链路 + 幂等。

    完整流程统一由下方「建议3」小节的 fixture 版本覆盖（不联网、断言更全），
    这里只保留一条最精简的假数据版本，用于确认不依赖 fixture 内容时主干仍成立。
    """
    dbf = tmp_path / "t.db"
    _make_db(dbf)
    items = [
        {"date": "2026-09-24", "title": "习近平主持召开中央政治局会议并发表重要讲话",
         "url": "http://p/1"},
        {"date": "2026-09-18", "title": "某地举办群众文化活动", "url": "http://p/3"},
    ]
    monkeypatch.setattr(usz, "scrape", lambda pages, html_file=None: items)
    man = tmp_path / "man.json"
    orig = db.DB_PATH
    try:
        assert usz.main(["--db", str(dbf), "--out", str(tmp_path / "o.json"),
                         "--manifest", str(man), "--no-ai"]) == 0
        m = json.loads(man.read_text(encoding="utf-8"))
        assert m["new_urls"] == 2
        assert m["updated_periods"] == ["2026年9月下半月"]
        saved = db.get_shizheng("2026年9月下半月")
        assert saved and "中央政治局会议" in saved["content"]
        assert "群众文化活动" not in saved["content"]     # 无关键词 → 被过滤
    finally:
        db.DB_PATH = orig


# ---------------- 建议3：离线 fixture（--html-file）全链路回归 ----------------

def _no_network(monkeypatch):
    """任何真实网络访问都应让用例失败——离线路径必须一次都不联网。"""
    def boom(url, timeout=20):
        raise AssertionError(f"离线路径不应发起网络请求：{url}")
    monkeypatch.setattr(usz, "fetch", boom)
    monkeypatch.setattr(usz.time, "sleep", lambda s: None)


def test_html_file_parses_without_network(monkeypatch):
    """本地 HTML 应解析出 9 条链接（2 条短文本 / 非 /n1/ 链接被忽略），且不联网。"""
    _no_network(monkeypatch)
    items = usz.scrape(1, html_file=str(PEOPLE_HTML))
    assert items is not None
    assert len(items) == 9
    # 文本 <6 字的链接被丢弃
    assert all(len(i["title"]) >= 6 for i in items)
    # 非 /n1/YYYY/MMDD/ 的链接被丢弃
    assert all("/n1/" in i["url"] for i in items)
    # 绝对 URL 原样保留、相对 URL 补全为人民网域名
    urls = {i["url"] for i in items}
    assert any(u.startswith("http://www.people.com.cn/GB/1024/n1/") for u in urls)
    assert any(u.startswith("http://politics.people.com.cn") for u in urls)
    # 日期归一为 YYYY-MM-DD
    assert {i["date"] for i in items} == {"2026-09-12", "2026-09-21",
                                          "2026-09-22", "2026-09-23", "2026-09-24"}


def test_html_file_noise_is_filtered(monkeypatch):
    """fixture 里 2 条噪声（抵达 / 回到北京）应被 is_valuable 剔除，剩 7 条。"""
    _no_network(monkeypatch)
    items = usz.scrape(1, html_file=str(PEOPLE_HTML))
    valuable = [i for i in items if usz.is_valuable(i["title"])]
    assert len(valuable) == 7
    noise = [i["title"] for i in items if not usz.is_valuable(i["title"])]
    assert len(noise) == 2
    assert any("抵达" in t for t in noise)
    assert any("回到北京" in t for t in noise)


def test_html_file_missing_returns_none(tmp_path, monkeypatch):
    """文件不存在 → 返回 None（等价于无网），不抛异常。"""
    _no_network(monkeypatch)
    assert usz.scrape(1, html_file=str(tmp_path / "nope.html")) is None


def test_main_offline_html_file_end_to_end(tmp_path, monkeypatch):
    """--html-file 全链路：退出码 0、两期入库、条目数与噪声过滤都正确、二次运行幂等。"""
    _no_network(monkeypatch)
    dbf = tmp_path / "t.db"
    _make_db(dbf)
    out = tmp_path / "scraped.json"
    man = tmp_path / "man.json"

    def run():
        return usz.main(["--db", str(dbf), "--out", str(out),
                         "--manifest", str(man), "--no-ai",
                         "--html-file", str(PEOPLE_HTML)])

    orig = db.DB_PATH
    try:
        assert run() == 0
        m = json.loads(man.read_text(encoding="utf-8"))
        assert m["scraped_total"] == 9
        assert m["new_urls"] == 9
        assert m["updated_periods"] == ["2026年9月下半月", "2026年9月上半月"]
        assert "ai_disabled" in m["skipped"]
        assert "network_unavailable" not in m["skipped"]
        # 按月归档文件
        assert "2026-09" in json.loads(out.read_text(encoding="utf-8"))

        lower = db.get_shizheng("2026年9月下半月")
        upper = db.get_shizheng("2026年9月上半月")
        assert lower and upper
        # 只保留高价值条目：下半月 5 条、上半月 2 条
        assert lower["content"].count("- **") == 5
        assert upper["content"].count("- **") == 2
        # 噪声不进正文
        assert "抵达" not in lower["content"]
        assert "回到北京" not in lower["content"]

        # 第二次运行：URL 全部已见 → 0 新增、0 更新（幂等）
        assert run() == 0
        m2 = json.loads(man.read_text(encoding="utf-8"))
        assert m2["new_urls"] == 0
        assert m2["updated_periods"] == []
        assert db.get_shizheng("2026年9月下半月")["content"] == lower["content"]
    finally:
        db.DB_PATH = orig


def test_main_offline_html_file_no_key_exits_3(tmp_path, monkeypatch):
    """离线 fixture + 未配置 Key → 入库照常完成，退出码 3（仅跳过 AI 出题）。"""
    _no_network(monkeypatch)
    dbf = tmp_path / "t.db"
    _make_db(dbf)
    man = tmp_path / "man.json"
    # 不真的调用 AI：直接声明「无 Key」且出题返回空
    monkeypatch.setattr(usz, "generate_quiz", lambda period, content: None)
    monkeypatch.setattr(usz, "_has_api_key", lambda: False)

    orig = db.DB_PATH
    try:
        code = usz.main(["--db", str(dbf), "--out", str(tmp_path / "o.json"),
                         "--manifest", str(man), "--html-file", str(PEOPLE_HTML)])
        assert code == 3
        m = json.loads(man.read_text(encoding="utf-8"))
        assert "no_api_key" in m["skipped"]
        # 抓取入库并未被 AI 缺 Key 影响
        assert m["updated_periods"] == ["2026年9月下半月", "2026年9月上半月"]
        assert db.get_shizheng("2026年9月下半月") is not None
    finally:
        db.DB_PATH = orig
