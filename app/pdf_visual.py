# app/pdf_visual.py — PDF 图形题视觉提取
#
# 针对粉笔回忆版这类"题目文字+嵌入截图"的 PDF：
# 纯文本抽取拿不到图形（图推、立体展开图、资料图表），AI 只能跳过 → 完整性核对报缺题。
# 本模块按几何位置把每道题名下的嵌入图片/矢量区域裁成 PNG，存入题库图片目录，
# 配合行内"正确答案：X"组装成完整题目；解析由 deepseek-flash（V4.1 原生多模态）看图生成。
from __future__ import annotations

import base64
import hashlib
import io
import re
from pathlib import Path

import fitz  # pymupdf
import httpx

# 题干特征：图形推理常见设问
_FIG_STEM_RE = re.compile(r"规律性|填入问号处|展开图|立体图形|俯视图|截面图")
# 行内官方答案：正确答案：C
_INLINE_ANS_RE = re.compile(r"正确答案\s*[:：]?\s*([A-DＡ-Ｄ])")
# 题号锚点行：数字+点（可单独成行，题干预留到后续行），且靠左 margin
_QNO_LINE_RE = re.compile(r"^(\d{1,3})\s*[.、．]\s*(.*)$")
# 单个占位选项行：如 "A.A"（真实选项在图里，文字只是占坑）
_PLACEHOLDER_ONE_RE = re.compile(r"^[A-DＡ-Ｄ]\s*[.、．]?\s*[A-DＡ-Ｄ]?$")
# 页眉（跳过其中的图片）：试卷标题行
_HEADER_RE = re.compile(r"笔试题|试题卷|职业能力倾向测验")

_IMG_DIR = Path("90-图片") / "题目图"  # 相对 vault 的题库图片目录（与存量真题一致）


def _norm_letter(c: str) -> str:
    """全角字母转半角。"""
    return chr(ord(c) - 0xFEE0) if "Ａ" <= c <= "Ｄ" else c


def _page_lines(page) -> list[dict]:
    """提取页面文本行（含 y 坐标），按阅读顺序排列。"""
    out = []
    for block in page.get_text("dict").get("blocks", []):
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            txt = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
            if txt:
                out.append({"y": line["bbox"][1], "x": line["bbox"][0], "text": txt})
    out.sort(key=lambda l: (l["y"], l["x"]))
    return out


def _save_png(png: bytes, vault: Path, ext: str = "png") -> str | None:
    """图片写入题库图片目录，返回 /img?path= 可用的相对路径。"""
    try:
        d = vault / _IMG_DIR
        d.mkdir(parents=True, exist_ok=True)
        name = hashlib.md5(png).hexdigest()[:13] + "." + ext
        fp = d / name
        if not fp.exists():
            fp.write_bytes(png)
        import urllib.parse
        return "/img?path=" + urllib.parse.quote(str(_IMG_DIR / name).replace("\\", "/"))
    except OSError:
        return None


def _img_tag(src: str, w: int, h: int, zoom: float = 1.0) -> str:
    """按题库现有格式生成 img 标签。"""
    return f'<img width="{int(w * zoom)}px" height="{int(h * zoom)}px" src="{src}" />'


def extract_visual_spans(data: bytes) -> dict[int, dict]:
    """按题号归属页面图片与行内答案。

    返回 {题号: {"images": [(png_bytes, w, h)], "answer": "C", "stem": "题干文本",
                  "placeholder": 选项是否占位符, "fig": 是否图形题特征}}
    跨页延续：页首元素归属上一页最后一题。
    """
    doc = fitz.open(stream=data, filetype="pdf")
    qs: dict[int, dict] = {}
    cur = 0  # 当前题号（0=还未遇到题）
    try:
        for page in doc:
            lines = _page_lines(page)
            header_bottom = 0.0
            for ln in lines[:3]:
                if _HEADER_RE.search(ln["text"]) and ln["y"] < 90:
                    header_bottom = max(header_bottom, ln["y"] + 12)

            # 页面元素时间线：文本行 + 图片块
            events: list[tuple[float, str, object]] = [(ln["y"], "line", ln) for ln in lines]
            for img in page.get_images(full=True):
                try:
                    bbox = page.get_image_bbox(img)
                except ValueError:
                    continue
                if bbox.y0 < header_bottom:
                    continue  # 页眉横幅
                if bbox.width < 50 or bbox.height < 20:
                    continue  # 图标/装饰
                events.append((bbox.y0, "img", (img, bbox)))
            events.sort(key=lambda e: e[0])

            for _, kind, obj in events:
                if kind == "line":
                    txt = obj["text"]
                    m = _QNO_LINE_RE.match(txt)
                    if m and obj["x"] < 110:
                        qno = int(m.group(1))
                        # 题号必须递增（防材料内的编号列表劫持）；允许小幅跳号
                        if cur < qno <= cur + 5 and qno <= 200:
                            cur = qno
                            qs.setdefault(cur, {"images": [], "answer": "", "stem_lines": [],
                                                "ph": 0, "placeholder": False, "fig": False})
                            # 题号与题干可能分两行（"62." 单独成行）
                            rest = m.group(2).strip()
                            if rest:
                                qs[cur]["stem_lines"].append(rest)
                            continue
                    if cur == 0:
                        continue
                    q = qs[cur]
                    am = _INLINE_ANS_RE.search(txt)
                    if am:
                        q["answer"] = _norm_letter(am.group(1))
                        continue
                    if re.match(r"^(你的答案|我的答案)\s*[:：]", txt):
                        continue
                    if _PLACEHOLDER_ONE_RE.match(txt):
                        q["ph"] += 1  # 累计 ≥3 个 A.A/B.B/C.C 行才算占位选项
                        continue
                    # 尚未遇到图片/答案的行视为题干延续
                    if not q["images"] and not q["answer"]:
                        q["stem_lines"].append(txt)
                else:
                    if cur == 0:
                        continue
                    img, bbox = obj
                    try:
                        ext = doc.extract_image(img[0])["ext"]
                        png = doc.extract_image(img[0])["image"]
                        w, h = img[2], img[3]
                    except Exception:
                        continue
                    qs[cur]["images"].append((png, w, h, ext))
    finally:
        doc.close()

    for qno, q in qs.items():
        stem = "".join(q["stem_lines"]).strip()
        q["stem"] = stem
        q["placeholder"] = q["ph"] >= 3
        q["fig"] = bool(q["images"]) and (q["placeholder"] or bool(_FIG_STEM_RE.search(stem)))
        q.pop("stem_lines", None)
        q.pop("ph", None)
    return qs


