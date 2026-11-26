"""按需登录代理：把本机网络借给服务器，只在扫码登录时用。

用法（在你自己的电脑上运行）：
    python tools/login_proxy.py --server root@你的服务器IP --port 8898

它会做两件事：
  1. 在本机 127.0.0.1:<port> 起一个 HTTP CONNECT 代理
  2. 用 SSH 反向隧道把这个端口映射到服务器的 127.0.0.1:<port>

然后在服务器上设 HTTPS_PROXY=http://127.0.0.1:<port>，登录请求就会从
你本机的网络出口发出（家用宽带 IP），符合平台对"登录环境"的常规预期。
关闭窗口即全部撤销，不留任何常驻服务。

用途边界：仅用于【本人账号】在【本人设备】上完成一次登录。
不用于他人账号，也不用于任何自动化批量登录。
"""
import argparse
import os
import select
import socket
import socketserver
import subprocess
import threading
import time

BUFSIZE = 65536

# 只允许白名单域名，防止这条隧道被拿去访问别的网站
DEFAULT_ALLOW = "chaoxing.com,cxstar.com,xuexixing.com"
ALLOW_SUFFIXES = []
LAST_ACTIVITY = [0.0]
LIFETIME = [0.0]


def host_allowed(host):
    host = (host or "").lower().strip(".")
    if not ALLOW_SUFFIXES:
        return True
    return any(host == s or host.endswith("." + s) for s in ALLOW_SUFFIXES)


class ProxyHandler(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            head = self.request.recv(8192)
        except OSError:
            return
        if not head:
            return
        first = head.split(b"\r\n", 1)[0].decode("latin-1", "ignore")
        parts = first.split()
        if len(parts) < 2 or parts[0].upper() != "CONNECT":
            self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        host, _, port_text = parts[1].rpartition(":")
        if not host:
            host, port_text = parts[1], "443"
        if not host_allowed(host):
            self.request.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
            print("拒绝非白名单目标：" + host)
            return
        try:
            upstream = socket.create_connection((host, int(port_text or 443)), timeout=15)
        except OSError:
            self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\n\r\n")
            return
        self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
        LAST_ACTIVITY[0] = time.time()
        peers = {self.request: upstream, upstream: self.request}
        try:
            while True:
                ready, _, _ = select.select(list(peers), [], [], 60)
                if not ready:
                    break
                for sock in ready:
                    data = sock.recv(BUFSIZE)
                    if not data:
                        return
                    peers[sock].sendall(data)
        except OSError:
            return
        finally:
            try:
                upstream.close()
            except OSError:
                pass


class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def ensure_key(path):
    """没有密钥就生成一个，返回私钥路径和公钥内容。"""
    import os
    import subprocess

    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        pub = path + ".pub"
        if os.path.exists(pub):
            with open(pub, encoding="utf-8") as fh:
                return path, fh.read().strip()
    subprocess.run(["ssh-keygen", "-t", "ed25519", "-N", "", "-q", "-f", path,
                    "-C", "xuexit-login-helper"], check=False)
    pub = path + ".pub"
    text = ""
    if os.path.exists(pub):
        with open(pub, encoding="utf-8") as fh:
            text = fh.read().strip()
    return path, text


def main():
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--config", default="", help="配置文件（JSON）")
    known, _ = pre.parse_known_args()

    conf = {}
    if known.config:
        import json as _json
        with open(known.config, encoding="utf-8") as fh:
            conf = _json.load(fh) or {}
        print("已读取配置：" + known.config)

    parser = argparse.ArgumentParser(description="按需登录代理（本机出口借给服务器）")
    parser.add_argument("--config", default=known.config, help="配置文件（JSON）")
    parser.add_argument("--server", default=conf.get("server", ""), help="SSH 目标")
    parser.add_argument("--port", type=int, default=int(conf.get("port", 8898)), help="本地/远端端口")
    parser.add_argument("--identity", default=conf.get("identity", ""), help="SSH 私钥路径（可选）")
    parser.add_argument("--bind", default=conf.get("bind", "172.17.0.1"),
                        help="远端绑定地址（容器要访问时用 docker 网桥 IP）")
    parser.add_argument("--allow", default=conf.get("allow", DEFAULT_ALLOW),
                        help="允许的目标域名后缀，逗号分隔；留空表示不限制")
    parser.add_argument("--idle-exit", type=int, default=int(conf.get("idle_exit", 180)),
                        help="空闲多少秒后自动退出（0 表示不退出）")
    parser.add_argument("--max-life", type=int, default=int(conf.get("max_life", 1800)),
                        help="最长运行秒数（0 表示不限制）")
    args = parser.parse_args()

    key_path, pubkey = ensure_key(os.path.expanduser("~/.xuexit/helper_ed25519"))
    print("=" * 60)
    print("助手公钥（粘贴到 AstrBot 面板「登录助手 → 公钥」里，只需一次）：")
    print(pubkey)
    print("=" * 60)

    ALLOW_SUFFIXES[:] = [s.strip().lower() for s in (args.allow or "").split(",") if s.strip()]
    print("允许的目标：" + (", ".join(ALLOW_SUFFIXES) if ALLOW_SUFFIXES else "不限"))
    started = time.time()
    LAST_ACTIVITY[0] = started
    LIFETIME[0] = started

    server = ThreadedServer(("127.0.0.1", args.port), ProxyHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print("代理已启动：127.0.0.1:%d" % args.port)

    cmd = ["ssh", "-N", "-o", "ExitOnForwardFailure=yes",
           "-o", "ServerAliveInterval=30",
           "-R", "%s:%d:127.0.0.1:%d" % (args.bind, args.port, args.port)]
    cmd += ["-i", args.identity or key_path]
    cmd.append(args.server)
    print("建立反向隧道：" + " ".join(cmd))
    proc = subprocess.Popen(cmd)
    try:
        while proc.poll() is None:
            time.sleep(1)
            now = time.time()
            if args.max_life and now - LIFETIME[0] > args.max_life:
                print("达到最长运行时间，自动退出")
                break
            if args.idle_exit and now - LAST_ACTIVITY[0] > args.idle_exit:
                print("空闲超时，自动退出")
                break
    except KeyboardInterrupt:
        print("\n正在关闭…")
    finally:
        try:
            proc.terminate()
        except OSError:
            pass
        server.shutdown()
        print("已关闭：代理和隧道都撤销了")


if __name__ == "__main__":
    main()
