# -*- coding: utf-8 -*-
"""折纸盒「拍照录题」：多模态 AI 识别平面展开图截图，输出结构化网格 JSON。

只识别平面展开图（6 格），立体透视图只能看到 3 个面、信息不全，前端无法还原，
故 prompt 明确要求立体图/无关图返回 is_net=false。
"""
import json
import math
import re

import httpx

PROMPT = """你在帮考生还原"折纸盒"（正方体平面展开图）题目。图片中应有一个由6个正方形格子组成的平面展开图（题目可能同时给出立体透视图选项，那些不是展开图，忽略它们）。

只输出一个紧凑 JSON（不要 markdown 代码块、不要解释）：
{"is_net": true 或 false, "cells": [...], "note": "简短说明"}

识别步骤（严格按顺序执行）：
1. 先定位平面展开图，数出它占几行几列，看清每个格子的边界线，再逐格判定内容。不要凭整体印象猜。
2. 坐标：最顶部格子所在行为 r=0，最左侧列为 c=0，向右 c 递增、向下 r 递增。空格子不要输出，cells 必须恰好 6 个。
3. 每个格子必须输出 {"r":行,"c":列,"bbox":[左,上,右,下],"kind":"...","dir":"...","label":"..."}：
   - bbox 为该格子在整张输入图片中的边界，坐标归一化到 0~1，原点在图片左上角。必须包含整个正方形面（含底纹），不要只框图案，也不要包含邻面或题干。左<右、上<下。六个面（包括空白面）都必须提供 bbox。
   - 按图片原方向给出边界。程序会裁剪原图作为面纹理，所以不需要用预设图形重画复杂图案。
   - kind 只能取：arrow（箭头）、triangle（三角）、cross（十字）、slash（斜线）、circle（圆点）、letter（文字）、image（数字、点数、阴影、组合图形及其他任意图案）、none（确实空白）。kind 仅作辅助描述，不影响原图保留。
   - dir 是图案朝向，以【原图方向】为准：
     · arrow/triangle 必填，是【尖部】指向（up/down/left/right）。务必分清头部和尾部：箭头尖端是三角形的锐角端，不是箭杆末端。
     · slash 必填：tlbr（左上到右下，形如 ＼）或 trbl（右上到左下，形如 ／）。
     · 无方向图案（cross/circle/none）dir 填空字符串。
   - label 仅 kind=letter 时填该字符，其余留空。
4. 阴影、数字点数、复杂花纹、组合图案必须保留，标为 image，绝不能当成空白。
5. 输出前自检：①cells 恰好 6 个；②6 格边对边连通；③每个 bbox 与对应格子位置一致。仅支持正视或接近正视的平面展开图；若图中只有立体透视图、严重倾斜拍摄或无关内容，is_net=false，cells 留空数组并在 note 中说明。"""


def _extract_json(text: str) -> dict:
    i, j = text.find("{"), text.rfind("}")
    if i < 0 or j <= i:
        raise ValueError("AI 未返回有效结果，请重试或换一张更清晰的截图")
    return json.loads(text[i:j + 1])


def _clean(d: dict) -> dict:
    if not isinstance(d, dict) or not d.get("is_net"):
        return {"is_net": False, "cells": [], "note": str(d.get("note", "")) if isinstance(d, dict) else ""}
    ok_kind = {"arrow", "triangle", "cross", "slash", "circle", "letter", "image", "none"}
    ok_dir = {"up", "down", "left", "right", "tlbr", "trbl", ""}
    cells, seen = [], set()
    for cl in d.get("cells") or []:
        if not isinstance(cl, dict):
            continue
        try:
            if any(isinstance(cl[k], bool) or not isinstance(cl[k], (int, float)) or not math.isfinite(cl[k]) or int(cl[k]) != cl[k] for k in ("r", "c")):
                continue
            r, c = int(cl["r"]), int(cl["c"])
        except (KeyError, TypeError, ValueError):
            continue
        if (r, c) in seen or r < 0 or c < 0 or r > 5 or c > 5:
            continue
        bbox = cl.get("bbox")
        if not isinstance(bbox, list) or len(bbox) != 4 or any(
            isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or not 0 <= v <= 1 for v in bbox
        ) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]:
            raise ValueError("AI 未返回有效的六面裁剪位置，请重试或上传更清晰、正视的展开图")
        kind = str(cl.get("kind") or "none").strip()
        if kind not in ok_kind:
            kind = "image"
        dirv = str(cl.get("dir") or "").strip().lower()
        if dirv not in ok_dir:
            dirv = ""
        label = str(cl.get("label") or "").strip()[:2]
        seen.add((r, c))
        cells.append({"r": r, "c": c, "bbox": bbox, "kind": kind, "dir": dirv, "label": label})
    if len(cells) != 6:
        raise ValueError(f"识别出的格子数为 {len(cells)}（应为6），请只截取展开图部分后重试")
    pending = set(seen)
    queue = [pending.pop()]
    for r, c in queue:
        for neighbor in ((r - 1, c), (r + 1, c), (r, c - 1), (r, c + 1)):
            if neighbor in pending:
                pending.remove(neighbor)
                queue.append(neighbor)
    if pending:
        raise ValueError("识别出的六格不连通，请只截取一个完整展开图后重试")
    return {"is_net": True, "cells": cells, "note": str(d.get("note") or "")}


async def recognize_net(data_url: str, settings: dict) -> dict:
    key = settings.get("deepseek_api_key", "")
    base_url = settings.get("deepseek_base_url", "https://api.deepseek.com")
    if not key:
        raise ValueError("未配置 DeepSeek API Key，请到「题库管理 → 设置」填写后再使用拍照录题")
    if not data_url or not re.match(r"^data:image/[a-zA-Z0-9.+-]+;base64,", data_url):
        raise ValueError("图片格式不正确，请重新选择截图")
    content = [
        {"type": "text", "text": PROMPT},
        {"type": "image_url", "image_url": {"url": data_url}},
    ]
    async with httpx.AsyncClient(timeout=120) as cli:
        r = await cli.post(
            base_url.rstrip("/") + "/chat/completions",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "model": "deepseek-flash",
                "thinking": {"type": "disabled"},
                "max_tokens": 2200,
                "messages": [{"role": "user", "content": content}],
            },
        )
    if r.status_code != 200:
        raise ValueError(f"识别服务返回错误（{r.status_code}），请稍后重试")
    out = (r.json()["choices"][0]["message"].get("content") or "").strip()
    return _clean(_extract_json(out))
