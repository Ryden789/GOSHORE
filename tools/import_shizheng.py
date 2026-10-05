#!/usr/bin/env python3
"""
GOSHORE 半月时政增量导入脚本
只写入 shizheng + shizheng_quiz 表，不影响其他数据（做题记录/错题/打卡等）。

用法：
  python import_shizheng.py <资源包.md> [--db <数据库路径>]
  python import_shizheng.py "d:\\人文\\行测知识库\\时政\\2026年9月下半月时政资源包.md"
  python import_shizheng.py "2026年9月下半月时政资源包.md" --db "D:\\GOSHORE\\data\\goshor.db"
"""
import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

DEFAULT_DB = Path(r"D:\GOSHORE\data\goshor.db")


def parse_resource_pack(md_path: Path) -> dict:
    """解析 Markdown 资源包，返回 {period, title, content, quiz_items}"""
    text = md_path.read_text(encoding="utf-8")

    # 提取期次（从第一行标题或正文开头）
    period = ""
    m = re.search(r"^#\s*(\d{4}年\d{1,2}月[上下]半月)", text, re.M)
    if m:
        period = m.group(1)
    else:
        # 从文件名猜
        m = re.search(r"(\d{4}年\d{1,2}月[上下]半月)", md_path.name)
        if m:
            period = m.group(1)
    if not period:
        raise ValueError("无法从资源包中识别期次（格式：2026年9月下半月）")

    title = f"{period}时政常识"

    # 正文 = 从 "## 一、国内要闻" 到 "## 四、自测小测" 之前
    body_m = re.search(
        r"(##\s*一、国内要闻[\s\S]*?)(?=##\s*四、自测小测|\Z)", text
    )
    if not body_m:
        raise ValueError("资源包中未找到「## 一、国内要闻」章节")
    content_body = body_m.group(1).strip()

    # 自测题解析
    quiz_items = []
    quiz_m = re.search(r"##\s*四、自测小测[\s\S]*", text)
    if quiz_m:
        quiz_text = quiz_m.group(0)
        # 按题号分割
        q_blocks = re.split(r"\n\s*\*\*\d+\.\s*", quiz_text)
        for block in q_blocks[1:]:  # 跳过第一个空块
            block = block.strip()
            if not block:
                continue
            # 提取题干
            q_end = re.search(r"\*\*\s*\n", block)
            if not q_end:
                continue
            q = block[: q_end.start()].strip()
            # 提取选项和答案
            rest = block[q_end.end() :].strip()
            ans_m = re.search(r"答案[：:]\s*([A-D])", rest)
            if not ans_m:
                continue
            answer = ans_m.group(1)
            # 提取解析
            note_m = re.search(r"解析[：:]\s*(.+)", rest)
            note = note_m.group(1).strip() if note_m else ""
            # 提取选项（A. xxx 到 答案 之前）
            opt_text = rest[: ans_m.start()].strip()
            options = []
            for opt_line in opt_text.split("\n"):
                opt_line = opt_line.strip()
                if re.match(r"^[A-D][.、．]\s*", opt_line):
                    options.append(opt_line)
            if len(options) != 4:
                continue
            quiz_items.append(
                {"q": q, "options": options, "answer": answer, "note": note}
            )

    # 组装完整 content（期次标题 + 正文）
    content = f"# {period}时政常识\n\n{content_body}"

    return {
        "period": period,
        "title": title,
        "content": content,
        "quiz_items": quiz_items,
    }


def ensure_sz_quiz_col(conn: sqlite3.Connection) -> None:
    """shizheng 表补 quiz 列（旧库兼容）"""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(shizheng)")}
    if "quiz" not in cols:
        conn.execute("ALTER TABLE shizheng ADD COLUMN quiz TEXT DEFAULT ''")
        conn.commit()


def import_to_db(data: dict, db_path: Path) -> dict:
    """写入数据库，返回统计信息"""
    if not db_path.exists():
        raise FileNotFoundError(f"数据库不存在: {db_path}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")

    # 检查表结构
    tables = {
        r[0]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }
    if "shizheng" not in tables:
        conn.close()
        raise RuntimeError("数据库中没有 shizheng 表")

    ensure_sz_quiz_col(conn)

    # 写入时政内容
    import time

    conn.execute(
        "INSERT OR REPLACE INTO shizheng(period,title,content,created_at) VALUES(?,?,?,?)",
        (data["period"], data["title"], data["content"], time.time()),
    )

    # 写入自测题
    # 桌面端：写 shizheng.quiz 列；手机端（有 shizheng_quiz 表）：同时写两个地方
    quiz_json = ""
    if data["quiz_items"]:
        quiz_json = json.dumps(data["quiz_items"], ensure_ascii=False)
        # 始终写 shizheng.quiz 列（桌面端读取入口）
        conn.execute(
            "UPDATE shizheng SET quiz=? WHERE period=?",
            (quiz_json, data["period"]),
        )
        # 如果存在 shizheng_quiz 表（手机端个人库结构），也写一份
        if "shizheng_quiz" in tables:
            conn.execute(
                "INSERT OR REPLACE INTO shizheng_quiz(period,quiz) VALUES(?,?)",
                (data["period"], quiz_json),
            )

    conn.commit()

    # 验证
    row = conn.execute(
        "SELECT period, title, length(content) as clen, length(quiz) as qlen FROM shizheng WHERE period=?",
        (data["period"],),
    ).fetchone()
    conn.close()

    return {
        "period": row["period"],
        "title": row["title"],
        "content_len": row["clen"],
        "quiz_len": row["qlen"],
        "quiz_count": len(data["quiz_items"]),
    }


def main():
    parser = argparse.ArgumentParser(description="GOSHORE 半月时政增量导入")
    parser.add_argument("md_file", help="资源包 Markdown 文件路径")
    parser.add_argument(
        "--db",
        default=str(DEFAULT_DB),
        help=f"目标数据库路径（默认: {DEFAULT_DB}）",
    )
    args = parser.parse_args()

    md_path = Path(args.md_file)
    if not md_path.exists():
        print(f"[ERR] 文件不存在: {md_path}", file=sys.stderr)
        sys.exit(1)

    db_path = Path(args.db)

    print(f"[1/3] 解析资源包: {md_path.name}")
    try:
        data = parse_resource_pack(md_path)
    except Exception as e:
        print(f"[ERR] 解析失败: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"      期次: {data['period']}")
    print(f"      正文长度: {len(data['content'])} 字符")
    print(f"      自测题: {len(data['quiz_items'])} 道")

    print(f"[2/3] 写入数据库: {db_path}")
    try:
        result = import_to_db(data, db_path)
    except Exception as e:
        print(f"[ERR] 写入失败: {e}", file=sys.stderr)
        sys.exit(1)

    print(f"[3/3] 验证完成")
    print(f"      期次: {result['period']}")
    print(f"      标题: {result['title']}")
    print(f"      正文: {result['content_len']} 字符")
    print(f"      自测: {result['quiz_len']} 字符 ({result['quiz_count']} 题)")
    print(f"[OK] 增量导入完成，其他数据未受影响")


if __name__ == "__main__":
    main()
