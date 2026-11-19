"""体检：主目录在哪个分区（设计书 4.3，任务 3-04）。只读：只跑 lsblk、findmnt，不格式化、不挂载、不改动任何分区。

结论四种：
- separate  主目录不在系统盘上（4.3 表的第一种，合格）
- single    整台电脑只有一个能用的 Linux 分区（第二种，合格）
- extra     主目录在系统盘上，另外还有能用的 Linux 分区（第三种，合格，报告里如实提一句）
- unknown   看不出来（照实报告，不猜）

做法：
- **比的是底下实际的分区，不是名字。** 系统（/）和主目录各自挂的设备，顺着加密层、逻辑卷、RAID 往下（lsblk 树里往上）
  找到真盘上的分区；整块盘不分区直接用的，整块盘算一个分区。btrfs 子卷的来源名带着 `[/@home]` 这种后缀，去掉再找。
  两边的分区完全一样算「同一个」，完全不相交算「不同」，有一部分重叠或者有一边找不到，都算「看不出来」。
- 「能用的 Linux 分区」：真盘上、Linux 自己格式的分区。不算 Windows 的分区（ntfs、vfat、exfat）、移动盘、
  系统自己在用的（/、/boot、/boot/efi、/efi、交换区），也不算系统和主目录所在的分区。
- 移动盘按接口类型认（usb、火线），不靠「可移动」标记（很多 USB 硬盘报的是不可移动）；标了可移动的也算移动盘。
- 加密了没打开的分区看不出里面是什么，不算进去，在报告里提一句。
"""
import json
import os
import subprocess
from dataclasses import dataclass, field

