#!/bin/bash
# 第一段 W36：体检里「主目录在哪个分区」这一项的试验原型（设计书 4.3 的表）。只读，不改动任何分区。
root=$(findmnt -no SOURCE /); home=$(findmnt -no SOURCE -T "$HOME")
rootdisk=$(lsblk -no PKNAME "$root" 2>/dev/null | head -1)
# 「能用的 Linux 分区」：真盘上的分区（不是移动盘），Linux 自己的格式；不算系统自己在用的（/、/boot、/boot/efi、交换区）
others=()
while read -r name type fstype rm mnt; do
  [ "$type" = part ] || continue; [ "$rm" = 1 ] && continue
  case "$fstype" in ext4|xfs|btrfs) ;; *) continue ;; esac
  case "$mnt" in /|/boot|/boot/efi|"[SWAP]") continue ;; esac
  [ "/dev/$name" = "$root" ] && continue; [ "/dev/$name" = "$home" ] && continue
  others+=("/dev/$name（${fstype}，${mnt:-没挂上}）")
done < <(lsblk -rno NAME,TYPE,FSTYPE,RM,MOUNTPOINTS)
echo "系统在 $root；主目录在 $home"
if [ "$home" != "$root" ]; then echo "结论：合格，主目录不在系统盘上（4.3 表的第一种）"
elif [ ${#others[@]} -eq 0 ]; then echo "结论：合格，整台电脑只有一个能用的 Linux 分区，所有内容都装进 ~/tools（第二种）"
else echo "结论：合格，照常装在主目录下。如实提一句：这台电脑主目录在系统盘上，另有分区没用上：${others[*]}（第三种）"; fi
