"""申论真题采分点库（L2）：本地真题索引 + 子项级采分点，命中后作为「参考答案」注入 prompt。

为什么需要它：DeepSeek 只看题目和材料时，每次自拟的得分点名称和分值都不一样，
同一篇作答连批三次能漂 3–5 分（见设计文档 P1/P2）。命中真题库时，把固定的
子项清单和分值交给模型，让它只做「逐条核对——踩到/部分/没踩」，分数就稳了。

数据目录（默认 `data/real_exams/`，可用 `GOSHORE_EXAM_DIR` 覆盖）：
    INDEX.json      索引：{version, items:[{exam_id, exam_full_name, sheet_type, keywords}]}
    <exam_id>.json  单套卷：题 + 子项级采分点

设计要点（与设计文档 4.1 一致）：
  * 单套卷一个文件，**子项分值之和必须精确等于该题满分**，差 0.5 分都拒载——
    分值不闭合的采分点表会直接把分数算歪，比没有更糟；
  * `source` 必须写明出处且**禁止**写「官方标准答案」（手上是机构拆解版，
    写成官方即造假）；
  * `evidence` 写材料出处；只到段落/主题级也可接受，但**不允许编造**「第 X 段第 Y 句」；
  * 任一硬校验不通过 → 抛 `ExamBankError` 拒载，不静默跳过（静默跳过会让
    「命中真题库」时分数看起来更稳，实际用的是残缺清单）。
"""
from __future__ import annotations

import difflib
import json
import os
import re
from functools import lru_cache
from pathlib import Path

from . import config
from .essay_rubric import RUBRICS

# 采分点最多收多少条：与 essay_rubric.parse_grade_json 的 points 上限保持一致，
# 免得题库里有 40 条子项、模型却只肯输出 30 条，最后对不上账。
MAX_POINTS = 30
# 索引命中阈值：题面/材料里出现 >=3 个主题关键词才算高置信（设计文档 4.1）
MIN_CONFIDENCE_HITS = 3
# 题面相似度下限：关键词命中只能说明「是这一套卷」，还要能认出「是第几题」。
# 认不出题号时宁可返回 None —— 用错题的子项清单比不给清单更误导。
QUESTION_MATCH_MIN = 0.45
# 素材库字段里不允许出现的表述（防止把机构拆解版写成官方口径）
_BANNED_SOURCE_HINTS = ("官方标准答案", "官方答案", "标准答案", "官方评分标准")
_PLACEHOLDER_HINTS = ("待补充", "todo", "tbd", "???")
# 分值比较容差：全部用 round(, 2) 后严格比较，这里只是浮点求和后的对齐精度
_SCORE_EPS = 1e-6


class ExamBankError(RuntimeError):
    """真题库数据不合规。加载期抛出，调用方应视为「该卷不可用」。"""


# ---------------------------------------------------------------- 路径与缓存

def exams_dir() -> Path:
    """真题库目录。

    优先级：`GOSHORE_EXAM_DIR` 环境变量（测试/便携部署）→ 用户数据目录
    `DATA_DIR/real_exams` → 打包内置副本 `BUNDLE_DIR/data/real_exams`。

    为什么要有内置副本：桌面版发布的是「一个 exe + 可选的 data/ 文件夹」，
    新装用户根本没有 `data/real_exams`，只认 DATA_DIR 会让真题库功能在冻结版里
    永远空转（只能退化成 AI 自拟）。内置副本是只读的，用户想补自己的卷子就在
    `DATA_DIR/real_exams` 放一份带 INDEX.json 的目录，它优先于内置的那份。

    每次调用都重新取 `config.*`，这样单测 monkeypatch 配置就能换目录。
    """
    raw = (os.environ.get("GOSHORE_EXAM_DIR") or "").strip()
    if raw:
        return Path(raw).expanduser()
    user = Path(config.DATA_DIR) / "real_exams"
    if (user / "INDEX.json").exists():
        return user
    bundled = Path(config.BUNDLE_DIR) / "data" / "real_exams"
    if (bundled / "INDEX.json").exists():
        return bundled
    # 两边都没有：返回用户目录，让上层报「缺少真题索引文件：…」时指向可写位置
    return user