async def _vision_analysis(key: str, base_url: str, images: list[str], stem: str, answer: str) -> dict:
    """deepseek-flash（V4.1 原生多模态）看图输出 {module, kaodian, analysis}；失败返回空 dict。

    V4.1-Flash 默认开思考模式，图形题会让它长时间推理直至耗尽 max_tokens（content 为空），
    此处仅需依据给定答案写简析，故显式关闭 thinking。
    """
    content: list[dict] = [{
        "type": "text",
        "text": ("这是事业单位C类职测的一道题，截图上方是题干图形/图表，下方是 A/B/C/D 四个选项。\n"
                 f"正确答案：{answer}\n题干文字：{stem[:200]}\n"
                 "请输出紧凑 JSON（不要 markdown 代码块）：{\"module\":\"...\",\"kaodian\":\"...\",\"analysis\":\"...\"}\n"
                 "module 只能是：常识判断 / 言语理解 / 数量关系 / 判断推理 / 资料分析 / 综合分析；"
                 "kaodian 填细分考点（如 图形推理 / 折线图 / 立体几何）；"
                 "analysis 用一两句话（60字内）说明规律或解法，不要复述题号与选项字母。"),
    }]
    for b64 in images[:3]:
        content.append({"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}})
    try:
        async with httpx.AsyncClient(timeout=90) as cli:
            r = await cli.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json={"model": "deepseek-flash", "thinking": {"type": "disabled"},
                      "max_tokens": 500,
                      "messages": [{"role": "user", "content": content}]},
            )
            if r.status_code != 200:
                return {}
            out = (r.json()["choices"][0]["message"].get("content") or "").strip()
            i, j = out.find("{"), out.rfind("}")
            if i >= 0 and j > i:
                import json as _json
                d = _json.loads(out[i:j + 1])
                if isinstance(d, dict):
                    return d
    except Exception:
        pass
    return {}


async def build_figure_items(data: bytes, settings: dict) -> tuple[list[dict], dict[int, list[str]]]:
    """从 PDF 构建图形题条目 + 为文字题补充缺图。

    返回 (图形题 items, {题号: [img标签...]})；后者供 AI 已抽到的文字题补图（如资料分析图表）。
    """
    vault_raw = (settings.get("vault_path") or "").strip()
    if not vault_raw:
        return [], {}
    vault = Path(vault_raw)
    spans = extract_visual_spans(data)
    items: list[dict] = []
    attach: dict[int, list[str]] = {}
    for qno in sorted(spans):
        q = spans[qno]
        if not q["images"]:
            continue
        tags = []
        for png, w, h, ext in q["images"]:
            src = _save_png(png, vault, ext=ext)
            if src:
                tags.append(_img_tag(src, w, h, zoom=0.6))
        if not tags:
            continue
        if not q["fig"]:
            attach[qno] = tags  # 非图形特征但带图 → 留给文字题补图
            continue
        if not q["answer"] or not q["stem"]:
            continue  # 无答案或无题干的残题不构造
        imgs_b64 = [base64.b64encode(p).decode() for p, _, _, _ in q["images"]]
        info = await _vision_analysis(
            settings.get("deepseek_api_key", ""), settings.get("deepseek_base_url", ""),
            imgs_b64, q["stem"], q["answer"],
        ) if settings.get("deepseek_api_key") else {}
        items.append({
            "no": qno,
            "stem": q["stem"] + "\n" + "\n".join(tags),
            "options": [{"label": c, "text": f"（见上图{c}）"} for c in "ABCD"],
            "answer": q["answer"],
            "analysis": str(info.get("analysis") or "").strip(),
            "module": str(info.get("module") or "判断推理").strip(),
            "kaodian": str(info.get("kaodian") or "图形推理").strip(),
            "year": "", "exam": "",
        })
    return items, attach
