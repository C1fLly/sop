import ctypes, os
libc = ctypes.CDLL(None, use_errno=True)
def trial(m, gid=False):
    r1, w1 = os.pipe(); r2, w2 = os.pipe(); pid = os.fork()
    if pid == 0:
        libc.unshare(0x10000000); os.write(w1, os.readlink('/proc/self').encode()); os.read(r2, 1); os._exit(0)
    cp = os.read(r1, 20).decode()
    try:
        fd = os.open(f'/proc/{cp}/uid_map', os.O_WRONLY); os.write(fd, m.encode()); os.close(fd); res = '写成了'
    except OSError as e: res = f'写不进（{e.strerror}）'
    os.write(w2, b'1'); os.waitpid(pid, 0); print(repr(m), res)
for m in ('0 0 65537\n', '0 0 65536\n', '0 0 2\n', '1 1 1\n', '0 0 1\n1 1 65536\n', '0 0 1\n1 1 1000\n'): trial(m)