@lru_cache(maxsize=8)
def _load_index_from(dir_str: str) -> dict:
    path = Path(dir_str) / "INDEX.json"
    if not path.exists():
        raise ExamBankError(f"缺少真题索引文件：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExamBankError(f"真题索引不是合法 JSON：{path}（{exc}）") from exc
    if not isinstance(data, dict):
        raise ExamBankError(f"真题索引顶层必须是对象：{path}")
    items = data.get("items")
    if not isinstance(items, list) or not items:
        raise ExamBankError(f"真题索引 items 必须是非空数组：{path}")
    seen: set[str] = set()
    for i, item in enumerate(items, 1):
        if not isinstance(item, dict):
            raise ExamBankError(f"真题索引第 {i} 项不是对象：{path}")
        exam_id = str(item.get("exam_id") or "").strip()
        if not exam_id:
            raise ExamBankError(f"真题索引第 {i} 项缺 exam_id：{path}")
        if exam_id in seen:
            raise ExamBankError(f"真题索引 exam_id 重复：{exam_id}")
        seen.add(exam_id)
        if not str(item.get("exam_full_name") or "").strip():
            raise ExamBankError(f"真题索引 {exam_id} 缺 exam_full_name")
        kws = item.get("keywords")
        if not isinstance(kws, list) or not [k for k in kws if str(k).strip()]:
            raise ExamBankError(f"真题索引 {exam_id} 缺 keywords")
    return data


def load_index() -> dict:
    """读 INDEX.json（按目录缓存）。返回 `{version, items:[...]}`。"""
    return _load_index_from(str(exams_dir()))


@lru_cache(maxsize=16)
def _load_exam_from(path_str: str, index_ids: tuple[str, ...]) -> dict:
    path = Path(path_str)
    if not path.exists():
        raise ExamBankError(f"缺少真题文件：{path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExamBankError(f"真题文件不是合法 JSON：{path}（{exc}）") from exc
    return _validate_exam(data, str(path), index_ids)


def _num(value) -> float | None:
    """把分值解析成 float；bool / 非数字 / 负数 / 零 → None。"""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        v = float(value)
    elif isinstance(value, str):
        try:
            v = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    if v <= 0 or v != v:  # NaN 也拒
        return None
    return v


def _text_field(value) -> str:
    return str(value or "").strip()


def _check_placeholder(text: str, where: str) -> str:
    low = text.lower()
    if not text or any(h in low for h in _PLACEHOLDER_HINTS):
        raise ExamBankError(f"{where} 为空或仍是占位符（{text!r}）")
    return text


def _validate_exam(data: dict, where: str, index_ids: tuple[str, ...]) -> dict:
    """硬校验一套卷；不合规直接抛错，绝不「尽量用」。"""
    if not isinstance(data, dict):
        raise ExamBankError(f"{where} 顶层必须是对象")
    exam_id = _text_field(data.get("exam_id"))
    if not exam_id:
        raise ExamBankError(f"{where} 缺 exam_id")
    if index_ids and exam_id not in index_ids:
        raise ExamBankError(f"{where} 的 exam_id={exam_id} 未登记在 INDEX.json")
    full_name = _text_field(data.get("exam_full_name"))
    if not full_name:
        raise ExamBankError(f"{exam_id} 缺 exam_full_name")
    if not _text_field(data.get("overall_theme")):
        raise ExamBankError(f"{exam_id} 缺 overall_theme")
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ExamBankError(f"{exam_id} 的 questions 必须是非空数组")
    seen_q: set[int] = set()
    for q in questions:
        if not isinstance(q, dict):
            raise ExamBankError(f"{exam_id} 有题目不是对象")
        q_no = q.get("q_no")
        if not isinstance(q_no, int) or isinstance(q_no, bool) or q_no <= 0:
            raise ExamBankError(f"{exam_id} 题目 q_no 必须是正整数（{q_no!r}）")
        if q_no in seen_q:
            raise ExamBankError(f"{exam_id} 题号重复：{q_no}")
        seen_q.add(q_no)
        tag = f"{exam_id} 第{q_no}题"
        category = _text_field(q.get("category"))
        if category not in RUBRICS:
            raise ExamBankError(f"{tag} 的 category={category!r} 不在 RUBRICS（{sorted(RUBRICS)}）")
        full_score = _num(q.get("full_score"))
        if full_score is None:
            raise ExamBankError(f"{tag} 的 full_score 必须是正数（{q.get('full_score')!r}）")
        _check_placeholder(_text_field(q.get("question_text")), f"{tag} 的 question_text")
        points = q.get("points")
        if not isinstance(points, list) or not points:
            raise ExamBankError(f"{tag} 的 points 必须是非空数组")
        if len(points) > MAX_POINTS:
            raise ExamBankError(f"{tag} 的 points 超过 {MAX_POINTS} 条")
        total = 0.0
        for i, p in enumerate(points, 1):
            if not isinstance(p, dict):
                raise ExamBankError(f"{tag} 第 {i} 个子项不是对象")
            ptag = f"{tag} 第 {i} 个子项"
            _check_placeholder(_text_field(p.get("name")), f"{ptag} 的 name")
            pf = _num(p.get("full"))
            if pf is None:
                raise ExamBankError(f"{ptag} 的 full 必须是正数（{p.get('full')!r}）")
            total += pf
            _check_placeholder(_text_field(p.get("evidence")), f"{ptag} 的 evidence")
            source = _check_placeholder(_text_field(p.get("source")), f"{ptag} 的 source")
            if any(h in source for h in _BANNED_SOURCE_HINTS):
                raise ExamBankError(f"{ptag} 的 source 不得自称官方答案（{source!r}）")
        if abs(total - full_score) > _SCORE_EPS:
            raise ExamBankError(
                f"{tag} 子项分值之和 {total:g} ≠ 满分 {full_score:g}（必须精确相等）")
    return data


def _exam_index_map() -> dict[str, dict]:
    return {str(it["exam_id"]): it for it in load_index().get("items", [])}


@lru_cache(maxsize=8)
def _all_exams_from(dir_str: str, index_ids: tuple[str, ...]) -> dict[str, dict]:
    """按索引逐个加载卷文件；索引里有但文件缺失的卷跳过（视为未入库）。"""
    out: dict[str, dict] = {}
    for exam_id in index_ids:
        path = Path(dir_str) / f"{exam_id}.json"
        if not path.exists():
            continue
        out[exam_id] = _load_exam_from(str(path), index_ids)
    return out


def all_exams() -> dict[str, dict]:
    """全部可用的卷（exam_id → 卷数据）。"""
    ids = tuple(str(it["exam_id"]) for it in load_index().get("items", []))
    return dict(_all_exams_from(str(exams_dir()), ids))


def _exam(exam_id: str) -> dict | None:
    return all_exams().get(exam_id)


def clear_cache() -> None:
    """清缓存。测试改数据文件后调用；生产无需要。"""
    for fn in (_load_index_from, _load_exam_from, _all_exams_from):
        fn.cache_clear()


# ---------------------------------------------------------------- 查询

_WS_RE = re.compile(r"\s+")


def _norm(text: str) -> str:
    """匹配用的归一化：去空白、转小写。保留标点（题面相似度依赖标点位置）。"""
    return _WS_RE.sub("", str(text or "")).lower()


def _question_head(text: str) -> str:
    """题面首行（题干本体）。用户手打时往往只抄题干、不抄「要求」。"""
    return str(text or "").split("\n")[0]


def _similarity(user_q: str, stored_q: str) -> float:
    a = _norm(user_q)
    if not a:
        return 0.0
    b = _norm(stored_q)
    if not b:
        return 0.0
    ratio = difflib.SequenceMatcher(None, a, b).ratio()
    head = _norm(_question_head(stored_q))
    if head and head != b:
        ratio = max(ratio, difflib.SequenceMatcher(None, a, head).ratio())
    return ratio


def _best_question(exam: dict, question: str, category: str = "") -> tuple[dict, float] | None:
    best: tuple[dict, float] | None = None
    for q in exam.get("questions") or []:
        if category and _text_field(q.get("category")) != category:
            continue
        ratio = _similarity(question, q.get("question_text") or "")
        if best is None or ratio > best[1]:
            best = (q, ratio)
    if best is None or best[1] < QUESTION_MATCH_MIN:
        return None
    return best


def match(question: str, material: str = "", category: str = "") -> dict | None:
    """按关键词命中 + 题面相似度，判断用户这道题是否来自真题库。

    返回 `{exam_id, exam_full_name, q_no, category, full_score, confidence,
    matched_keywords, question_similarity}`；未命中返回 None。

    `confidence`：命中的主题关键词 >=3 个为 "high"，1–2 个为 "medium"。
    调用方（main.py）**只在 high 时**采用题库采分点，medium 仍走 AI 自拟。

    传了 `category` 时只在同类题里挑（用户选错题型就不会拿到别题的子项清单）。
    关键词命中只证明「是这一套卷」，题面相似度才证明「是第几题」——两者都过
    才算命中，否则返回 None：用错题的子项清单比不给清单更误导。
    """
    q = str(question or "").strip()
    if not q:
        return None
    haystack = _norm(q + "\n" + str(material or "")[:2000])
    scored: list[tuple[int, dict, list[str]]] = []
    for item in load_index().get("items", []):
        hits = [str(k) for k in (item.get("keywords") or [])
                if str(k).strip() and _norm(str(k)) in haystack]
        if hits:
            scored.append((len(hits), item, hits))
    if not scored:
        return None
    scored.sort(key=lambda t: -t[0])
    hit_count, item, hits = scored[0]
    exam = _exam(str(item["exam_id"]))
    if not exam:
        return None
    picked = _best_question(exam, q, category)
    if not picked:
        return None
    question_data, ratio = picked
    return {
        "exam_id": str(exam["exam_id"]),
        "exam_full_name": str(exam.get("exam_full_name") or item.get("exam_full_name") or ""),
        "q_no": int(question_data["q_no"]),
        "category": _text_field(question_data.get("category")),
        "full_score": float(question_data.get("full_score") or 0),
        "confidence": "high" if hit_count >= MIN_CONFIDENCE_HITS else "medium",
        "matched_keywords": hits,
        "question_similarity": round(ratio, 3),
    }


def get_question(exam_id: str, q_no: int | None = None) -> dict | None:
    """取一道题；`q_no=None` 时返回整卷（含 questions 列表）。"""
    exam = _exam(str(exam_id or "").strip())
    if not exam:
        return None
    if q_no is None:
        return exam
    for q in exam.get("questions") or []:
        if int(q.get("q_no") or 0) == int(q_no):
            return q
    return None


def score_text(value: float) -> str:
    """分值显示：3.0 → "3"，1.5 → "1.5"。"""
    v = float(value)
    return str(int(v)) if abs(v - int(v)) < _SCORE_EPS else f"{v:g}"


def build_reference(exam_id: str, q_no: int | None = None) -> str:
    """把子项采分点渲染成注入 prompt 的「参考答案 / 赋分标准」文本。

    格式与设计文档一致：`1. {name} —— {full}分（材料出处：{evidence}）`。
    卷或题不存在、或没有可用子项时返回空串（调用方据此回落到 AI 自拟）。
    """
    q = get_question(exam_id, q_no)
    if not isinstance(q, dict) or "points" not in q:
        return ""
    points = [p for p in (q.get("points") or []) if isinstance(p, dict)][:MAX_POINTS]
    if not points:
        return ""
    lines = []
    for i, p in enumerate(points, 1):
        name = _text_field(p.get("name"))
        full = _num(p.get("full")) or 0.0
        evidence = _text_field(p.get("evidence"))
        line = f"{i}. {name} —— {score_text(full)}分"
        if evidence:
            line += f"（材料出处：{evidence}）"
        lines.append(line)
    return "\n".join(lines)
