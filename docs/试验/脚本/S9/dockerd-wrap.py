#!/usr/bin/python3
"""试验用：在 Docker 自己的隔离空间里，先把根目录换成一个只含白名单的目录，再启动 dockerd。
这样 dockerd 以及它启动的一切容器，都只看得到白名单里的东西。"""
import ctypes, os, subprocess, sys
H = "/home/sanchuanzl"; R = "/tmp/sop-spike-s9"; RD = R + "/rd"; NR = R + "/rd-newroot"; PROJ = R + "/proj"
def sh(*a): subprocess.run(a, check=True)
def ro(p): sh("mount", "--bind", p, p); sh("mount", "-o", "remount,bind,ro", p)
sh("mount", "-t", "tmpfs", "-o", "mode=755", "tmpfs", NR)
for d in ("usr", "etc", "proc", "sys", "dev", "run", "tmp", "var/lib", "var/tmp", ".old"): os.makedirs(f"{NR}/{d}")
for l in ("bin", "lib", "lib64", "sbin"): os.symlink("usr/" + l, f"{NR}/{l}")
os.symlink("/run", f"{NR}/var/run")
for d in ("usr", "etc", "proc", "sys", "dev"): sh("mount", "--rbind", "/" + d, f"{NR}/{d}")
sh("mount", "-o", "remount,bind,ro", f"{NR}/usr")
sh("mount", "-t", "tmpfs", "tmpfs", f"{NR}/dev/shm")          # 不给宿主机的共享内存
sh("mount", "-t", "tmpfs", "tmpfs", f"{NR}/run")              # 全新的 /run：没有钥匙串、SSH 代理、原 Docker 的通道
sh("mount", "-t", "tmpfs", "-o", "mode=1777", "tmpfs", f"{NR}/tmp")
# 白名单：Docker 的程序（只读）、本试验专用的数据和运行目录、试验项目
for src, mode in ((H + "/tools/docker/bin", "ro"), (RD, "rw"), (PROJ, "rw"), (R + "/cache", "rw")):
    os.makedirs(NR + src); sh("mount", "--rbind", src, NR + src)
    if mode == "ro": sh("mount", "-o", "remount,bind,ro", NR + src)
# 项目里：.git 整个只读；每个工作目录里指向 .git 的小文件只读
ro(f"{NR}{PROJ}/.git")
for w in os.listdir(PROJ):
    f = f"{NR}{PROJ}/{w}/.git"
    if os.path.isfile(f): ro(f)
# 换根，并把旧的根彻底摘掉
libc = ctypes.CDLL(None, use_errno=True)
os.chdir(NR)
if libc.syscall(155, b".", b".old") != 0: raise OSError(ctypes.get_errno(), "pivot_root 失败")
if libc.umount2(b"/.old", 2) != 0: raise OSError(ctypes.get_errno(), "摘掉旧根失败")
os.chdir("/"); os.rmdir("/.old")
os.execv(H + "/tools/docker/bin/dockerd", ["dockerd"] + sys.argv[1:])
