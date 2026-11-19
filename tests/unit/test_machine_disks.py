"""3-04：体检的分区判断（设计书 4.3）。用造出来的 lsblk、findmnt 输出测，不碰这台电脑的磁盘。"""
import json
import shutil
import subprocess
import unittest

from machine import disks


def dev(name, type_, fstype=None, mounts=(), children=(), tran=None, rm=False, path=None):
    d = {'name': name, 'path': path or (f'/dev/mapper/{name}' if type_ in ('crypt', 'lvm') else f'/dev/{name}'),
         'type': type_, 'fstype': fstype, 'tran': tran, 'rm': rm, 'mountpoints': list(mounts) or [None]}
    if children:
        d['children'] = list(children)
    return d


def disk(name, *children, tran='nvme', rm=False, fstype=None, mounts=()):
    return dev(name, 'disk', fstype=fstype, mounts=mounts, children=children, tran=tran, rm=rm)


def part(name, fstype=None, *mounts, children=()):
    return dev(name, 'part', fstype, mounts, children)


def efi(name):
    return part(name, 'vfat', '/boot/efi')


def tree(*tops):
    return {'blockdevices': list(tops)}


class TestJudge(unittest.TestCase):
    def check(self, lsblk, root, home, kind):
        lay = disks.judge(lsblk, root, home)
        self.assertEqual(lay.kind, kind, disks.describe(lay))
        self.assertTrue(disks.describe(lay))
        return lay

    def test_two_partitions(self):
        """第一种：系统、主目录各一个分区（这台试验电脑就是这样，同一块盘上两个分区）。"""
        t = tree(disk('nvme0n1', efi('nvme0n1p1'), part('nvme0n1p5', 'ext4', '/'), part('nvme0n1p6', 'ext4', '/home')))
        lay = self.check(t, '/dev/nvme0n1p5', '/dev/nvme0n1p6', 'separate')
        self.assertEqual((lay.root, lay.home), (['/dev/nvme0n1p5'], ['/dev/nvme0n1p6']))

    def test_one_partition(self):
        """第二种：只有一个系统分区；/boot、/boot/efi、交换区都不算（W36 在虚拟机里踩过 /boot）。"""
        t = tree(disk('vda', efi('vda15'), part('vda16', 'ext4', '/boot'), part('vda1', 'ext4', '/'),
                      part('vda2', 'swap', '[SWAP]'), tran='virtio'))
        lay = self.check(t, '/dev/vda1', '/dev/vda1', 'single')
        self.assertEqual(lay.others, [])

    def test_third_kind(self):
        """第三种：主目录在系统盘上，后来加的一块盘上有一个 ext4 分区没用上。"""
        t = tree(disk('vda', efi('vda15'), part('vda1', 'ext4', '/'), tran='virtio'),
                 disk('vdb', part('vdb1', 'ext4'), tran='virtio'))
        lay = self.check(t, '/dev/vda1', '/dev/vda1', 'extra')
        self.assertEqual(lay.others, [{'path': '/dev/vdb1', 'fstype': 'ext4', 'mount': ''}])
        self.assertIn('/dev/vdb1（ext4，没挂上）', disks.describe(lay))

    def test_encrypted_two_lvs(self):
        """装系统时选了加密：系统和主目录是同一个加密分区上的两个逻辑卷，名字不同、底下是同一个分区 → 第二种，不是第一种。"""
        lvs = [dev('ubuntu--vg-root', 'lvm', 'ext4', ['/']), dev('ubuntu--vg-home', 'lvm', 'ext4', ['/home']),
               dev('ubuntu--vg-swap', 'lvm', 'swap', ['[SWAP]'])]
        crypt = dev('dm_crypt-0', 'crypt', 'LVM2_member', children=lvs)
        t = tree(disk('nvme0n1', efi('nvme0n1p1'), part('nvme0n1p2', 'ext4', '/boot'),
                      part('nvme0n1p3', 'crypto_LUKS', children=[crypt])))
        lay = self.check(t, '/dev/mapper/ubuntu--vg-root', '/dev/mapper/ubuntu--vg-home', 'single')
        self.assertEqual(lay.root, ['/dev/nvme0n1p3'])
        self.assertEqual(lay.home, ['/dev/nvme0n1p3'])

    def test_encrypted_home_on_other_partition(self):
        """加密加逻辑卷，但主目录那个逻辑卷在另一块盘的分区上 → 第一种。"""
        root_lv = dev('vg0-root', 'lvm', 'ext4', ['/'])
        home_lv = dev('vg1-home', 'lvm', 'xfs', ['/home'])
        t = tree(disk('sda', efi('sda1'), part('sda2', 'crypto_LUKS', children=[dev('c1', 'crypt', 'LVM2_member', children=[root_lv])]), tran='sata'),
                 disk('sdb', part('sdb1', 'crypto_LUKS', children=[dev('c2', 'crypt', 'LVM2_member', children=[home_lv])]), tran='sata'))
        lay = self.check(t, '/dev/mapper/vg0-root', '/dev/mapper/vg1-home', 'separate')
        self.assertEqual((lay.root, lay.home), (['/dev/sda2'], ['/dev/sdb1']))

    def test_btrfs_two_subvolumes(self):
        """btrfs 的两个子卷：来源名带不同的后缀，底下是同一个分区 → 第二种。"""
        t = tree(disk('sda', efi('sda1'), part('sda2', 'btrfs', '/', '/home'), tran='sata'))
        lay = self.check(t, '/dev/sda2[/@]', '/dev/sda2[/@home]', 'single')
        self.assertEqual(lay.root, ['/dev/sda2'])

    def test_whole_disk(self):
        """整块盘不分区直接格式化的，算一个分区：主目录在整块的 vdb 上 → 第一种；另一块整盘没用上 → 第三种。"""
        t = tree(disk('vda', efi('vda15'), part('vda1', 'ext4', '/'), tran='virtio'),
                 disk('vdb', tran='virtio', fstype='ext4', mounts=['/home']))
        lay = self.check(t, '/dev/vda1', '/dev/vdb', 'separate')
        self.assertEqual(lay.home, ['/dev/vdb'])
        t = tree(disk('vda', efi('vda15'), part('vda1', 'ext4', '/'), tran='virtio'),
                 disk('vdc', tran='virtio', fstype='xfs'))
        lay = self.check(t, '/dev/vda1', '/dev/vda1', 'extra')
        self.assertEqual(lay.others[0]['path'], '/dev/vdc')

    def test_usb_disk_reports_not_removable(self):
        """USB 硬盘报「不可移动」：按接口类型认出是移动盘，不算 → 第二种。标了可移动的（U 盘）也不算。"""
        t = tree(disk('nvme0n1', efi('nvme0n1p1'), part('nvme0n1p2', 'ext4', '/')),
                 disk('sda', part('sda1', 'ext4', '/media/u/backup'), tran='usb', rm=False),
                 disk('sdb', part('sdb1', 'ext4'), tran=None, rm=True))
        lay = self.check(t, '/dev/nvme0n1p2', '/dev/nvme0n1p2', 'single')
        self.assertEqual(lay.others, [])

    def test_dual_boot(self):
        """双系统：Windows 的分区（ntfs、微软保留分区）和共用的 efi 都不算 → 第二种（这台电脑的盘上就有）。"""
        t = tree(disk('nvme0n1', efi('nvme0n1p1'), part('nvme0n1p2'), part('nvme0n1p3', 'ntfs'),
                      part('nvme0n1p4', 'ntfs'), part('nvme0n1p5', 'ext4', '/'), part('nvme0n1p6', 'exfat')))
        self.check(t, '/dev/nvme0n1p5', '/dev/nvme0n1p5', 'single')

    def test_cannot_tell(self):
        """认不出来的照实说「看不出来」，不猜。"""
        t = tree(disk('sda', efi('sda1'), part('sda2', 'ext4', '/'), tran='sata'))
        # 主目录在 ZFS 上：来源是存储池里的名字，不是设备
        lay = self.check(t, '/dev/sda2', 'rpool/USERDATA/home_abc', 'unknown')
        self.assertIn('主目录', lay.why)
        # 主目录在内存盘、网络盘上
        self.check(t, '/dev/sda2', 'tmpfs', 'unknown')
        self.check(t, '/dev/sda2', 'server:/export/home', 'unknown')
        # 磁盘列表里根本没有这个设备
        self.check(t, '/dev/sda2', '/dev/sdz9', 'unknown')
        # 系统在回环设备上（试用盘之类），不是真盘
        t2 = tree(dev('loop0', 'loop', 'squashfs', ['/']), disk('sda', part('sda2', 'ext4', '/home'), tran='sata'))
        lay = self.check(t2, '/dev/loop0', '/dev/sda2', 'unknown')
        self.assertIn('系统', lay.why)
        # 跨了两个分区的逻辑卷：主目录的分区和系统的有一部分重叠
        root_lv = dev('vg-root', 'lvm', 'ext4', ['/'])
        home_lv = dev('vg-home', 'lvm', 'ext4', ['/home'])
        t3 = tree(disk('sda', part('sda1', 'LVM2_member', children=[root_lv, home_lv]), tran='sata'),
                  disk('sdb', part('sdb1', 'LVM2_member', children=[home_lv]), tran='sata'))
        lay = self.check(t3, '/dev/mapper/vg-root', '/dev/mapper/vg-home', 'unknown')
        self.assertIn('一部分', lay.why)
        # 什么都没查到
        self.check({}, None, None, 'unknown')

    def test_misc_rules(self):
        """几条零碎的规矩：没打开的加密分区提一句不算；挂在别处的 Linux 分区算「另有」；老版 lsblk 的写法也认。"""
        t = tree(disk('sda', efi('sda1'), part('sda2', 'ext4', '/'), part('sda3', 'crypto_LUKS'),
                      part('sda4', 'xfs', '/data'), tran='sata'))
        lay = self.check(t, '/dev/sda2', '/dev/sda2', 'extra')
        self.assertEqual(lay.others, [{'path': '/dev/sda4', 'fstype': 'xfs', 'mount': '/data'}])
        self.assertTrue(any('/dev/sda3' in n and '加密' in n for n in lay.notes))
        # lsblk 2.37 以前：mountpoint 是一个字符串，rm 是 "0"/"1"
        old = {'blockdevices': [
            {'name': 'sda', 'type': 'disk', 'fstype': None, 'tran': 'sata', 'rm': '0', 'mountpoint': None, 'children': [
                {'name': 'sda1', 'type': 'part', 'fstype': 'ext4', 'rm': '0', 'mountpoint': '/'},
                {'name': 'sda2', 'type': 'part', 'fstype': 'swap', 'rm': '0', 'mountpoint': '[SWAP]'}]},
            {'name': 'sdb', 'type': 'disk', 'fstype': None, 'tran': None, 'rm': '1', 'mountpoint': None,
             'children': [{'name': 'sdb1', 'type': 'part', 'fstype': 'ext4', 'rm': '1', 'mountpoint': None}]},
            {'name': 'zram0', 'type': 'disk', 'fstype': 'swap', 'mountpoint': '[SWAP]'}]}
        self.check(old, '/dev/sda1', '/dev/sda1', 'single')
        # 系统在移动盘上的，如实提一句
        t = tree(disk('sda', part('sda1', 'ext4', '/'), tran='usb'), disk('nvme0n1', part('nvme0n1p1', 'ext4', '/home')))
        lay = self.check(t, '/dev/sda1', '/dev/nvme0n1p1', 'separate')
        self.assertTrue(any('移动盘' in n for n in lay.notes))


