"""查看选项内部结构。"""
import re
from pathlib import Path

p = Path(r'c:\Users\29364\Desktop\2026年下半年事业单位联考ABCDE类职测终极模考大赛.html')
s = p.read_text(encoding='utf-8', errors='ignore')

i = s.find('choice-radio-label')
print(s[i-300:i+2500])
