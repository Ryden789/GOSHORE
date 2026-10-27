"""按模块统计 + 输出错题详情供复盘。"""
import json
from pathlib import Path

qs = json.loads(Path(r'D:\GOSHORE\tools\fenbi_extract.json').read_text(encoding='utf-8'))
by_num = {q['num']: q for q in qs}

# 确认边界：打印40-41、50-51、60-61、90-91附近的考点
print('=== 边界考点确认 ===')
for n in ['20','21','40','41','50','51','60','61','90','91','95','100']:
    q = by_num.get(n)
    if q:
        print(f"#{n} 考点:{'/'.join(q['keypoint'])[:40]}")

# 模块区间（待边界确认后固定）
MODULES = [
    ('常识判断', 1, 20, 20),
    ('言语理解', 21, 40, 32),
    ('数量关系', 41, 50, 20),
    ('资料分析', 51, 60, 15),
    ('判断推理', 61, 90, 45),
    ('综合分析', 91, 100, 18),
]
print('\n=== 模块统计 ===')
total = 0
for name, a, b, full in MODULES:
    sel = [q for q in qs if a <= int(q['num']) <= b]
    ok = sum(1 for q in sel if q['verdict'] == 'correct')
    total += ok / len(sel) * full
    print(f"{name}: {ok}/{len(sel)}  正确率{ok/len(sel)*100:.0f}%  得分≈{ok/len(sel)*full:.1f}/{full}")
print(f"总分≈{total:.1f}/150")

# 错题详情（题干前80字+选项+解析前200字）
print('\n=== 错题详情 ===')
for q in qs:
    if q['verdict'] == 'wrong':
        print(f"\n--- #{q['num']} [{'/'.join(q['keypoint'])}] 我:{q['my']}→正:{q['correct']} 易错:{q['trap']}")
        print('题干:', q['stem'][:100])
        for L, t in q['options'].items():
            mark = '✔' if L == q['correct'] else ('✘' if L == q['my'] else ' ')
            print(f'  {mark}{L}. {t[:60]}')
        print('解析:', q['solution'][:220])
