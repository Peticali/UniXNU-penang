#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Write a UniXNU userdata image (`unixnu userdata`: SHNGROOT manifest, OS/SystemOS windows, data objects) to the
moto g53's userdata partition, exposed over USB by the penang UMS gadget in read-write mode.

    fastboot boot penang/ums/out/penang-ums-rw.img          (in the penang tools tree)
    scripts/flash-userdata.py IMAGE /dev/disk/by-id/usb-...penang-ums-0:0

penang's ABL refuses `fastboot flash userdata`, so the image goes over UMS, as tools/ios26/flash-root.py did for the
HFS+ root. The same guards: DEVICE must be the gadget's by-id path (serial penang-ums) at the g53 userdata size
(120328269824 bytes), and the image must fit. The first MiB (the manifest block) is written last, so an interrupted
write never leaves a valid-looking SHNGROOT manifest in front of partial windows. Every byte is then read back from
the device (its page cache dropped first) and compared by SHA-256 in 64 MiB chunks.
"""
import hashlib
import os
import sys

USERDATA_SIZE = 120328269824
MIB = 1 << 20
CHUNK = 64 * MIB


def main():
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    image, device = sys.argv[1], sys.argv[2]
    if 'penang-ums' not in device or not device.startswith('/dev/disk/by-id/'):
        sys.exit(f'{device}: use the gadget\'s /dev/disk/by-id/...penang-ums... path')
    fi = os.open(image, os.O_RDONLY)
    fd = os.open(device, os.O_RDWR)
    size = os.lseek(fd, 0, os.SEEK_END)
    if size != USERDATA_SIZE:
        sys.exit(f'{device}: {size} bytes, not the g53 userdata ({USERDATA_SIZE}): refused')
    total = os.fstat(fi).st_size
    if total > size or total < 2 * MIB:
        sys.exit(f'{image}: {total} bytes does not fit the partition')
    head = os.pread(fi, MIB, 0)
    if head[:8] != b'SHNGROOT':
        sys.exit(f'{image}: no SHNGROOT manifest at offset 0: not a unixnu userdata image')
    print(f'writing {total / 2**30:.2f} GiB to {device} (manifest block last)', flush=True)
    offset, reported = MIB, 0
    while offset < total:
        data = os.pread(fi, min(CHUNK, total - offset), offset)
        os.pwrite(fd, data, offset)
        offset += len(data)
        if offset - reported >= 1 << 30 or offset == total:
            print(f'  {offset / 2**30:.1f} GiB', flush=True)
            reported = offset
    os.fsync(fd)
    os.pwrite(fd, head, 0)
    os.fsync(fd)
    os.posix_fadvise(fd, 0, 0, os.POSIX_FADV_DONTNEED)   # read back from the device, not from the host's cache
    print('verifying', flush=True)
    bad, offset = [], 0
    while offset < total:
        n = min(CHUNK, total - offset)
        if hashlib.sha256(os.pread(fi, n, offset)).digest() != hashlib.sha256(os.pread(fd, n, offset)).digest():
            bad.append(offset)
            print(f'  MISMATCH in the 64 MiB at {offset:#x}', flush=True)
        offset += n
    print('verify:', 'OK' if not bad else f'{len(bad)} chunks differ')
    sys.exit(1 if bad else 0)


if __name__ == '__main__':
    main()
