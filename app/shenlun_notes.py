"""申论速查手册知识库：五大题型的方法、框架与答题提示。

纯静态数据，桌面端 /api/sl/notes 与移动端内置服务器共用。
与 app/xingce_notes.py 同构（groups → sections → points），前端复用同一套渲染，
只是去掉选择题（申论是主观题，不造客观选项）。

内容来源：`知识点综合/申论/` 下 5 份讲义的整理稿（见 scripts/pdf_notes_extract_shenlun.py），
按「答题总纲 / 归纳概括 / 综合分析 / 提出对策 / 贯彻执行 / 文章写作」六个模块人工重写，
不直接照搬原书表述。

结构：六个模块的正文分别落在 `app/shenlun_content_<key>.py`，本文件只做合并与标题强校验，
与行测的 `xingce_content_*.py` 同一套做法（E-2）。

撰写约定：
- body 用 "\\n" 分段，列表统一用 "- "，加粗用 **...**（双端 md() 都支持）；
- 不出现 "1. " 这类有序列表标记，也不出现 "###" 三级标题；
- 每个考点 body ≥ 150 字、≤ 500 字，tips 2—4 条，写最容易被扣分的地方；
- tips 与 tip_kinds 等长，tip_kinds ∈ {易错, 采分, 时间}（C-4）。
"""

from app import shenlun_content_zonggang as _zonggang  # noqa: E402
from app import shenlun_content_gaikuo as _gaikuo  # noqa: E402
from app import shenlun_content_fenxi as _fenxi  # noqa: E402
from app import shenlun_content_duice as _duice  # noqa: E402
from app import shenlun_content_guanche as _guanche  # noqa: E402
from app import shenlun_content_zuowen as _zuowen  # noqa: E402

_GROUPS = [
    _zonggang.GROUP,
    _gaikuo.GROUP,
    _fenxi.GROUP,
    _duice.GROUP,
    _guanche.GROUP,
    _zuowen.GROUP,
]

NOTES = {
    "version": 1,
    "groups": _GROUPS,
}

# ---------------------------------------------------------------- 真题范例（C-3）
# 题干摘要 + 参考答案要点，键为「模块 key|考点标题」，标题对不上直接报错，
# 避免范例静默挂到别的考点上。
from app.shenlun_examples import EXAMPLES as _EXAMPLES, NOTE as _EXAMPLE_NOTE  # noqa: E402

_BY_KEY = {f"{_g['key']}|{_p['title']}": _p for _g in _GROUPS for _p in _g["points"]}
_orphans = [k for k in _EXAMPLES if k not in _BY_KEY]
if _orphans:
    raise KeyError(f"申论范例的考点键不存在：{_orphans}")
for _k, _ex in _EXAMPLES.items():
    _BY_KEY[_k]["examples"] = _ex
NOTES["example_note"] = _EXAMPLE_NOTE

# 结构校验：key 唯一、模块数固定为 6、顺序与阅读顺序一致
_EXPECT = ["zonggang", "gaikuo", "fenxi", "duice", "guanche", "zuowen"]
if [g["key"] for g in _GROUPS] != _EXPECT:
    raise KeyError(f"申论模块顺序或 key 不符：{[g['key'] for g in _GROUPS]}")


# ---------------------------------------------------------------- 提示分型（C-4）
from app.note_tip_kinds import TIP_KINDS as _TIP_KINDS  # noqa: E402

for _g in _GROUPS:
    for _p in _g["points"]:
        _kinds = _TIP_KINDS["sl"].get(f"{_g['key']}|{_p['title']}")
        if not _kinds:
            continue
        if len(_kinds) != len(_p.get("tips") or []):
            raise KeyError(f"{_g['name']} · {_p['title']} 的 tip_kinds 与 tips 长度不一致")
        _p["tip_kinds"] = list(_kinds)
