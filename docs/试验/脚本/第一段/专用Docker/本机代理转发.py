#!/usr/bin/env python3
"""第一段：在虚拟机里模拟「代理只在本机内部 127.0.0.1:7890 开着」，转发到真正的代理 10.0.2.2:7890。"""
import socket, threading
def pipe(a, b):
    try:
        while (d := a.recv(65536)): b.sendall(d)
    except Exception: pass
    finally:
        for s in (a, b):
            try: s.close()
            except Exception: pass
srv = socket.socket(); srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1); srv.bind(('127.0.0.1', 7890)); srv.listen(64)
while True:
    c, _ = srv.accept(); u = socket.create_connection(('10.0.2.2', 7890))
    threading.Thread(target=pipe, args=(c, u), daemon=True).start(); threading.Thread(target=pipe, args=(u, c), daemon=True).start()
