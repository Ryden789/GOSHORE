"""定位第一题的实际DOM内容。"""
import re
from pathlib import Path

p = Path(r'c:\Users\29364\Desktop\2026年下半年事业单位联考ABCDE类职测终极模考大赛.html')
s = p.read_text(encoding='utf-8', errors='ignore')

# 找 class="result-common-section" 的div本体
for m in re.finditer(r'<div[^>]*class="[^"]*result-common-section[^"]*"', s):
    print('div位置:', m.start(), m.group(0)[:120])
    break

i = s.find('class="result-common-section')
if i > 0:
    chunk = s[i:i+6000]
    print(chunk)
