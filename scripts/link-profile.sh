#!/bin/sh
# Expose this repository's OS profile to a UniXNU checkout (an untracked symlink: `git pull` in UniXNU stays clean).
#   scripts/link-profile.sh [UNIXNU_DIR]     (default ../UniXNU)
set -eu
here=$(cd "$(dirname "$0")/.." && pwd)
unixnu=${1:-$here/../UniXNU}
for p in "$here"/profiles/os/*/; do
	name=$(basename "$p")
	ln -sfn "$p" "$unixnu/profiles/os/$name"
	echo "profiles/os/$name -> $p"
done
