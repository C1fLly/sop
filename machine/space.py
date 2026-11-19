"""体检：系统盘、主目录所在的分区还剩多少空间（设计书 4.3、W39，任务 3-05）。只读：只看剩余空间，不删任何东西。

提醒线（W39，用户 2026-11-19 定）：
- 系统盘（/ 所在的那个文件系统）剩不到 10 GB 时提醒；
- 主目录所在的那个文件系统剩不到 20 GB 时提醒；
- 两个是同一个文件系统时（第二、三种电脑，4.3），只报一行，按 20 GB。

「同一个」按文件系统算，不按底下的分区算：装系统时选了加密，系统和主目录多半是同一个分区上的两个逻辑卷，
各有各的剩余空间，一个满了不会吃掉另一个的，所以各按各的线（分区判断那边按底下的分区比，是另一回事，见 disks.py）。
btrfs 的子卷共用一个池子，算同一个。

GB 按 10 的 9 次方字节算，和 Ubuntu 的「磁盘使用情况」显示的一样。剩余空间按普通用户能用的算（不含留给管理员的那一块）。
低于提醒线时指向 `sop machine clean`（8.5，第 3 期做，W31）；只提醒，不挡流程。
"""
import os
import subprocess
from dataclasses import dataclass

from . import disks

GB = 1000 ** 3
SYSTEM_MIN = 10 * GB
HOME_MIN = 20 * GB
WHY_LOW = {
    'system': '系统盘满了，Ubuntu 可能进不了桌面',
    'home': '主目录这边满了，镜像、依赖缓存、数据库都写不进去，项目会跑不起来',
    'both': '系统和主目录在同一个分区上，满了 Ubuntu 可能进不了桌面，项目也会跑不起来',
}
CLEAN_HINT = ('可以执行 sop machine clean，看看各项目的镜像、依赖缓存、运行日志各占多少、选了再删'
              '（这个命令第 3 期才做好，在那之前先自己删掉不要的大文件，拿不准的问维修窗口）')
NAMES = {'system': '系统盘', 'home': '主目录所在的分区', 'both': '系统盘（主目录也在上面）'}


@dataclass
class Space:
    which: str            # system / home / both
    path: str             # 查的是哪个位置（/ 或主目录）
    minimum: int          # 提醒线（字节）
    free: int = None      # 剩余（字节）；查不出来是 None
    total: int = None
    error: str = ''

    @property
    def low(self):
        return self.free is not None and self.free < self.minimum


def gb(n):
    """字节换成大白话的 GB，留一位小数。"""
    return f'{n / GB:.1f} GB'


def _statvfs(path, statvfs):
    try:
        st = statvfs(path)
    except OSError as e:
        return None, None, f'查不出来（{e.strerror or e}）'
    return st.f_bavail * st.f_frsize, st.f_blocks * st.f_frsize, ''


def same_filesystem(root, home, run=subprocess.run, stat=os.stat):
    """系统和主目录是不是同一个文件系统。设备号一样就是；不一样时再看 findmnt 的来源名
    （btrfs 每个子卷的设备号都不一样，来源名去掉子卷的后缀后是同一个）。查不出来按「不是同一个」，两边各报一行，不会少报。"""
    try:
        if stat(root).st_dev == stat(home).st_dev:
            return True
    except OSError:
        return False
    try:
        a, b = disks._findmnt_source(run, root), disks._findmnt_source(run, home)
    except (OSError, subprocess.SubprocessError, ValueError):
        return False
    return bool(a and b) and disks.source_device(a) == disks.source_device(b)


def check(home=None, statvfs=os.statvfs, same=None, run=subprocess.run):
    """只读地查一遍，返回 [Space]：同一个文件系统一项，否则两项（系统盘在前）。same 给了就不再自己判断（测试用）。"""
    home = home or os.path.expanduser('~')
    if same is None:
        same = same_filesystem('/', home, run=run)
    wanted = [('both', home, HOME_MIN)] if same else [('system', '/', SYSTEM_MIN), ('home', home, HOME_MIN)]
    out = []
    for which, path, minimum in wanted:
        free, total, err = _statvfs(path, statvfs)
        out.append(Space(which, path, minimum, free, total, err))
    return out


def describe(spaces):
    """大白话的几行，给体检报告用（3-06）。"""
    lines = []
    for s in spaces:
        name = f'{NAMES[s.which]}（{s.path}）'
        if s.free is None:
            lines.append(f'{name}剩多少空间{s.error}。')
        elif s.low:
            lines.append(f'要注意：{name}只剩 {gb(s.free)}（共 {gb(s.total)}），低于 {s.minimum // GB} GB 的提醒线。'
                         f'{WHY_LOW[s.which]}。{CLEAN_HINT}。')
        else:
            lines.append(f'{name}还剩 {gb(s.free)}（共 {gb(s.total)}），够用（低于 {s.minimum // GB} GB 时提醒）。')
    return '\n'.join(lines)


def any_low(spaces):
    return any(s.low for s in spaces)


if __name__ == '__main__':
    print(describe(check()))
