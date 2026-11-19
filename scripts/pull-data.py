#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Rebuild the iPadOS Data volume of the last boot from the seed and the persistent store on userdata, read over UMS.

    python3 scripts/pull-data.py [--dev /dev/sdX] [--seed SEED.dbr] [--out DIR] [--mount]

The phone runs ums/out/penang-ums-auto.img (tools/uefi-run.sh boots it after each run), which exposes userdata as a USB disk
(serial penang-ums, the 112 GiB one). NativeRamBlock's store window (PersistOverlay.h: "SHNGDATA" header, bitmap, pages) lies
at the end of userdata, below the 1 GiB log reserve (ShengUfs native_ufs_store_open). Seed pages + overlay pages = Data, a sparse
raw APFS image in OUT/data.raw; with --mount it is mounted read-only with apfs-fuse at OUT/m and launchd's logs are copied to OUT.
It survives the PMIC cold reset that wipes the ramoops ring. With log=1 the console ring the board copies to the UFS log window
(every round and from the panic screen) goes to OUT/ufs-ring.txt too. Reads only; needs no root (the UMS disk belongs to the user).
"""
import argparse
import shutil
import struct
import subprocess
import sys
from pathlib import Path

UNIXNU = Path(__file__).resolve().parents[2] / 'UniXNU'
USERDATA_BYTES = 120328269824          # board.toml [userdata]: 29377019 blocks of 4096
RESERVE_BLOCKS = 1024 * 256            # ShengUfs default log-reserve, 1024 MiB


def ums_disk():
    out = subprocess.run(['lsblk', '-dbno', 'NAME,SIZE,SERIAL'], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[2] == 'penang-ums' and int(parts[1]) == USERDATA_BYTES:
            return '/dev/' + parts[0]
    sys.exit('no penang-ums userdata disk: boot ums/out/penang-ums-auto.img first')


LOG_RESERVE_BLOCKS = 8192              # ShengUfs kLogReserveBlocks: the log window, the last 32 MiB of userdata (log=1)
RING_BYTES = 0x40000                   # penang_pram_va: {u32 "DBGC", u32 start, u32 size} then the ring


def dump_ufs_ring(dev, out):
    """The console ring the board copies to the UFS log window every round and from the panic screen (log=1): OUT/ufs-ring.txt."""
    first = USERDATA_BYTES // 4096 - LOG_RESERVE_BLOCKS
    with open(dev, 'rb') as disk:
        disk.seek(first * 4096)
        ring = disk.read(RING_BYTES)
    sig, start, size = struct.unpack_from('<III', ring, 0)
    data = ring[12:]
    if sig != 0x43474244 or start >= len(data) or size > len(data):
        print(f'no console ring in the UFS log window (block {first}; boot with log=1)')
        return
    text = data[start:size] + data[:start] if size == len(data) else data[:size]
    path = out / 'ufs-ring.txt'
    path.write_bytes(text)
    print(f'UFS console ring: {len(text)} bytes -> {path}')


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--dev')
    p.add_argument('--seed', type=Path, default=Path('/mnt/nvme/xnu-build/unixnu/seeds/penang-24A446-data.dbr'))
    p.add_argument('--out', type=Path, default=Path('/mnt/nvme/xnu-build/unixnu/data-pull'))
    p.add_argument('--mount', action='store_true')
    args = p.parse_args()
    sys.path.insert(0, str(UNIXNU / 'drivers/DarwinBoot/Test'))
    import packed_ramdisk
    logical, extents = packed_ramdisk.regions(args.seed.read_bytes())
    pages = logical // 4096
    bitmap_blocks = (pages + 32767) // 32768
    first = USERDATA_BYTES // 4096 - RESERVE_BLOCKS - (1 + bitmap_blocks + pages)
    dev = args.dev or ums_disk()
    args.out.mkdir(parents=True, exist_ok=True)
    dump_ufs_ring(dev, args.out)
    mnt = args.out / 'm'
    subprocess.run(['fusermount3', '-u', str(mnt)], capture_output=True)
    with open(dev, 'rb') as disk:
        disk.seek(first * 4096)
        header = disk.read(4096)
        if header[:8] != b'SHNGDATA' or struct.unpack_from('<Q', header, 16)[0] != pages:
            sys.exit(f'{dev}: no store of this seed at block {first} (header {header[:8]!r}); Data ran from the seed alone')
        bitmap = disk.read(bitmap_blocks * 4096)
        changed = [i * 8 + k for i, b in enumerate(bitmap) if b for k in range(8) if b >> k & 1]
        raw = args.out / 'data.raw'
        with raw.open('wb') as out:
            out.truncate(logical)
            for offset, data in extents:
                out.seek(offset)
                out.write(data)
            for index in changed:
                disk.seek((first + 1 + bitmap_blocks + index) * 4096)
                out.seek(index * 4096)
                out.write(disk.read(4096))
    print(f'store generation {struct.unpack_from("<I", header, 56)[0]}, {len(changed)} changed pages -> {raw}')
    if args.mount:
        mnt.mkdir(exist_ok=True)
        subprocess.run(['apfs-fuse', str(raw), str(mnt)], check=True)
        logs = mnt / 'root/log/com.apple.xpc.launchd'
        for log in sorted(logs.glob('*.log')) if logs.is_dir() else []:
            shutil.copy(log, args.out / log.name)
            print(f'{args.out / log.name}')


if __name__ == '__main__':
    main()
