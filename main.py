# -*- coding: utf-8 -*-
"""AppShelf 桌面应用入口：内嵌本地服务 + 原生窗口
开发:  python main.py
打包:  pyinstaller appshelf.spec
"""
import os, sys, threading, socket, time

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

def free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p

def main():
    import webview
    import server as srv

    port = free_port()
    # 后台起本地服务（静态 + API + 定时扫描）
    def run():
        srv.PORT = port
        threading.Thread(target=srv.auto_scan, daemon=True).start()
        from http.server import ThreadingHTTPServer
        ThreadingHTTPServer(("127.0.0.1", port), srv.Handler).serve_forever()

    threading.Thread(target=run, daemon=True).start()
    # 等服务就绪
    for _ in range(50):
        try:
            socket.create_connection(("127.0.0.1", port), 0.1).close()
            break
        except OSError:
            time.sleep(0.05)

    webview.create_window(
        "AppShelf · 本机应用清单",
        f"http://127.0.0.1:{port}/index.html",
        width=1120, height=760,
        min_size=(760, 520),
        text_select=True,
    )
    webview.start()

if __name__ == "__main__":
    main()
