# 共用的一小段（3-56）：用 apt-get 装系统软件包时，等住软件包的锁。不单独运行，由要管理员权限的那一小段脚本先载入再用：
#   machine/install.py、machine/install/docker-rootless.sh 读这个文件；bootstrap.sh 要单独运行，里面抄了一份，
#   单元测试核对两份一字不差。只用 sh 的写法（install.py、bootstrap.sh 用 sh -c 跑，docker-rootless.sh 用 bash 跑）。
#
# 刚开机时系统常常正在自己更新软件（apt-daily、unattended-upgrades），占着软件包的锁。apt 的 DPkg::Lock::Timeout
# 只管 dpkg 的锁；apt-get update 要的 /var/lib/apt/lists/lock、下载要的 /var/cache/apt/archives/lock 拿不到就立刻报错退出
# （退出码 100，虚拟机里试过，apt 3.2.1）。所以这里自己等：报错里提到这几把锁，就隔 5 秒再试，
# 一共最多等 SOP_APT_WAIT 秒（默认 600，即 10 分钟），等不到退出码 75，上面认出 75 说「系统正在自己更新软件」。
# 报错里的锁文件路径不随系统语言变，所以按路径认。apt 正常的输出扔掉，报错和警告照原样打出来。
sop_apt() {
  _sop_limit=${SOP_APT_WAIT:-600} _sop_start=$(date +%s) _sop_said=0
  while :; do
    _sop_err=$(apt-get "$@" 2>&1 >/dev/null) && { [ -z "$_sop_err" ] || printf '%s\n' "$_sop_err" >&2; return 0; }
    _sop_rc=$?
    case $_sop_err in
      *'/var/lib/apt/lists/lock'*|*'/var/cache/apt/archives/lock'*|*'/var/lib/dpkg/lock'*) ;;
      *) printf '%s\n' "$_sop_err" >&2; return $_sop_rc ;;
    esac
    _sop_used=$(( $(date +%s) - _sop_start ))
    if [ "$_sop_used" -ge "$_sop_limit" ]; then
      printf '%s\n' "$_sop_err" >&2
      echo "等了 $(( (_sop_used + 59) / 60 )) 分钟，系统自己的软件更新还没做完，还占着软件包的锁。" >&2
      return 75
    fi
    if [ "$_sop_said" = 0 ]; then
      echo "系统正在自己更新软件（刚开机时常有），占着软件包的锁。等它做完再接着装，最多等 $(( (_sop_limit + 59) / 60 )) 分钟……" >&2
      _sop_said=60
    elif [ "$_sop_used" -ge "$_sop_said" ]; then
      echo "还在等系统自己的软件更新（已经等了 $(( _sop_used / 60 )) 分钟）……" >&2
      _sop_said=$(( _sop_said + 60 ))
    fi
    sleep 5
  done
}
