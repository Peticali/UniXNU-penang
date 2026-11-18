#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Give mobile its own directories in an existing Data seed, in place: the volume UUID (CONFIG_XNU_OWNER_DATA_VOLUME_UUID) is kept.

    sudo python3 scripts/seed-fix-owners.py --unixnu ../UniXNU SEED.dbr

make-data-seed-linux.py created /private/var/mobile/tmp as root (fixed there since): mobile (501) could not create anything in it,
so biomed, callservicesd and nsurlsessiond exited 1 at startup and backboardd waited forever on biomed (u27-disp13; UniXNU's
opi5plus record, round 2, found the same). The seed is unpacked to a sparse image, mounted read-write with linux-apfs-rw, every
directory below mobile/ that root owns is given to 501:501, then it is checked and packed again. The old seed is kept as SEED.dbr.bak.
"""
import argparse, os, subprocess, sys, tempfile
from pathlib import Path

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument('--unixnu', type=Path, required=True)
p.add_argument('seed', type=Path)
args = p.parse_args()
if os.geteuid() != 0:
    p.error('run as root: changing owners and mounting need it')
sys.path.insert(0, str(args.unixnu.resolve() / 'drivers/DarwinBoot/Test'))
import packed_ramdisk
seed = args.seed.resolve()
logical, extents = packed_ramdisk.regions(seed.read_bytes())
with tempfile.TemporaryDirectory(prefix='seed-fix-', dir=seed.parent) as td:
    work = Path(td); raw = work / 'seed.raw'; mnt = work / 'm'; mnt.mkdir()
    with raw.open('wb') as f:
        f.truncate(logical)
        for off, data in extents:
            f.seek(off); f.write(data)
    subprocess.run(['modprobe', 'apfs'], check=True)
    subprocess.run(['mount', '-t', 'apfs', '-o', 'loop,readwrite', str(raw), str(mnt)], check=True)
    changed = []
    try:
        for d in sorted(p for p in (mnt / 'mobile').rglob('*') if p.is_dir() and not p.is_symlink()) + [mnt / 'mobile']:
            st = d.lstat()
            if st.st_uid == 0:
                os.chown(d, 501, 501)
                changed.append(str(d.relative_to(mnt)))
        tmp = mnt / 'mobile/tmp'
        tmp.mkdir(exist_ok=True); os.chown(tmp, 501, 501); tmp.chmod(0o755)
    finally:
        subprocess.run(['umount', str(mnt)], check=True)
    subprocess.run(['fsck.apfs', str(raw)], check=False)
    out = work / 'fixed.dbr'
    packed_ramdisk.pack(raw, out)
    seed.rename(seed.with_suffix('.dbr.bak'))
    out.replace(seed)
owner = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
if all(owner):
    os.chown(seed, int(owner[0]), int(owner[1]))
print('mobile directories given to 501:501:', ', '.join(changed) or 'none besides mobile/tmp')
print('seed', seed, '(old one kept as', seed.with_suffix('.dbr.bak'), ')')
