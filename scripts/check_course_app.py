"""课程项目 index.html 静态完整性检查。"""
import re

html = open(r'D:\人文\课程项目_公考刷题软件\index.html', encoding='utf-8').read()

# 所有 onclick 引用的函数名
calls = set(re.findall(r'onclick="(?:event\.stopPropagation\(\);)?(?:if\(confirm\([^)]*\)\))?(\w+)\(', html))
# 已定义：window.x = ... 或 function x(
defined = set(re.findall(r'window\.(\w+)\s*=', html)) | set(re.findall(r'function\s+(\w+)\s*\(', html))
missing = calls - defined
print('onclick 调用数:', len(calls))
print('缺失定义:', sorted(missing) if missing else '无 OK')

# getElementById 引用 vs id= 定义
ids_used = set(re.findall(r'getElementById\("([\w-]+)"\)', html))
ids_def = set(re.findall(r'id="([\w-]+)"', html))
missing_ids = ids_used - ids_def
print('JS 引用的ID:', sorted(ids_used))
print('缺失的ID定义:', sorted(missing_ids) if missing_ids else '无 OK')

# localStorage 键名一致性
keys = set(re.findall(r'LS\.get\("(\w+)"', html)) | set(re.findall(r'LS\.set\("(\w+)"', html))
print('localStorage 键:', sorted(keys))

# 括号平衡
js = re.search(r'<script>(.*?)</script>', html, re.S).group(1)
print('braces diff:', js.count('{') - js.count('}'), '| parens diff:', js.count('(') - js.count(')'))
print('backtick diff:', js.count('`') % 2)
