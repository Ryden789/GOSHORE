"""解析粉笔模考保存的 HTML，提取题目、选项、答案。"""
import re
import sys
import json
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else r'c:\Users\29364\Desktop\2026年下半年事业单位联考ABCDE类职测终极模考大赛.html')
s = p.read_text(encoding='utf-8', errors='ignore')

print('文件大小 MB:', round(len(s.encode('utf-8')) / 1048576, 2))
print('script块:', len(re.findall(r'<script', s)))
print('title:', re.findall(r'<title>(.*?)</title>', s))

# 粉笔保存页通常在 window.__INITIAL_STATE__ 或 JSON-LD 或 script 里藏数据
for key in ['__INITIAL_STATE__', 'window.__', 'application/json', '"questions"', '"options"', '"correct"',
            'class="item', 'class="ti', '试题', '解析']:
    print(f'{key!r}: {len(re.findall(re.escape(key), s))}')

# 看看 script 里的 JSON 数据块
scripts = re.findall(r'<script[^>]*>(.*?)</script>', s, re.S)
print('--- script 块预览 ---')
for i, sc in enumerate(scripts):
    sc = sc.strip()
    if not sc:
        continue
    head = sc[:120].replace('\n', ' ')
    print(f'[{i}] len={len(sc)} :: {head}')
