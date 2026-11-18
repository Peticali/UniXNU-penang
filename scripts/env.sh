# Source before running ../UniXNU/unixnu: the UniXNU Linux toolchain installed on the NVMe without root
# (setup-toolchain.py with its /usr/bin shims redirected to <prefix>/bin).
export UNIXNU_TOOLCHAIN=${UNIXNU_TOOLCHAIN:-/mnt/nvme/xnu-build/unixnu/toolchain/prefix}
export PATH="$UNIXNU_TOOLCHAIN/bin:$PATH"
export TMPDIR=${TMPDIR:-/mnt/nvme/xnu-build/unixnu/toolchain/tmp}
# The iPhone12,1 26.6.2 (23G90) IPSW, when this machine has it (otherwise the profile's URL).
[ -f /mnt/nvme/xnu-build/ios26/ipsw/iPhone12,1_26.6.2_23G90_Restore.ipsw ] && export UNIXNU_IPSW=${UNIXNU_IPSW:-/mnt/nvme/xnu-build/ios26/ipsw/iPhone12,1_26.6.2_23G90_Restore.ipsw}
