#!/usr/bin/env python3
"""按 qid 对账题库与个人数据，输出 import_report.json。

用法：
  python tools/qid_reconcile.py                       # 对账并落盘 data/import_report.json
  python tools/qid_reconcile.py --out report.json     # 指定输出路径
  python tools/qid_reconcile.py --no-snapshot         # 只统计，不更新基线快照
  python tools/qid_reconcile.py --json                # 直接把报告打到 stdout

为什么需要它（调研文档 12.2 / 12.7 / 14.7）：
  - 题量口径必须可复现：所有对外表述引用这份报告，禁止口头估算
  - 缺失必须显式：缺答案 / 缺解析按模块计数，不静默跳过
  - 切主键前必须验：8 张个人表的 qid 孤儿数必须全为 0

退出码：
  0 正常（有孤儿或失联也返回 0，那是数据现状而不是工具失败）
  1 对账本身失败（库打不开、路径不可写等）
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app import db  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="按 qid 对账题库与个人数据")
    ap.add_argument("--out", default="", help="报告输出路径（默认 data/import_report.json）")
    ap.add_argument("--no-snapshot", action="store_true",
                    help="不更新 _meta 里的 qid 基线快照（只读式检查）")
    ap.add_argument("--json", action="store_true", help="把报告打印到 stdout")
    args = ap.parse_args(argv)

    try:
        rep = db.reconcile_import(args.out or None,
                                  write_snapshot=not args.no_snapshot)
    except Exception as e:                       # noqa: BLE001  工具出错要给人话
        print(f"对账失败：{e}", file=sys.stderr)
        return 1

    t, d = rep["totals"], rep["diff"]
    print(f"题目 {t['documents']} 道，有 qid {t['with_qid']}，空 qid {t['blank_qid']}，"
          f"重复组 {t['duplicate_qid_groups']}")
    print(f"相对上次：新增 {d['added']} / 失联 {d['removed']} / 保留 {d['kept']}"
          f"（基线 {d['baseline']}）")
    # 孤儿分两类：blank（指向非题目行/历史脏数据，修不了也不该修）
    # 与 lost（qid 非空但题库里查不到，切主键前必须为 0）
    blank = {k: v["blank"] for k, v in rep["orphans"].items() if v.get("blank")}
    lost = {k: v["lost"] for k, v in rep["orphans"].items() if v.get("lost")}
    print("qid 为空的个人数据：" + ("无" if not blank else json.dumps(blank, ensure_ascii=False)))
    print("qid 真失联（必须为 0）：" + ("无" if not lost else json.dumps(lost, ensure_ascii=False)))
    bad = {k: v for k, v in rep["invalid_json_refs"].items() if v}
    print("失效题号引用：" + ("无" if not bad else json.dumps(bad, ensure_ascii=False)))
    for mod, s in sorted(rep["by_module"].items()):
        print(f"  {mod}: {s['total']} 题，缺答案 {s['missing_answer']}，"
              f"缺解析 {s['missing_analysis']}，含图 {s['with_image']}")
    if rep.get("report_path"):
        print(f"报告已写入 {rep['report_path']}")
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
