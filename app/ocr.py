"""图片 → 文字（OCR）：把手写/打印的作答稿转成可编辑文本。

与 `cube_vision.py` 的区别：那个是「折纸盒展开图 → 六格 JSON」，prompt 为特定
题型定制；这里是通用转写，输出纯文本，两者不能共用 prompt，故独立成模块。

模型与错误口径跟 `cube_vision` 保持一致：`config.vision_model()` 取模，
上游非 200 统一转成可展示的中文 ValueError。
"""
from __future__ import annotations

import re

import httpx

from .config import vision_model

# 单张图 base64 上限：前端压缩后约 200—400 KB，留足余量
MAX_IMAGE_CHARS = 8 * 1024 * 1024

_DATA_URL_RE = re.compile(r"^data:image/[a-zA-Z0-9.+-]+;base64,[A-Za-z0-9+/=]+$")

PROMPTS = {
    # 申论作答：要的是「原样抄下来」，任何润色都会让批改判错
    "essay": (
        "这是一份申论（或综应）手写作答的拍照/截图。请把作答内容逐字转写成纯文本。\n"
        "规则：\n"
        "1. 只输出作答正文，不要任何前言、解释、点评、字数统计或总结。\n"
        "2. 保持原有分段：每个自然段之间空一行；段首的序号（一、1.（1））原样保留。\n"
        "3. 严格按原文转写，**不要纠错、不要润色、不要补全句子、不要改标点风格**——"
        "这是要给阅卷规则打分的，改一个字都可能导致误判。\n"
        "4. 认不出的字用「□」占位，不要凭上下文猜。\n"
        "5. 划掉/涂改的内容忽略，只写最终保留的文字。\n"
        "6. 如果图片里没有可识别的文字，只输出：NO_TEXT"
    ),
    # 通用：题干、材料、题目截图
    "general": (
        "请把图片中的文字完整转写成纯文本。\n"
        "规则：\n"
        "1. 只输出文字内容，不要解释、不要总结、不要加标题。\n"
        "2. 保持原有结构与顺序：题干、选项（A. B. C. D.）、编号、表格按行输出。\n"
        "3. 严格按原文转写，不要纠错或改写。\n"
        "4. 认不出的字用「□」占位。\n"
        "5. 如果图片里没有可识别的文字，只输出：NO_TEXT"
    ),
}

MAX_TOKENS = 4000


def _pick_prompt(mode: str) -> str:
    return PROMPTS["essay"] if mode == "essay" else PROMPTS["general"]


async def recognize(data_url: object, settings: dict, mode: str = "general") -> dict:
    """识别图片中的文字，返回 `{text, chars, mode}`。

    失败抛 ValueError（中文），由两端服务转 400/502。
    """
    key = (settings.get("deepseek_api_key") or "").strip()
    base_url = settings.get("deepseek_base_url") or "https://api.deepseek.com"
    if not key:
        raise ValueError("未配置 DeepSeek API Key，请到「设置」填写后再使用图片识别")
    if not isinstance(data_url, str) or not _DATA_URL_RE.match(data_url.strip()):
        raise ValueError("图片格式不正确，请重新选择（支持 JPG / PNG / WebP）")
    if len(data_url) > MAX_IMAGE_CHARS:
        raise ValueError("图片太大，请压缩后重试")

    mode = "essay" if mode == "essay" else "general"
    payload = {
        "model": vision_model(settings),
        "thinking": {"type": "disabled"},
        "max_tokens": MAX_TOKENS,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": _pick_prompt(mode)},
                {"type": "image_url", "image_url": {"url": data_url}},
            ],
        }],
    }
    try:
        async with httpx.AsyncClient(timeout=120) as cli:
            r = await cli.post(
                base_url.rstrip("/") + "/chat/completions",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except httpx.HTTPError as e:
        raise ValueError(f"识别服务连接失败（{type(e).__name__}），请检查网络后重试")
    if r.status_code != 200:
        raise ValueError(f"识别服务返回错误（{r.status_code}），请稍后重试")
    try:
        text = (r.json()["choices"][0]["message"].get("content") or "").strip()
    except (KeyError, IndexError, TypeError, ValueError):
        raise ValueError("识别服务返回格式异常，请重试")

    if not text or text.strip() == "NO_TEXT":
        raise ValueError("这张图里没认出文字，请拍清楚一些或换个角度")

    # 模型偶尔会在正文外裹一层代码块或引言，剥掉再返回
    text = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return {"text": text, "chars": len(text), "mode": mode}
