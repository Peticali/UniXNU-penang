#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""Rebuild the <window>.vroot hash tables of header-only root policies, checked against the signed headers.

    make-root-tables.py --unixnu ../UniXNU --policies scripts/policies/ipados-27.0.1-24A446 --output DIR \
        OS=IMAGE [SystemOS=IMAGE ...]

The policies in scripts/policies/<profile>/<window>/ carry only the 544-byte signed header (manifest.header.bin): the
table of per-block SHA-256 digests is a userdata data object (`unixnu userdata --object <window>.vroot=FILE`). The
table depends only on the image (VerifiedRoot tools/manifest.py: SHA-256 of each 4096-byte block of the raw disk, in
order), so it is rebuilt here from the IPSW image and accepted only when the image size, block count, image digest and
table digest all equal the values the signed header records.

IMAGE is the IPSW component as unixnu extracted it into out/ipsw/<build>/: an .aea archive is decrypted with
UniXNU's own decrypt_aea (cached beside it, as `unixnu userdata` does), and a UDIF disk image is read as its raw disk
with UniXNU's udif.py, the same bytes the userdata window carries. Nothing is signed here and no key is needed.
"""
import argparse
import hashlib
from pathlib import Path
import struct
import sys
import uuid

HEADER = struct.Struct('<8s4I2Q16s32s32s32sQ')   # VerifiedRoot tools/manifest.py header, 160 bytes
BLOCK = 4096


def signed_header(path):
    data = path.read_bytes()
    if len(data) != 544:
        raise SystemExit(f'{path}: {len(data)} bytes, expected the 544-byte signed header')
    fields = HEADER.unpack_from(data)
    magic, version, length, block, _, image_bytes, count, volume, image_sha, table_sha, anchor_sha, generation = fields
    if magic != b'VROOT01\0' or version != 1 or length != 160 or block != BLOCK:
        raise SystemExit(f'{path}: not a VROOT01 version 1 header with 4096-byte blocks')
    return dict(image_bytes=image_bytes, count=count, volume=str(uuid.UUID(bytes=volume)).upper(),
                image_sha=image_sha, table_sha=table_sha, generation=generation)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--unixnu', type=Path, required=True, help='the UniXNU checkout (its scripts/unixnu modules)')
    parser.add_argument('--policies', type=Path, required=True, help='scripts/policies/<profile> of this repository')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('windows', nargs='+', metavar='NAME=IMAGE')
    args = parser.parse_args()
    sys.path.insert(0, str(args.unixnu.resolve() / 'scripts'))
    from unixnu import udif
    from unixnu.ipsw import decrypt_aea
    args.output.mkdir(parents=True, exist_ok=True)
    for spec in args.windows:
        name, sep, image_text = spec.partition('=')
        if not sep or not name or '/' in name:
            parser.error(f'{spec}: expected NAME=IMAGE')
        header = signed_header(args.policies / name / 'manifest.header.bin')
        image = Path(image_text)
        if image.suffix == '.aea':
            image = decrypt_aea(image)
        disk = udif.Image(image)
        if disk.size != header['image_bytes']:
            raise SystemExit(f'{name}: raw disk is {disk.size} bytes, the signed header records {header["image_bytes"]}')
        image_hash, table_hash = hashlib.sha256(), hashlib.sha256()
        table = args.output / f'{name}.vroot'
        partial = table.with_suffix('.vroot.partial')
        count, pending, done = 0, b'', 0
        with partial.open('wb') as out:
            for chunk in disk.blocks():
                image_hash.update(chunk)
                pending = pending + chunk if pending else chunk
                whole = len(pending) - len(pending) % BLOCK
                view = memoryview(pending)
                digests = b''.join(hashlib.sha256(view[at:at + BLOCK]).digest() for at in range(0, whole, BLOCK))
                out.write(digests)
                table_hash.update(digests)
                count += whole // BLOCK
                pending = bytes(view[whole:])
                done += len(chunk)
                if done % (1 << 30) < len(chunk):
                    print(f'{name}: {done >> 30} GiB', flush=True)
            if pending:
                digest = hashlib.sha256(pending).digest()
                out.write(digest)
                table_hash.update(digest)
                count += 1
        checks = [('block count', count, header['count']),
                  ('image sha256', image_hash.digest(), header['image_sha']),
                  ('table sha256', table_hash.digest(), header['table_sha'])]
        failed = [what for what, got, want in checks if got != want]
        if failed:
            partial.unlink()
            raise SystemExit(f'{name}: {", ".join(failed)} differ from the signed header')
        partial.rename(table)
        print(f'{name}: {table} ({count} blocks, {table.stat().st_size} bytes), volume {header["volume"]}, '
              f'image sha256 {image_hash.hexdigest()}: matches the signed header')


if __name__ == '__main__':
    main()
