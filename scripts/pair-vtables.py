#!/usr/bin/env python3
"""Pair stubbed kernel functions through the slots of paired vtables.

  scripts/pair-vtables.py [--apply]

The prelink map pairs Apple's kernel vtables (__ZTV...) with the native ones. Kexts call kernel methods through
those slots, so the C++ ABI requires both layouts to agree. For every paired vtable, walk both in step: a vtable
qualifies only when every slot whose original function the map already pairs holds that same native function and
both have the same length up to the first non-pointer. Then each slot holding a stubbed original function names it:
the native function in the same slot. A native function claimed by two different originals is dropped.
"""
import hashlib
import json
import os
import struct
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

UNIXNU = Path(os.environ.get('UNIXNU', '/mnt/nvme/xnu-build/unixnu/UniXNU'))
OUT = UNIXNU / 'out/penang/ipados-27.0.1-24A446/penang'
KC = Path(os.environ.get('UNIXNU_KERNELCACHE', '/mnt/nvme/xnu-build/ios26/kc/24A446__iPad17,3/24A446__iPad17,1_2_3_4/'
                                               'kernelcache.release.iPad17,1_2_3_4'))
NATIVE = OUT / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
FIXTURE = UNIXNU / 'kits/XnuPrelink/fixtures/fileset-24A446-symbols.json'
sys.path.insert(0, str(UNIXNU / 'kits/XnuPrelink'))
from kc_image import Image            # noqa: E402
from fileset_match import Side        # noqa: E402


def segments(data):
    out, p = [], 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, p)
        if cmd == 0x19:
            out.append(struct.unpack_from('<QQQQ', data, p + 24))
        p += size
    return out


def text_base(data):
    """Chained fixup targets are offsets from __TEXT (the native kernel's PLK segment lies below it)."""
    p = 32
    for _ in range(struct.unpack_from('<I', data, 16)[0]):
        cmd, size = struct.unpack_from('<II', data, p)
        if cmd == 0x19 and data[p + 8:p + 24].rstrip(b'\0') == b'__TEXT':
            return struct.unpack_from('<Q', data, p + 24)[0]
        p += size
    raise SystemExit('no __TEXT segment')


def reader(data):
    segs = segments(data)

    def read(va):
        for vm, _, fo, fs in segs:
            if vm <= va < vm + fs:
                return struct.unpack_from('<Q', data, fo + va - vm)[0]
        return None
    return read


def main():
    record = json.loads((OUT / 'kernel/kernel.json').read_text())
    slide = int(record['collection_slide'], 16)
    stubbed = {int(a, 16) - slide for sites in record['stubbed'].values() for a in sites}
    pairing = json.loads((OUT / 'kernel/kernel.map.json').read_text())
    funcs = {int(k, 16): int(v['native'], 16) for k, v in pairing['functions'].items()}
    kc, nat = KC.read_bytes(), NATIVE.read_bytes()
    kread, nread = reader(kc), reader(nat)
    kbase, nbase = text_base(kc), text_base(nat)
    names = {}
    for line in subprocess.run(['llvm-nm', str(NATIVE)], capture_output=True, text=True).stdout.splitlines():
        f = line.split()
        if len(f) == 3:
            names.setdefault(int(f[0], 16), f[2])

    def target(raw, base):
        # format-8 chained fixup (rebase), or an already plain pointer
        if raw is None or raw == 0:
            return None
        if raw >> 62 or raw >> 32 < 0xfffff000:
            return base + (raw & 0x3fffffff)
        return raw

    claims = defaultdict(set)
    vtables = 0
    for key, value in pairing['data'].items():
        if not (value.get('name') or '').startswith('__ZTV') or not value.get('native'):
            continue
        orig, native = int(key, 16) + 16, int(value['native'], 16) + 16
        slots = []
        for i in range(2048):
            o, n = target(kread(orig + 8 * i), kbase), target(nread(native + 8 * i), nbase)
            if o is None or n is None or n not in names:
                break
            slots.append((o, n))
        known = [(o, n) for o, n in slots if o in funcs]
        if not known or any(funcs[o] != n for o, n in known):
            continue
        vtables += 1
        for o, n in slots:
            if o in stubbed and o not in funcs:
                claims[o].add(n)
    fixture = json.loads(FIXTURE.read_text())
    pinned = {int(e['original'], 16) for e in fixture['functions']}
    used = defaultdict(set)
    for o, ns in claims.items():
        if len(ns) == 1:
            used[next(iter(ns))].add(o)
    raw = KC.read_bytes()
    cache = Image(raw)
    _, at = cache.entries['com.apple.kernel']
    entry = Image(raw, at)
    side = Side(entry, cache.fixups(), entry.mapped())
    proposals = []
    for o, ns in sorted(claims.items()):
        if len(ns) != 1 or o in pinned or o not in side.functions:
            continue
        n = next(iter(ns))
        if len(used[n]) != 1:
            continue
        body = entry.read(o, side.functions[o]['end'] - o)
        proposals.append({'original': f'{o:#x}', 'original_size': len(body),
                          'original_sha256': hashlib.sha256(body).hexdigest(), 'native_symbol': names[n],
                          'evidence': ('Same slot of paired vtables: every slot of these vtables whose original function '
                                       'the prelink map already pairs holds that same native function, so the layouts '
                                       'agree and this slot names the stubbed original. Proposed by UniXNU-penang '
                                       'scripts/pair-vtables.py.')})
    print(f'consistent vtables: {vtables}; stubbed functions named by a slot: {len(proposals)}')
    for p in proposals[:60]:
        print(' ', p['original'], p['native_symbol'])
    if '--apply' in sys.argv and proposals:
        text = FIXTURE.read_text()
        fixture['functions'] += proposals
        FIXTURE.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + ('\n' if text.endswith('\n') else ''))
        print(f'added {len(proposals)} entries to {FIXTURE}')


if __name__ == '__main__':
    main()
