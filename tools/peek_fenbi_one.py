"""查看单题HTML结构样例。"""
import re
from pathlib import Path

p = Path(r'c:\Users\29364\Desktop\2026年下半年事业单位联考ABCDE类职测终极模考大赛.html')
s = p.read_text(encoding='utf-8', errors='ignore')

i = s.find('result-common-section')
print('=== 第一题 section 前后 3000 字符 ===')
chunk = s[i-200:i+3000]
print(chunk)
