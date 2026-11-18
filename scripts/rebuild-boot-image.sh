#!/bin/bash
# After a fixture or board change: prelink again, de-PAC, payload, and the RAM boot image for tools/uefi-run.sh.
#   [KARGS="..."] scripts/rebuild-boot-image.sh NAME    -> /mnt/nvme/xnu-build/uefi-holi/stage4/NAME.img
# Also refreshes patches/unixnu/0007 from the XnuPrelink fixture and prints the prelink's unresolved counts.
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
name=${1:?image name}
. "$here/scripts/env.sh"
U=$(cd "$here/../UniXNU" && pwd)
O=$U/out/penang/ipados-27.0.1-24A446/penang
W=/mnt/nvme/xnu-build/uefi-holi/stage4
git -C "$U/kits/XnuPrelink" diff fixtures/fileset-24A446-symbols.json > "$here/patches/unixnu/0007-xnuprelink-24A446-reviewed-libc-timebase.patch"
cd "$U"
./unixnu prelink -D "$here" > "$O/logs/rebuild-prelink.log" 2>&1 || { tail -20 "$O/logs/rebuild-prelink.log"; exit 1; }
python3 - "$O/kernel/kernel.json" <<'EOF'
import json, sys
d = json.load(open(sys.argv[1]))
sites = sum(len(v) for v in d['stubbed'].values())
print(f"prelink: stubbed {sites} sites, {len({a for v in d['stubbed'].values() for a in v})} functions; "
      f"missing {sum(len(v) for v in d['missing'].values())}")
EOF
bash "$here/scripts/kextpac/depac-kernel.sh" "$O" | tail -1
# KARGS="a=1 b=2": extra kernel arguments for this image only (unixnu payload --kernel-arg), e.g. a diagnostic probe.
kargs=(); for a in ${KARGS:-}; do kargs+=(--kernel-arg "$a"); done
# The IPSW's trust caches (StaticTrustCache, Cryptex1 System/App), bundled unchanged by UniXNU's bundle-ipsw-trust.py:
# AMFI validates the root's platform binaries (launchd first) against them. TRUST= overrides, TRUST=none leaves it out.
trust=${TRUST:-$U/out/penang/apple-trust-24A446.bundle}
[ "$trust" != none ] && [ -f "$trust" ] && kargs+=(--trust-cache "$trust")
# The first-install Data seed (scripts/make-data-seed-linux.py); keep it: it is installation state. DATA=none leaves it out.
data=${DATA:-/mnt/nvme/xnu-build/unixnu/seeds/penang-24A446-data.dbr}
[ "$data" != none ] && kargs+=(--data-ramdisk "$data")
./unixnu payload -D "$here" "${kargs[@]}" > "$O/logs/rebuild-payload.log" 2>&1 || { tail -20 "$O/logs/rebuild-payload.log"; exit 1; }
tail -1 "$O/logs/payload-patch.log" | cut -c1-160
PATH=$U/../uefi-penang/Mu_Basecore/BaseTools/Bin/Mu-Basetools_extdep/Linux-x86:$PATH python3 -c "
import sys; sys.path.insert(0, 'scripts')
from unixnu import ramdisk
ramdisk.encode('$O/payload/payload.img', '$W/payload.packed')"
python3 -I "/mnt/nvme/moto g53/xnu-port/ios-penang/penang/tools/mkbootimg_v3.py" --kernel "$W/kernel-fd.bin" \
	--ramdisk "$W/payload.packed" -o "$W/$name.img" | tail -1
