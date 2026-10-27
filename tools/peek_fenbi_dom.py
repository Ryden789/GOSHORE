"""查看粉笔HTML的DOM题目结构。"""
import re
from pathlib import Path

p = Path(r'c:\Users\29364\Desktop\2026年下半年事业单位联考ABCDE类职测终极模考大赛.html')
s = p.read_text(encoding='utf-8', errors='ignore')

# 去掉换行便于观察
s2 = re.sub(r'\s+', ' ', s)

# 找第一个 class 含 ti 的节点的上下文
m = re.search(r'<[^>]*class="[^"]*ti[^"]*"[^>]*>', s2)
print('第一个ti类节点:', m.group(0) if m else None)

# 列出所有 class 属性种类和频次
classes = re.findall(r'class="([^"]+)"', s2)
from collections import Counter
c = Counter()
for cl in classes:
    for tok in cl.split():
        c[tok] += 1
print('--- top40 class ---')
for k, v in c.most_common(40):
    print(f'{v:5d}  {k}')
