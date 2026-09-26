"""GOSHORE 启动入口：python run.py"""
import uvicorn

from app.config import load_settings

if __name__ == "__main__":
    s = load_settings()
    print("=" * 48)
    print("  GOSHORE 上岸工作台 已启动")
    print(f"  请用浏览器访问: http://127.0.0.1:{s['port']}")
    print("  按 Ctrl+C 停止服务")
    print("=" * 48)
    uvicorn.run("app.main:app", host="127.0.0.1", port=s["port"], log_level="warning")
