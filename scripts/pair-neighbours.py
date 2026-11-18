#!/usr/bin/env python3
"""Name small stubbed kernel functions by their paired neighbours in the RELEASE comparison kernel.
  scripts/pair-neighbours.py [--kext BUNDLE ...] [--max-insns N]
Accessors of a few instructions (a field load, a bit test, clearing 16 bytes) carry no fingerprint for
pair-callers.py. The compiler emits a source file's functions in order, in Apple's kernel and in the comparison kernel
alike: between the nearest paired original before T and the nearest one after it, the comparison kernel holds the
same functions. Among those, T's candidates are the ones whose body has T's shape: the same instructions with the
immediates (field offsets, which may differ between RELEASE and DEVELOPMENT layouts) masked. One candidate is a
pairing; several are listed with their positions relative to T's. Confirm and pin with scripts/pin-function.py.
"""
import bisect, importlib.util, json, struct, sys
from pathlib import Path
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pc', HERE / 'pair-callers.py')
pc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pc)
pn = pc.pn


def shape(image, start, end):
    try:
        raw = image.read(start, end - start)
    except ValueError:
        return None
    out = []
    for (w,) in struct.iter_unpack('<I', raw[:len(raw) // 4 * 4]):
        if w in (0xd503245f, 0xd503249f, 0xd50324df, 0xd503233f, 0xd503237f):   # bti, pacibsp/paciasp
            continue
        if w & 0x7c000000 == 0x14000000:
            w &= 0xfc000000                               # b/bl target
        elif w & 0x3b000000 == 0x39000000:
            w &= 0xffc003ff                               # ldr/str imm12: offset masked, registers kept
        elif w & 0x9f000000 == 0x90000000:
            w &= 0x9f00001f                               # adrp page
        elif w & 0x7f800000 in (0x11000000, 0x52800000, 0x72800000, 0x12800000):
            w &= 0xffc003ff if w & 0x7f800000 == 0x11000000 else 0xffe0001f   # add imm / movz/movk/movn imm
        elif w & 0x7f800000 == 0x53000000:
            w &= 0xffc003ff                               # ubfm (ubfx/lsr/lsl): bit position masked
        out.append(w)
    return tuple(out)


def main():
    max_insns = int(sys.argv[sys.argv.index('--max-insns') + 1]) if '--max-insns' in sys.argv else 12
    kexts = sys.argv[sys.argv.index('--kext') + 1:] if '--kext' in sys.argv else None
    record = json.loads((pn.OUT / 'kernel/kernel.json').read_text())
    slide = int(record['collection_slide'], 16)
    stubbed = sorted({int(a, 16) - slide for bundle, sites in record['stubbed'].items()
                      if not kexts or any(bundle.startswith(k) for k in kexts) for a in sites})
    pairing = json.loads((pn.OUT / 'kernel/kernel.map.json').read_text())['functions']
    names = {int(k, 16): v.get('name') for k, v in pairing.items() if v.get('name')}
    taken = set(names.values())
    raw = pn.KC.read_bytes()
    _, at = pn.Image(raw).entries['com.apple.kernel']
    entry = pn.Image(raw, at)
    starts = sorted(entry.function_starts())
    end_of = {s: e for s, e in zip(starts, starts[1:] + [starts[-1] + 4])}
    paired = sorted(names)
    ref_table = pc.symbols(pc.REFERENCE)
    ref_image = pn.Image(pc.REFERENCE.read_bytes())
    ref_addr = {n: a for a, n in ref_table}
    ref_starts = [a for a, _ in ref_table]
    ref_end = {a: b for (a, _), (b, _) in zip(ref_table, ref_table[1:] + [(ref_table[-1][0] + 4, '')])}
    native = {n for _, n in pc.symbols(pn.NATIVE)}
    for target in stubbed:
        body = shape(entry, target, end_of.get(target, target + 4))
        if body is None or len(body) > max_insns:
            continue
        k = bisect.bisect_left(paired, target)
        before = paired[k - 1] if k else None
        after = paired[k] if k < len(paired) else None
        lo, hi = ref_addr.get(names.get(before)), ref_addr.get(names.get(after))
        if lo is None or hi is None or hi <= lo or hi - lo > 0x4000:
            print(f'{target:#x}: neighbours {names.get(before)} / {names.get(after)} not usable in the reference')
            continue
        position = sum(1 for s in starts if before < s < target)
        found = []
        i = bisect.bisect_right(ref_starts, lo)
        index = 0
        while i < len(ref_table) and ref_table[i][0] < hi:
            a, n = ref_table[i]
            if shape(ref_image, a, ref_end[a]) == body and n not in taken:
                found.append((index, n, n in native))
            index += 1
            i += 1
        what = '; '.join(f'#{p} {n}{"" if nat else " (not native)"}' for p, n, nat in found) or 'no same-shape function'
        print(f'{target:#x} ({len(body)} insns, #{position} after {names.get(before)}): {what}')


if __name__ == '__main__':
    main()
