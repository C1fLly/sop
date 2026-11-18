# 样例的 setup.sh 共用的几个小函数（bash）。用法：. "$TOOLKIT/checks/samples.sh"
repo() {  # repo <目录>：建一个普通仓库，main 上一个初始提交
  git init -q -b main "$1"; echo 初始 > "$1/README.md"; git -C "$1" add -A; git -C "$1" commit -qm 初始
}
put() {   # put <仓库> <路径> <内容>：写文件（自动建目录）
  mkdir -p "$(dirname "$1/$2")"; printf '%s\n' "$3" > "$1/$2"
}
commit() { git -C "$1" add -A; git -C "$1" commit -qm "${2:-改动}"; }
head() { git -C "$1" rev-parse HEAD; }
blob() { git -C "$1" rev-parse "$2:$3"; }
