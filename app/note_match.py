"""题目考点 → 速查考点的模糊匹配（L-3 错题回流用）。

题库的 `documents.kaodian` 形如「比重 / 基期比重计算」「定义判断 / 单定义-要件对照」，
申论的扣分点是自由文本；两者都要落到速查的考点标题上，才能显示「错 3 次」。

口径：
- 在候选考点的标题 + 正文 + 提示里，找与来源文本共有的 2—6 字片段；
- 优先「本体词」（增长、比重、定义等专业词），其次看片段长度；
- 最长片段不足 2 字则视为无法归属，返回 None（前端静默不显示）。
"""
from __future__ import annotations

SHORT_TERMS = {
    "增长", "基期", "现期", "比重", "倍数", "平均", "混合", "指数", "顺差", "逆差",
    "工程", "行程", "利润", "浓度", "排列", "组合", "容斥", "最值", "几何", "方程",
    "数列", "日期", "年龄", "周期", "图形", "定义", "类比", "逻辑", "削弱", "加强",
    "翻译", "真假", "语句", "标题", "细节", "病句", "归纳", "分析", "对策", "公文",
    "纪要", "简报", "调研", "方案", "公开信", "新闻", "标题", "立意", "论证", "分论",
}
STOP = {"计算", "比较", "问题", "分析", "方法", "公式", "选项", "材料", "数据",
        "题目", "题型", "特征", "常见", "介绍", "思路", "考点", "内容", "作答", "要点"}


def blob(point: dict) -> str:
    parts = [point["title"], point.get("body") or ""]
    parts += point.get("tips") or []
    for q in point.get("quizzes") or []:
        parts += [q.get("q", ""), q.get("explain", "")]
    return "\n".join(parts)


def segments(theme: str, text: str) -> str:
    cands = {theme[i:i + n] for n in range(2, 7)
             for i in range(len(theme) - n + 1) if theme[i:i + n] in text}
    if not cands:
        return ""
    return max(cands, key=lambda s: (2 * (s in SHORT_TERMS), 1 if s not in STOP else 0, len(s)))


def best_point(theme: str, points: list[dict], min_len: int = 3) -> dict | None:
    best, best_seg = None, ""
    for p in points:
        seg = segments(theme, blob(p))
        if len(seg) > len(best_seg) or (len(seg) == len(best_seg) and seg in SHORT_TERMS):
            best, best_seg = p, seg
    if best is None or len(best_seg) < min_len:
        return None
    return best
