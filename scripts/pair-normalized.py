#!/usr/bin/env python3
"""Propose reviewed fixture pairs for prelink-stubbed kernel functions whose code equals a native function's.

  scripts/pair-normalized.py [--apply]

Apple's kernel is built by Apple clang, ours by upstream clang. Many functions XnuPrelink leaves stubbed differ only
in what the two compilers insert, not in what they do:
  - BTI landing pads (bti c/j/jc) at function entries;
  - the PAC failure check upstream clang emits after an authentication (mov x17, xN; xpaci/xpacd x17; cmp xN, x17;
    b.eq +8; brk #0xc47K), which Apple clang leaves out (the CPU's FPAC faults instead).
Both sides are normalized (those removed, then PC-relative immediates and adrp page offsets masked) and an original
stubbed function is paired only when its normalized code is unique among all original functions and equals exactly
one native named function's, itself unique among native functions. Each pair carries that as its evidence.
With --apply the entries are added to the 24A446 fixture of the UniXNU checkout (patches/unixnu/0007 records them).
"""
import hashlib
import json
import os
import struct
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

BTI = {0xd503241f, 0xd503245f, 0xd503249f, 0xd50324df}
MIN_WORDS = 4


def normalize(words):
    out, i = [], 0
    while i < len(words):
        w = words[i]
        if w in BTI:
            i += 1
            continue
        # mov x17, xN; xpaci/xpacd x17; cmp xN, x17; b.eq +8; brk #0xc47K
        if (i + 4 < len(words) and words[i] & 0xffe0ffff == 0xaa0003f1 and words[i + 1] in (0xdac143f1, 0xdac147f1)
                and words[i + 2] & 0xfffffc1f == 0xeb11001f and words[i + 3] == 0x54000040
                and words[i + 4] & 0xffffff9f == 0xd4388e00):   # brk #0xc470..0xc473
            i += 5
            continue
        if w & 0x7c000000 == 0x14000000:          # b / bl
            w &= 0xfc000000
        elif w & 0xff000010 == 0x54000000:        # b.cond
            w &= 0xff00001f
        elif w & 0x7e000000 in (0x34000000, 0x36000000):   # cbz/cbnz, tbz/tbnz
            w &= 0xfff8001f if w & 0x7e000000 == 0x36000000 else 0xff00001f
        elif w & 0x1f000000 == 0x10000000:        # adr / adrp
            w &= 0x9f00001f
        elif w & 0x3b000000 == 0x18000000:        # ldr literal
            w &= 0xff00001f
        if out and out[-1] & 0x9f000000 == 0x90000000:   # the low 12 bits after an adrp
            base = out[-1] & 31
            if (w & 0x7f800000 == 0x11000000 or w & 0x3b000000 == 0x39000000) and (w >> 5) & 31 == base:
                w &= ~(0xfff << 10) & 0xffffffff
        out.append(w)
        i += 1
    return b''.join(struct.pack('<I', w) for w in out)


def words_of(image, start, end):
    raw = image.read(start, end - start)
    return list(struct.unpack(f'<{len(raw) // 4}I', raw[:len(raw) // 4 * 4]))


def main():
    record = json.loads((OUT / 'kernel/kernel.json').read_text())
    slide = int(record['collection_slide'], 16)
    stubbed = {int(a, 16) - slide for sites in record['stubbed'].values() for a in sites}
    raw = KC.read_bytes()
    cache = Image(raw)
    _, at = cache.entries['com.apple.kernel']
    entry = Image(raw, at)
    original = Side(entry, cache.fixups(), entry.mapped())
    native_image = Image(NATIVE.read_bytes())
    native = Side(native_image, native_image.fixups(), native_image.mapped())

    shapes = defaultdict(list)
    for start, fn in original.functions.items():
        shapes[normalize(words_of(entry, start, fn['end']))].append(start)
    native_shapes = defaultdict(set)
    names = {}
    for name, start in native.named_functions.items():
        fn = native.functions.get(start)
        if fn is None:
            continue
        native_shapes[normalize(words_of(native_image, start, fn['end']))].add(start)
        names.setdefault(start, name)
    fixture = json.loads(FIXTURE.read_text())
    pinned = {int(e['original'], 16) for e in fixture['functions']}
    proposals = []
    for start in sorted(stubbed):
        fn = original.functions.get(start)
        if fn is None or start in pinned:
            continue
        shape = normalize(words_of(entry, start, fn['end']))
        if len(shape) < 4 * MIN_WORDS or len(shapes[shape]) != 1 or len(native_shapes.get(shape, ())) != 1:
            continue
        target = next(iter(native_shapes[shape]))
        body = entry.read(start, fn['end'] - start)
        proposals.append({'original': f'{start:#x}', 'original_size': len(body),
                          'original_sha256': hashlib.sha256(body).hexdigest(), 'native_symbol': names[target],
                          'evidence': (f'Normalized code ({len(shape) // 4} instructions; BTI pads and upstream clang\'s '
                                       'PAC failure checks removed, PC-relative immediates masked) is unique among the '
                                       'original functions and equals exactly one native function, itself unique. '
                                       'Proposed by UniXNU-penang scripts/pair-normalized.py for a prelink stub.')})
    print(f'stubbed originals: {len(stubbed)}; unique normalized pairs: {len(proposals)}')
    for p in proposals[:40]:
        print(' ', p['original'], p['native_symbol'])
    if '--apply' in sys.argv and proposals:
        fixture['functions'] += proposals
        text = FIXTURE.read_text()
        FIXTURE.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + ('\n' if text.endswith('\n') else ''))
        print(f'added {len(proposals)} entries to {FIXTURE}')


if __name__ == '__main__':
    main()
