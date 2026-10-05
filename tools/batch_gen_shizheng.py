#!/usr/bin/env python3
"""批量生成缺失的半月时政并入库。"""
import json
import time
import urllib.request

PERIODS = [
    "2026年4月下半月",
    "2026年5月上半月",
    "2026年5月下半月",
    "2026年6月上半月",
    "2026年6月下半月",
    "2026年7月上半月",
    "2026年7月下半月",
    "2026年8月上半月",
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
        print(f"生成: {p}")
        try:
            r = post("/api/shizheng/generate", {"period": p})
            if r.get("ok"):
                cached = r.get("cached", False)
                clen = len(r["item"]["content"])
                print(f"  ok cached={cached} content_len={clen}")
            else:
                print(f"  FAIL: {r.get('error')}")
        except Exception as e:
            print(f"  ERROR: {e}")
        time.sleep(1)  # 避免AI接口过载

    # 再批量生成自测题
    print("\n--- 生成自测题 ---")
    for p in PERIODS:
        print(f"自测: {p}")
        try:
            r = post("/api/shizheng/quiz", {"period": p})
            if r.get("ok"):
                n = len(r.get("items", []))
                print(f"  ok {n}题")
            else:
                print(f"  FAIL: {r.get('error')}")
        except Exception as e:
            print(f"  ERROR: {e}")
        time.sleep(1)

    print("\n全部完成")


if __name__ == "__main__":
    main()
