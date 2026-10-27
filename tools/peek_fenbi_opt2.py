"""在DOM上下文查看选项结构（跳过CSS）。"""
import re
from pathlib import Path

p = Path(r'c:\Users\29364\Desktop\2026年下半年事业单位联考ABCDE类职测终极模考大赛.html')
s = p.read_text(encoding='utf-8', errors='ignore')

# 找ul里的choice-radios（DOM而非CSS）
m = re.search(r'<ul[^>]*choice-radios[^>]*>', s)
print('ul起点:', m.start() if m else None)
if m:
    print(s[m.start():m.start()+3500])
