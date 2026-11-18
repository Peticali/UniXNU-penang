#!/usr/bin/env python3
"""add_pairs.py MAP.json NATIVE_KERNEL PAIRS.txt OUT.json: add hand-identified function pairs to an XnuPrelink map."""
import json, subprocess, sys
m = json.load(open(sys.argv[1]))
syms = {}
for line in subprocess.run(['llvm-nm', sys.argv[2]], capture_output=True, text=True).stdout.splitlines():
    f = line.split()
    if len(f) == 3:
        syms.setdefault(f[2], int(f[0], 16))
added = 0
for line in open(sys.argv[3]):
    line = line.split('#', 1)[0].split()
    if len(line) not in (2, 3):
        continue
    orig, name = line[:2]
    if len(line) == 3 and line[2] == 'data':
        if name not in syms:
            raise SystemExit('native symbol missing: ' + name)
        m['data']['0x%x' % int(orig, 16)] = {'native': '0x%x' % syms[name], 'name': name, 'how': 'manual',
                                             'sections': ['__DATA,__common', '__DATA,__common']}
        added += 1
        continue
    key = '0x%x' % int(orig, 16)
    if name not in syms:
        raise SystemExit('native symbol missing: ' + name)
    m['functions'][key] = {'native': '0x%x' % syms[name], 'name': name, 'addend': 0, 'how': 'manual'}
    added += 1
json.dump(m, open(sys.argv[4], 'w'), indent=1)
print('added', added, 'pairs ->', sys.argv[4])
