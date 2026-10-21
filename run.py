"""GOSHORE 启动入口：python run.py（默认只开本机） / python run.py --lan（局域网+令牌）。"""
import argparse
import socket
import sys

import uvicorn

from app import access
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="GOSHORE 启动器：默认只监听本机；--lan 才开放局域网并要求令牌")
    ap.add_argument("--lan", action="store_true",
                    help="监听 0.0.0.0，供手机/其它设备访问；自动生成访问令牌")
    ap.add_argument("--port", type=int, default=None, help="覆盖 data/settings.json 里的端口")
    args = ap.parse_args(argv)

    s = load_settings()
    port = args.port or int(s["port"])

    # 端口占用：给出明确提示与可恢复路径，不静默/强制结束任何进程
    if _port_busy(port):
        print("=" * 52)
        print(f"  ⚠️  端口 {port} 已被占用，未能启动新的服务实例。")
        print(f"  如果已有一个 GOSHORE 在运行，直接打开： http://127.0.0.1:{port}")
        print("  若是其它程序占用，先结束它再启动。查看占用者（Windows）：")
        print(f"      netstat -ano | findstr :{port}")
        print("  也可在 data/settings.json 里改端口后重启。")
        print("=" * 52)
        return 1

    print("=" * 52)
    print("  GOSHORE 上岸工作台 已启动")
    print(f"  电脑访问:   http://127.0.0.1:{port}")

    if args.lan:
        token = access.ensure_access_token()
        ips = _lan_ips()
        if ips:
            print(f"  手机访问:   http://{ips[0]}:{port}/m/?token={token}")
            print("  （手机需与电脑处于同一 Wi-Fi / 同一局域网；首次打开会记住 30 天）")
        else:
            print("  手机访问:   未能自动检测局域网地址")
            print("  请手动查询本机 IPv4（Windows 运行 ipconfig，macOS/Linux 运行 ifconfig），")
            print(f"  再用 http://<本机IPv4>:{port}/m/?token={token} 在手机上打开。")
            print("  注意：127.0.0.1 只在本机有效，手机访问不了。")
        print(f"  访问令牌:   {token}")
        print("  ⚠️  已开放局域网（0.0.0.0），所有非本机请求都必须带上面的令牌；")
        print("      不要把带令牌的链接发到群里或公共网络。")
        print("      怀疑泄露时：关掉服务，设置新的 GOSHORE_ACCESS_TOKEN 后再启动。")
    else:
        print("  手机访问:   未开启（默认只允许本机）")
        print("  确需手机访问：用 python run.py --lan 启动，会打印带访问令牌的手机地址。")
        print("  ⚠️  默认只监听 127.0.0.1，同一局域网内的其它设备无法访问；")
        print("      不要用 uvicorn 手动绑 0.0.0.0，那会绕开本启动器的令牌逻辑。")

    print("  按 Ctrl+C 停止服务")
    print("=" * 52)
    uvicorn.run("app.main:app", host="0.0.0.0" if args.lan else "127.0.0.1",
                port=port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
