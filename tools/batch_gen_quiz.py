#!/usr/bin/env python3
"""补齐缺失自测题的期次。"""
import json
import time
import urllib.request

PERIODS = [
    "2026年8月下半月",
    "2026年9月上半月",
    "2026年10月上半月",
]

BASE = "http://127.0.0.1:8765"


def post(path: str, data: dict) -> dict:
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        BASE + path,
        data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    for p in PERIODS:
        print(f"自测: {p}")
        try:
            r = post("/api/shizheng/quiz", {"period": p})
            if r.get("ok"):
                n = len(r.get("items", []))
                cached = r.get("cached", False)
                print(f"  ok {n}题 cached={cached}")
            else:
                print(f"  FAIL: {r.get('error')}")
        except Exception as e:
            print(f"  ERROR: {e}")
        time.sleep(1)
    print("完成")


if __name__ == "__main__":
    main()
