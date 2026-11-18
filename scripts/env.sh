# Source before running ../UniXNU/unixnu: the UniXNU Linux toolchain installed on the NVMe without root
# (setup-toolchain.py with its /usr/bin shims redirected to <prefix>/bin).
export UNIXNU_TOOLCHAIN=${UNIXNU_TOOLCHAIN:-/mnt/nvme/xnu-build/unixnu/toolchain/prefix}
export PATH="$UNIXNU_TOOLCHAIN/bin:$PATH"
export TMPDIR=${TMPDIR:-/mnt/nvme/xnu-build/unixnu/toolchain/tmp}
