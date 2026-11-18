#!/bin/sh
# Fetch the kernelcache of the board's UniXNU OS profile (only that member of the IPSW, by HTTP range) and check its pin.
# The prelink uses it unchanged, as UniXNU does; the finished kernel.macho is rewritten without PAC afterwards.
# Needs the ipsw tool (blacktop/ipsw).    scripts/kextpac/make-kernelcache.sh OUT_DIR [PROFILE]
set -eu
here=$(cd "$(dirname "$0")" && pwd)
out=${1:?OUT_DIR}; profile=${2:-ipados-27.0.1-24A446}
toml="$here/../../../UniXNU/profiles/os/$profile/profile.toml"
url=$(sed -n 's/^"url" = "\(.*\)"/\1/p' "$toml" | head -1)
pin=$(sed -n 's/^"kernelcache_sha256" = "\([0-9a-f]*\)".*/\1/p' "$toml" | head -1)
ipsw extract --kernel --remote "$url" -o "$out"
kc=$(find "$out" -name 'kernelcache.release.*' | head -1)
echo "$pin  $kc" | sha256sum -c -
echo "export UNIXNU_KERNELCACHE=$kc"
