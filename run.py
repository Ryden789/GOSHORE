"""GOSHORE 启动入口：python run.py"""
import socket

import uvicorn

from app.config import load_settings


def _lan_ip() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    s = load_settings()
    ip = _lan_ip()
    print("=" * 52)
    print("  GOSHORE 上岸工作台 已启动")
    print(f"  电脑访问:   http://127.0.0.1:{s['port']}")
    print(f"  手机访问:   http://{ip}:{s['port']}/m/")
    print("  （手机需与电脑连接同一 Wi-Fi）")
    print("  按 Ctrl+C 停止服务")
    print("=" * 52)
    uvicorn.run("app.main:app", host="0.0.0.0", port=s["port"], log_level="warning")
