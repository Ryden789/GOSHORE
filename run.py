"""GOSHORE 启动入口：python run.py"""
import socket
import sys

import uvicorn

from app.config import load_settings


def _lan_ips():
    """尽力推断本机可被局域网访问的 IPv4 地址（排除回环）。

    优先用「默认路由」法：UDP connect 不会真的发包，即使没有外网，只要存在
    默认路由也能拿到本机出口 IP。失败再退回遍历本机主机名解析出的地址。
    找不到就返回空列表，由调用方明确提示「未能自动检测」，绝不假报 127.0.0.1
    为手机可访问地址。
    """
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    if not ips:
        try:
            for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
                ip = info[4][0]
                if not ip.startswith("127.") and ip not in ips:
                    ips.append(ip)
        except Exception:
            pass
    return [ip for ip in ips if not ip.startswith("127.")]


def _port_busy(port: int) -> bool:
    """检测端口是否已被监听（不结束任何进程，只做只读探测）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", port)) == 0
    finally:
        s.close()


if __name__ == "__main__":
    s = load_settings()
    port = s["port"]

    # 端口占用：给出明确提示与可恢复路径，不静默/强制结束任何进程
    if _port_busy(port):
        print("=" * 52)
        print(f"  ⚠️  端口 {port} 已被占用，未能启动新的服务实例。")
        print(f"  如果已有一个 GOSHORE 在运行，直接打开： http://127.0.0.1:{port}")
        print(f"  若是其它程序占用，先结束它再启动。查看占用者（Windows）：")
        print(f"      netstat -ano | findstr :{port}")
        print("  也可在 data/settings.json 里改端口后重启（手机入口需用同一端口）。")
        print("=" * 52)
        sys.exit(1)

    ips = _lan_ips()
    print("=" * 52)
    print("  GOSHORE 上岸工作台 已启动")
    print(f"  电脑访问:   http://127.0.0.1:{port}")
    if ips:
        print(f"  手机访问:   http://{ips[0]}:{port}/m/")
        print("  （手机需与电脑处于同一 Wi-Fi / 同一局域网）")
    else:
        print("  手机访问:   未能自动检测局域网地址")
        print("  请手动查询本机 IPv4（Windows 运行 ipconfig，macOS/Linux 运行 ifconfig），")
        print(f"  再用 http://<本机IPv4>:{port}/m/ 在手机上打开。")
        print("  注意：127.0.0.1 只在本机有效，手机访问不了。")
    print("  服务在局域网内监听（0.0.0.0）；请仅在可信网络中使用。")
    print("  按 Ctrl+C 停止服务")
    print("=" * 52)
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, log_level="warning")
