#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""AI 输出质量评测 CLI（离线 golden set）。

用法：
    python scripts/eval_ai.py                 # 人类可读报告，低于 95 分退出 1
    python scripts/eval_ai.py --json          # 机器可读，供 CI 归档
    python scripts/eval_ai.py --min-score 100 # 收紧门槛
    python scripts/eval_ai.py --live --record tests/golden/ai_golden.new.jsonl
                                              # 需配置 API Key，重录后人工 diff 再替换

评测口径与 golden 结构见 docs/03-开发/2026-10-21-AI 质量评测.md。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.ai_eval import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
