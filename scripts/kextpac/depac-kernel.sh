#!/bin/sh
# Rewrite the prelinked kernel.macho (UniXNU's arm64e kernel + Apple's kexts, an MH_FILESET) without PAC for the
# SM4350, in place, between "unixnu kernel" and "unixnu payload". The original is kept as kernel.macho.pac.
#   scripts/kextpac/depac-kernel.sh [OUT_DIR]    (default ../UniXNU/out/penang/ipados-27.0.1-24A446/penang)
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:-$here/../../../UniXNU/out/penang/ipados-27.0.1-24A446/penang}
k=$out/kernel/kernel.macho
[ -f "$k.pac" ] && [ "$k" -ot "$k.pac" ] && { echo "already rewritten: $k"; exit 0; }
cp "$k" "$k.pac"
python3 -I "$here/depac_kc.py" "$k.pac" "$k" --with-kernel
sha256sum "$k"
