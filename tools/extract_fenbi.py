"""提取粉笔模考HTML：题号/题型/对错/正答/我的答案/全站正确率/用时/易错项/题干/解析/考点。"""
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup

SRC = Path(r'c:\Users\29364\Desktop\2026年下半年事业单位联考ABCDE类职测终极模考大赛.html')
OUT = Path(r'D:\GOSHORE\tools\fenbi_extract.json')

s = SRC.read_text(encoding='utf-8', errors='ignore')
soup = BeautifulSoup(s, 'html.parser')

def flat(el):
    return re.sub(r'\s+', ' ', el.get_text(' ', strip=True)) if el else ''

questions = []
for ti in soup.select('app-ti[data-question-key]'):
    container = ti.select_one('.ti-container')
    if container is None:
        continue
    cl = container.get('class', [])
    verdict = 'correct' if 'correct' in cl else ('wrong' if 'wrong' in cl else '?')

    num = flat(ti.select_one('.title-index')).rstrip('.')
    qtype = flat(ti.select_one('.title-type-name')).strip()
    key = ti.get('data-question-key', '')

    # 题干（主content，非section内的）
    stem = ''
    main = None
    for c in ti.select('div.content'):
        if c.find_parent('section') is None:
            main = c
            break
    if main is not None:
        stem = flat(main)

    # 选项文本
    options = {}
    for lab in ti.select('.choice-radio-label'):
        letter = flat(lab.select_one('.input-radio'))
        text = flat(lab.select_one('.input-text'))
        if letter:
            options[letter] = text

    # 汇总区
    ov = ti.select_one('.question-overall-container') or ti.select_one('app-solution-overall')
    corr = flat(ov.select_one('.correct-answer')) if ov else ''
    mine = flat(ov.select_one('.your-answer')) if ov else ''
    rate = flat(ov.select_one('.correct-rate')) if ov else ''
    secs = flat(ov.select_one('.answer-time')) if ov else ''
    trap = flat(ov.select_one('.error-prone')) if ov else ''

    # 解析、考点
    sol_sec = ti.select_one(f'[id="section-solution-{key}"]')
    sol = flat(sol_sec.select_one('.content')) if sol_sec else ''
    kp_sec = ti.select_one(f'[id="section-keypoint-{key}"]')
    kps = [flat(x) for x in kp_sec.select('.solution-keypoint-item-name')] if kp_sec else []

    questions.append({
        'num': num, 'type': qtype, 'verdict': verdict, 'key': key,
        'stem': stem, 'options': options,
        'my': mine, 'correct': corr, 'rate': rate, 'secs': secs, 'trap': trap,
        'keypoint': kps, 'solution': sol,
    })

questions.sort(key=lambda q: float(q['num']) if q['num'] else 0)
OUT.write_text(json.dumps(questions, ensure_ascii=False, indent=1), encoding='utf-8')

n_ok = sum(1 for q in questions if q['verdict'] == 'correct')
n_no = sum(1 for q in questions if q['verdict'] == 'wrong')
print(f'共 {len(questions)} 题 | 对 {n_ok} | 错 {n_no} | 其他 {len(questions)-n_ok-n_no}')
print('--- 错题清单 ---')
for q in questions:
    if q['verdict'] == 'wrong':
        print(f"#{q['num']:>4} 我:{q['my'] or '未选'}→正:{q['correct']} 全站:{q['rate']}% 用时:{q['secs']} 考点:{'/'.join(q['keypoint'])}")
