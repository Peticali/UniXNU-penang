#!/usr/bin/env python3
"""Name stubbed kernel functions by fingerprint: a fourth pairing pass after pair-normalized, pair-vtables, pair-gaps.
  scripts/pair-callers.py [--kext BUNDLE ...] [--top N]
The functions still stubbed are mostly exported KPIs the kernel inlines into its own code under LTO, so they have no
kernel callers and their bodies differ from the native ones in instruction selection (how a vtable slot is reached,
bounds checks). What survives every build of the same source is a fingerprint: the PAC discriminators (movk Xn,
#imm, lsl #48: hashes of method and type names), the small immediates (sizes, slots, flags), and the callees the
prelink already pairs by name. Each stubbed original is scored (Jaccard over those features, discriminators counted
twice) against every function of the symbol-bearing RELEASE comparison kernel, the LTO build the prelink pairs
through; the report gives the best candidates with their scores and sizes, and flags candidates that are not native
symbols or are already paired. Confirm by reading both bodies, then pin with scripts/pin-function.py.
"""
import bisect
import collections
import difflib
import importlib.util
import json
import struct
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pairnorm', HERE / 'pair-normalized.py')
pn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pn)
REFERENCE = pn.OUT / 'tree/build/xnu/fileset-reference/mach.release.bcm2837.unstripped.noctf'


def symbols(path):
    out = subprocess.run(['llvm-nm', '-n', '--defined-only', str(path)], capture_output=True, text=True, check=True).stdout
    table = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) == 3 and parts[1] in 'tTsS' and not parts[2].startswith(('ltmp', '__ZTV', '__ZTS', '__ZTI')):
            table.append((int(parts[0], 16), parts[2]))
    return table


def calls(image, start, end):
    """bl targets in order."""
    try:
        raw = image.read(start, end - start)
    except ValueError:                       # the last function runs to the end of the segment
        return []
    out = []
    for i, (w,) in enumerate(struct.iter_unpack('<I', raw[:len(raw) // 4 * 4])):
        if w & 0xfc000000 == 0x94000000:
            out.append(start + 4 * i + ((((w & 0x3ffffff) ^ 0x2000000) - 0x2000000) << 2))
    return out


def features(image, start, end, names):
    try:
        raw = image.read(start, end - start)
    except ValueError:
        return collections.Counter(), 0
    words = [w for (w,) in struct.iter_unpack('<I', raw[:len(raw) // 4 * 4])]
    out = collections.Counter()
    for i, w in enumerate(words):
        pc = start + 4 * i
        if w & 0xff800000 == 0xf2800000 and (w >> 21) & 3 == 3:        # movk Xd, #imm, lsl #48: a discriminator
            out[('disc', (w >> 5) & 0xffff)] += 2
        elif w & 0x7f800000 == 0x52800000:                              # movz Wd/Xd, #imm (lsl 0)
            if (w >> 21) & 3 == 0:
                out[('imm', (w >> 5) & 0xffff)] += 1
        elif w & 0x7f800000 == 0x11000000 and (w >> 10) & 0xfff:        # add #imm12
            out[('add', (w >> 10) & 0xfff)] += 1
        elif w & 0xfc000000 in (0x94000000, 0x14000000):              # bl / b
            target = pc + ((((w & 0x3ffffff) ^ 0x2000000) - 0x2000000) << 2)
            if names is not None and target in names:
                out[('call', names[target])] += 1
    return out, len(words)


def jaccard(a, b):
    keys = set(a) | set(b)
    if not keys:
        return 0.0
    return sum(min(a[k], b[k]) for k in keys) / sum(max(a[k], b[k]) for k in keys)


def main():
    top = int(sys.argv[sys.argv.index('--top') + 1]) if '--top' in sys.argv else 3
    kexts = sys.argv[sys.argv.index('--kext') + 1:] if '--kext' in sys.argv else None
    record = json.loads((pn.OUT / 'kernel/kernel.json').read_text())
    slide = int(record['collection_slide'], 16)
    stubbed = sorted({int(a, 16) - slide for bundle, sites in record['stubbed'].items()
                      if not kexts or any(bundle.startswith(k) for k in kexts) for a in sites})
    pairing = json.loads((pn.OUT / 'kernel/kernel.map.json').read_text())['functions']
    names = {int(k, 16): v.get('name') for k, v in pairing.items() if v.get('name')}
    taken = {v.get('name') for v in pairing.values() if v.get('name')}
    raw = pn.KC.read_bytes()
    cache = pn.Image(raw)
    _, at = cache.entries['com.apple.kernel']
    entry = pn.Image(raw, at)
    starts = sorted(entry.function_starts())
    bounds = {s: e for s, e in zip(starts, starts[1:] + [starts[-1] + 4])}
    ref_table = symbols(REFERENCE)
    ref_image = pn.Image(REFERENCE.read_bytes())
    ref_names = {a: n for a, n in ref_table}
    native = {n for _, n in symbols(pn.NATIVE)}
    ref = []
    for (a, n), (b, _) in zip(ref_table, ref_table[1:] + [(ref_table[-1][0] + 4, '')]):
        if n in taken:
            continue
        f, size = features(ref_image, a, b, ref_names)
        if f:
            ref.append((n, f, size))
    for target in stubbed:
        f, size = features(entry, target, bounds.get(target, target + 4), names)
        scored = sorted(((jaccard(f, g), n, s) for n, g, s in ref), reverse=True)[:top]
        line = ', '.join(f'{n} {score:.2f} ({s}{"" if n in native else " not native"})' for score, n, s in scored)
        print(f'{target:#x} ({size} insns, {sum(1 for k in f if k[0] == "disc")} discs): {line}')


if __name__ == '__main__':
    main()