LINUX_FS = {'ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'f2fs', 'jfs', 'reiserfs', 'bcachefs'}
SYSTEM_MOUNTS = {'/', '/boot', '/boot/efi', '/efi', '[SWAP]'}
REMOVABLE_TRAN = {'usb', 'ieee1394'}
NOT_REAL_DISK = ('zram', 'ram', 'loop', 'nbd')  # 内存盘、回环设备之类，不是真盘
LSBLK = ['lsblk', '-J', '-o', 'NAME,PATH,TYPE,FSTYPE,TRAN,RM,MOUNTPOINTS']
KIND_TEXT = {
    'separate': '合格：主目录不在系统盘上',
    'single': '合格：整台电脑只有一个能用的 Linux 分区，所有内容都装进 ~/tools 目录（tools 在系统盘上是没有办法的事）',
    'extra': '合格：主目录在系统盘上，照常装在主目录下',
    'unknown': '看不出来主目录和系统是不是在同一个分区上',
}


@dataclass
class Layout:
    kind: str                                    # separate / single / extra / unknown
    root: list = field(default_factory=list)     # 系统所在的实际分区
    home: list = field(default_factory=list)     # 主目录所在的实际分区
    others: list = field(default_factory=list)   # 另外能用的 Linux 分区：{'path', 'fstype', 'mount'}
    notes: list = field(default_factory=list)    # 要如实提一句的事
    why: str = ''                                # 看不出来的原因


def _flag(v):
    return v is True or str(v).strip().lower() in ('1', 'true')


def _mounts(node):
    """lsblk 2.37 起是 mountpoints（列表），以前是 mountpoint（一个）。没挂的写成 null。"""
    if 'mountpoints' in node:
        ms = node['mountpoints'] or []
    else:
        ms = [node.get('mountpoint')]
    return [m for m in ms if m]


def _walk(nodes, chain=()):
    """把 lsblk 的树摊平：每个设备连同它从真盘往下的一串（同一个设备挂在几个上层下面时出现几次）。"""
    for n in nodes or []:
        c = chain + (n,)
        yield c
        yield from _walk(n.get('children'), c)


def _is_real_disk(top):
    return top.get('type') == 'disk' and not str(top.get('name', '')).startswith(NOT_REAL_DISK)


def _is_removable(top):
    return str(top.get('tran') or '').lower() in REMOVABLE_TRAN or _flag(top.get('rm'))


def _base(chain):
    """一串里真盘上的那个分区；整块盘不分区直接用的，就是盘本身。"""
    if len(chain) > 1 and chain[1].get('type') == 'part':
        return chain[1]
    return chain[0]


def _path(node):
    return node.get('path') or f"/dev/{node.get('name')}"


def source_device(source):
    """findmnt 的来源名去掉 btrfs 子卷的后缀：/dev/sda2[/@home] → /dev/sda2。"""
    s = (source or '').strip()
    if s.endswith(']') and '[' in s:
        s = s[:s.rindex('[')]
    return s


def _bases_of(chains, source):
    """来源名对应的实际分区（路径的集合）；找不到、或者不在真盘上，返回 None。"""
    dev = source_device(source)
    if not dev.startswith('/dev/'):
        return None
    found = [c for c in chains if dev in (_path(c[-1]), f"/dev/{c[-1].get('name')}", f"/dev/mapper/{c[-1].get('name')}")]
    if not found or not all(_is_real_disk(c[0]) for c in found):
        return None
    return {_path(_base(c)) for c in found}


def judge(lsblk, root_source, home_source):
    """lsblk：`lsblk -J` 的结果（已解析）；root_source、home_source：findmnt 给的系统、主目录的来源名。"""
    chains = list(_walk((lsblk or {}).get('blockdevices')))
    root = _bases_of(chains, root_source)
    home = _bases_of(chains, home_source)
    if root is None or home is None:
        which = '系统' if root is None else '主目录'
        src = root_source if root is None else home_source
        return Layout('unknown', sorted(root or []), sorted(home or []),
                      why=f'{which}挂的是「{src or "（没查到）"}」，在磁盘列表里找不到它底下是哪块真盘上的哪个分区')
    lay = Layout('separate', sorted(root), sorted(home))
    if root & home and root != home:
        lay.kind = 'unknown'
        lay.why = '系统和主目录底下的分区有一部分是同一个、有一部分不是（多半是跨了几个分区的逻辑卷或 RAID）'
        return lay

    # 另外能用的 Linux 分区：每块真盘上的每个分区；盘上没有分区的，整块盘算一个
    seen = set()
    for top in (lsblk or {}).get('blockdevices') or []:
        if not _is_real_disk(top):
            continue
        tops = list(_walk([top]))
        removable = _is_removable(top)
        for path in sorted(root | home):
            if removable and any(_path(_base(c)) == path for c in tops):
                lay.notes.append(f'{"系统" if path in root else "主目录"}在移动盘上（{path}）')
        parts = [n for n in top.get('children') or [] if n.get('type') == 'part']
        for cand in parts or [top]:
            p = _path(cand)
            if p in seen or p in root or p in home or removable:
                continue
            seen.add(p)
            sub = [c[-1] for c in _walk([cand])]
            if any(m in SYSTEM_MOUNTS for n in sub for m in _mounts(n)):
                continue
            linux = [n for n in sub if n.get('fstype') in LINUX_FS]
            if linux:
                ms = [m for n in linux for m in _mounts(n)]
                lay.others.append({'path': p, 'fstype': linux[0]['fstype'], 'mount': ms[0] if ms else ''})
            elif any(n.get('fstype') == 'crypto_LUKS' and not n.get('children') for n in sub):
                lay.notes.append(f'{p} 是加密的、没打开，看不出里面是什么，没算进去')

    if root != home:
        lay.kind = 'separate'
    elif lay.others:
        lay.kind = 'extra'
    else:
        lay.kind = 'single'
    return lay


def describe(lay):
    """大白话的几行，给体检报告用（3-06）。"""
    lines = [KIND_TEXT[lay.kind] + '。']
    if lay.root or lay.home:
        lines.append(f'系统在 {"、".join(lay.root) or "（看不出来）"}；主目录在 {"、".join(lay.home) or "（看不出来）"}。')
    if lay.kind == 'extra':
        lst = '；'.join(f"{o['path']}（{o['fstype']}，{'挂在 ' + o['mount'] if o['mount'] else '没挂上'}）" for o in lay.others)
        lines.append(f'这台电脑主目录在系统盘上，另有分区没用上：{lst}。不挡流程，不用处理。')
    if lay.kind == 'unknown':
        lines.append(f'原因：{lay.why}。工具包照常装在主目录下，不猜。')
    lines += [n + '。' for n in lay.notes]
    return '\n'.join(lines)


def _findmnt_source(run, target):
    r = run(['findmnt', '-J', '-o', 'TARGET,SOURCE', '-T', target], capture_output=True, text=True, timeout=30)
    if r.returncode != 0:
        return None
    fs = json.loads(r.stdout).get('filesystems') or []
    return fs[-1].get('source') if fs else None


def collect(home=None, run=subprocess.run):
    """在这台电脑上只读地查一遍，返回 Layout。run 换成假的就能在测试里造输出。"""
    home = home or os.path.expanduser('~')
    try:
        r = run(LSBLK, capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            return Layout('unknown', why=f'lsblk 没跑成功：{(r.stderr or "").strip() or r.returncode}')
        lsblk = json.loads(r.stdout)
        root_src = _findmnt_source(run, '/')
        home_src = _findmnt_source(run, home)
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        return Layout('unknown', why=f'查磁盘的命令没跑成功：{e}')
    return judge(lsblk, root_src, home_src)


if __name__ == '__main__':
    print(describe(collect()))
