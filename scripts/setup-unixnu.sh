#!/bin/sh
# Apply this device's patches to a UniXNU checkout (and its submodules). Safe to run again: a patch already applied
# is skipped. Pull UniXNU first; if a patch no longer applies, it needs a refresh against the new UniXNU.
#   scripts/setup-unixnu.sh [UNIXNU_DIR]        (default ../UniXNU)
# 0006 (AdrenoMetal, GPU work in progress) is opt-in: WITH_GPU=1.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
unixnu=$(cd "${1:-$here/../UniXNU}" && pwd)
apply() {   # apply PATCH DIR
	if git -C "$2" apply --reverse --check "$1" 2>/dev/null; then echo "applied already: $(basename "$1")"
	else git -C "$2" apply "$1" && echo "applied: $(basename "$1")"; fi
}
git -C "$unixnu" submodule update --init drivers/DarwinBoot kits/XnuPrelink drivers/ArmCpu >/dev/null
apply "$here/patches/unixnu/0001-ramdisk-find-payload-inside-initrd.patch" "$unixnu"
apply "$here/patches/unixnu/0003-kernel-xnu-arch-override.patch" "$unixnu"
apply "$here/patches/unixnu/0004-xnuprelink-penang-layout.patch" "$unixnu/kits/XnuPrelink"
apply "$here/patches/unixnu/0005-fileset-reference-linux-host.patch" "$unixnu"
apply "$here/patches/unixnu/0007-xnuprelink-24A446-reviewed-libc-timebase.patch" "$unixnu/kits/XnuPrelink"
apply "$here/patches/unixnu/0008-source-storage-board-kit.patch" "$unixnu"
apply "$here/patches/unixnu/0009-ipsw-aea-linux.patch" "$unixnu"
apply "$here/patches/unixnu/0010-armcpu-virtual-timer-ppi.patch" "$unixnu/drivers/ArmCpu"
apply "$here/patches/unixnu/0011-devicetree-virtual-timer-ppi.patch" "$unixnu"
apply "$here/patches/unixnu/0012-panic-screen-persistent-ring-and-reset.patch" "$unixnu"
apply "$here/patches/unixnu/0013-panic-screen-claim-before-drawing.patch" "$unixnu"
if [ "${WITH_GPU:-0}" = 1 ]; then
	git -C "$unixnu" submodule update --init drivers/AdrenoMetal >/dev/null
	apply "$here/patches/unixnu/0006-adrenometal-penang-gpu-wip.patch" "$unixnu/drivers/AdrenoMetal"
fi
