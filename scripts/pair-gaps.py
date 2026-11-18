#!/usr/bin/env python3
"""Pair stubbed kernel functions by compile order: the gaps between paired neighbours.

  scripts/pair-gaps.py [--apply] [--max-gap N]

A compiler emits one source file's functions in source order, so Apple's kernel and the native one keep the same
sequence wherever both built the same file. Take two consecutive paired original functions A < B whose natives
A' < B' are in the same order with no paired native function between them. When the original gap holds exactly as
many unpaired functions as the native gap, they pair by position, provided each candidate pair passes:
  - size: within a factor of 4 (Apple clang's bounds checks and inlining make bodies larger, not different in kind);
  - references: every callee or datum the original uses that the prelink map already pairs is used by the candidate
    too (as a set: inlining reorders calls), and the candidate is not one of the native functions already taken.
A gap with any rejected pair is skipped whole. Only gaps that contain at least one stubbed original are reported.
"""
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('pairnorm', HERE / 'pair-normalized.py')
pn = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pn)


def refs_of(image, start, end):
    refs = []
    pn.normalize(pn.words_of(image, start, end), start, refs)
    return set(refs)


def main():
    max_gap = int(sys.argv[sys.argv.index('--max-gap') + 1]) if '--max-gap' in sys.argv else 8
    record = json.loads((pn.OUT / 'kernel/kernel.json').read_text())
    slide = int(record['collection_slide'], 16)
    stubbed = {int(a, 16) - slide for sites in record['stubbed'].values() for a in sites}
    pairing = json.loads((pn.OUT / 'kernel/kernel.map.json').read_text())
    funcs = {int(k, 16): int(v['native'], 16) for k, v in pairing['functions'].items() if v.get('native')}
    known = dict(funcs)
    known.update({int(k, 16): int(v['native'], 16) for k, v in pairing['data'].items() if v.get('native')})
    taken = set(funcs.values())

    raw = pn.KC.read_bytes()
    cache = pn.Image(raw)
    _, at = cache.entries['com.apple.kernel']
    entry = pn.Image(raw, at)
    original = pn.Side(entry, cache.fixups(), entry.mapped())
    native_image = pn.Image(pn.NATIVE.read_bytes())
    native = pn.Side(native_image, native_image.fixups(), native_image.mapped())
    names = {}
    for name, start in native.named_functions.items():
        if '.cold.' not in name:
            names.setdefault(start, name)
    ostarts = sorted(original.functions)
    nstarts = sorted(s for s in native.functions if s in names)
    nindex = {s: i for i, s in enumerate(nstarts)}

    fixture = json.loads(pn.FIXTURE.read_text())
    pinned = {int(e['original'], 16) for e in fixture['functions']}
    anchors = [a for a in ostarts if a in funcs and funcs[a] in nindex]
    proposals, used = [], set()
    gaps_seen = gaps_ok = 0
    for a, b in zip(anchors, anchors[1:]):
        na, nb = funcs[a], funcs[b]
        if not na < nb:
            continue
        ogap = [s for s in ostarts if a < s < b]
        if any(s in funcs for s in ogap) or not ogap or len(ogap) > max_gap:
            continue
        ngap = nstarts[nindex[na] + 1:nindex[nb]]
        if any(s in taken for s in ngap) or len(ngap) != len(ogap):
            continue
        if not any(s in stubbed for s in ogap):
            continue
        gaps_seen += 1
        pairs = []
        for o, n in zip(ogap, ngap):
            osize = original.functions[o]['end'] - o
            nsize = native.functions[n]['end'] - n
            if not (osize * 4 >= nsize and nsize * 4 >= osize):
                break
            orefs = {known[r] for r in refs_of(entry, o, original.functions[o]['end']) if r in known}
            nrefs = refs_of(native_image, n, native.functions[n]['end'])
            if not orefs <= nrefs:
                break
            pairs.append((o, n, osize, len(orefs)))
        else:
            gaps_ok += 1
            for o, n, osize, nref in pairs:
                if o not in stubbed or o in pinned or names[n] in used:
                    continue
                used.add(names[n])
                body = entry.read(o, osize)
                proposals.append({'original': f'{o:#x}', 'original_size': osize,
                                  'original_sha256': hashlib.sha256(body).hexdigest(), 'native_symbol': names[n],
                                  'evidence': (f'Compile order: between paired neighbours {pairing["functions"][hex(a)]["name"]} '
                                               f'and {pairing["functions"][hex(b)]["name"]} the original and the native '
                                               f'kernel hold the same number ({len(ogap)}) of unpaired functions; this is '
                                               f'position {ogap.index(o) + 1}. Sizes agree within 4x and all {nref} of its '
                                               'references the prelink map already pairs appear in the native function. '
                                               'Proposed by UniXNU-penang scripts/pair-gaps.py.')})
    print(f'gaps with stubbed functions and equal counts: {gaps_seen}; consistent: {gaps_ok}; pairs: {len(proposals)}')
    for p in proposals[:80]:
        print(' ', p['original'], p['native_symbol'])
    if '--apply' in sys.argv and proposals:
        text = pn.FIXTURE.read_text()
        fixture['functions'] += proposals
        pn.FIXTURE.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + ('\n' if text.endswith('\n') else ''))
        print(f'added {len(proposals)} entries to {pn.FIXTURE}')


if __name__ == '__main__':
    main()
