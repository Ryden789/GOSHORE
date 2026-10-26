"""CI 质量门用：跑移动端 E2E，失败自动重试一次，并把失败行提升为 GitHub 注解。

为什么放在 Python 里而不是写进 YAML 的 shell：这套 E2E 在 CI 上偶发超时
（340a285 这种纯文档提交也红过），需要「失败先重试一次」；而本机没有 bash，
用 Python 才能本地自检这段重试逻辑（--cmd 换命令）。

用法：
    python scripts/ci_e2e_retry.py                 # CI 默认：跑两次机会
    python scripts/ci_e2e_retry.py --attempts 1    # 只跑一次
    python scripts/ci_e2e_retry.py --cmd "python -c 'import sys; sys.exit(1)'"

退出码 = 最后一次尝试的退出码（0 才算通过）。作业日志下载要仓库写权限，
所以失败时把 [FAIL] 行打成 ::error:: 注解（公开仓库可直接在提交页看到）。
"""

from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_CMD = [sys.executable, "-u", str(REPO / "scripts" / "e2e_mobile.py")]


def run_once(cmd: list[str], log_path: Path) -> int:
    """跑一次命令，输出实时透传到 stdout 并落盘，返回退出码。"""
    env = dict(os.environ)
    env.setdefault("PYTHONUTF8", "1")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    with log_path.open("w", encoding="utf-8", errors="replace") as fh:
        proc = subprocess.Popen(
            cmd,
            cwd=str(REPO),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            fh.write(line)
        return proc.wait()


def failure_lines(log_path: Path, limit: int = 10) -> list[str]:
    """从日志里挑失败行；没有 [FAIL] 标记时退回最后几行。"""
    if not log_path.exists():
        return []
    lines = [l.rstrip() for l in log_path.read_text(encoding="utf-8", errors="replace").splitlines() if l.strip()]
    picked = [l for l in lines if l.startswith("[FAIL]")]
    if not picked:
        picked = lines[-15:]
    return [l[:900] for l in picked[:limit]]


def annotate(lines: list[str], level: str) -> None:
    for line in lines:
        print(f"::{level}::{line}", flush=True)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="带一次重试的 E2E 运行器")
    ap.add_argument("--cmd", default="", help="覆盖默认命令（本地自检用）")
    ap.add_argument("--attempts", type=int, default=2, help="最多尝试次数（默认 2）")
    ap.add_argument("--log", default="", help="日志路径（默认临时目录）")
    args = ap.parse_args(argv)

    if args.cmd:
        # Windows 下 posix 模式会把反斜杠当转义符吃掉（C:\Users → C:Users），
        # 只有本地自检才会走到这里，CI 用的是 DEFAULT_CMD 列表。
        cmd = shlex.split(args.cmd, posix=(os.name != "nt"))
        if os.name == "nt":
            cmd = [p.strip('"') for p in cmd]
    else:
        cmd = list(DEFAULT_CMD)
    attempts = max(1, args.attempts)
    log_dir = Path(os.environ.get("TEMP") or os.environ.get("TMPDIR") or "/tmp")
    log_path = Path(args.log) if args.log else log_dir / "e2e.log"

    rc = 0
    for i in range(1, attempts + 1):
        if i > 1:
            print(f"::warning::E2E 第 {i - 1} 次未通过，重试一次（该套件在 CI 上偶发超时）", flush=True)
        rc = run_once(cmd, log_path)
        if rc == 0:
            return 0
        annotate(failure_lines(log_path), "warning" if i < attempts else "error")

    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary and log_path.exists():
        tail = log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-40:]
        try:
            with open(summary, "a", encoding="utf-8") as fh:
                fh.write("### E2E 失败摘要\n```\n" + "\n".join(tail) + "\n```\n")
        except OSError:
            pass
    return rc


if __name__ == "__main__":
    sys.exit(main())