class FakeRun:
    """假的 subprocess.run：按命令给造好的输出，记下跑过什么。"""

    def __init__(self, lsblk, mounts, fail=()):
        self.lsblk, self.mounts, self.fail, self.calls = lsblk, mounts, fail, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] in self.fail:
            return subprocess.CompletedProcess(cmd, 1, '', f'{cmd[0]}: 不行')
        if cmd[0] == 'lsblk':
            return subprocess.CompletedProcess(cmd, 0, json.dumps(self.lsblk), '')
        target = cmd[cmd.index('-T') + 1]
        out = {'filesystems': [{'target': target, 'source': self.mounts[target]}]}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), '')


class TestCollect(unittest.TestCase):
    T = tree(disk('sda', efi('sda1'), part('sda2', 'btrfs', '/', '/home'), tran='sata'))

    def test_collect_with_fake_commands(self):
        run = FakeRun(self.T, {'/': '/dev/sda2[/@]', '/home/u': '/dev/sda2[/@home]'})
        lay = disks.collect(home='/home/u', run=run)
        self.assertEqual(lay.kind, 'single')
        # 只跑了这三条只读的命令
        self.assertEqual([c[0] for c in run.calls], ['lsblk', 'findmnt', 'findmnt'])

    def test_commands_fail(self):
        lay = disks.collect(home='/home/u', run=FakeRun(self.T, {}, fail=('lsblk',)))
        self.assertEqual(lay.kind, 'unknown')
        self.assertIn('lsblk', lay.why)
        lay = disks.collect(home='/home/u', run=FakeRun(self.T, {}, fail=('findmnt',)))
        self.assertEqual(lay.kind, 'unknown')

        def missing(cmd, **kw):
            raise FileNotFoundError(cmd[0])
        self.assertEqual(disks.collect(home='/home/u', run=missing).kind, 'unknown')

    @unittest.skipUnless(shutil.which('lsblk') and shutil.which('findmnt'), '没有 lsblk、findmnt')
    def test_this_computer_read_only(self):
        """在跑测试的这台电脑上只读地查一遍：给得出四种之一，不出错。"""
        lay = disks.collect()
        self.assertIn(lay.kind, disks.KIND_TEXT)


if __name__ == '__main__':
    unittest.main()
