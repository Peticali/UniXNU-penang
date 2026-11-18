# Source before running ../UniXNU/unixnu: the UniXNU Linux toolchain installed on the NVMe without root
# (setup-toolchain.py with its /usr/bin shims redirected to <prefix>/bin).
export UNIXNU_TOOLCHAIN=${UNIXNU_TOOLCHAIN:-/mnt/nvme/xnu-build/unixnu/toolchain/prefix}
export PATH="$UNIXNU_TOOLCHAIN/bin:$PATH"
export TMPDIR=${TMPDIR:-/mnt/nvme/xnu-build/unixnu/toolchain/tmp}


# The profile's original kernelcache (scripts/kextpac/make-kernelcache.sh fetches it; the prelink checks its pin).
export UNIXNU_KERNELCACHE=${UNIXNU_KERNELCACHE:-/mnt/nvme/xnu-build/ios26/kc/24A446__iPad17,3/24A446__iPad17,1_2_3_4/kernelcache.release.iPad17,1_2_3_4}
