#!/usr/bin/env python3
"""Count the PAC instructions that fault on a non-PAC CPU (ARMv8.2), per kext of an arm64e kernelcache fileset."""
import struct, sys, collections
kc = open(sys.argv[1], 'rb').read()
want = sys.argv[2:] or None
ncmds = struct.unpack_from('<I', kc, 16)[0]
o = 32
entries = []
for _ in range(ncmds):
    cmd, sz = struct.unpack_from('<II', kc, o)
    if cmd == 0x80000035:                                   # LC_FILESET_ENTRY
        vmaddr, fileoff, nameoff = struct.unpack_from('<QQI', kc, o + 8)
        name = kc[o + nameoff:kc.index(b'\0', o + nameoff)].decode()
        entries.append((name, fileoff))
    o += sz

def classify(i):
    if i in (0xd65f0bff, 0xd65f0fff): return 'retaa/b'
    if (i & 0xfffffc00) in (0xd71f0800, 0xd71f0c00, 0xd73f0800, 0xd73f0c00): return 'braa/blraa'
    if (i & 0xfffffc1f) in (0xd61f081f, 0xd61f0c1f, 0xd63f081f, 0xd63f0c1f): return 'braaz/blraaz'
    if (i & 0xff200400) in (0xf8200400, 0xf8a00400): return 'ldraa/b'
    if i & 0xffffc000 == 0xdac10000: return 'pac/aut/xpac reg'
    if i & 0xffe0fc00 == 0x9ac03000: return 'pacga'
    if i in (0xd69f0bff, 0xd69f0fff): return 'eretaa/b'
    return None

tot = collections.Counter()
ldr_neg = 0
for name, fo in entries:
    if want and not any(w.lower() in name.lower() for w in want):
        continue
    nc = struct.unpack_from('<I', kc, fo + 16)[0]
    p = fo + 32; c = collections.Counter(); textsz = 0
    for _ in range(nc):
        cmd, sz = struct.unpack_from('<II', kc, p)
        if cmd == 0x19:
            seg = kc[p + 8:p + 24].split(b'\0')[0]
            nsec = struct.unpack_from('<I', kc, p + 64)[0]
            for k in range(nsec):
                q = p + 72 + 80 * k
                sect = kc[q:q + 16].split(b'\0')[0]
                addr, size, off = struct.unpack_from('<QQI', kc, q + 32)
                flags = struct.unpack_from('<I', kc, q + 64)[0]
                if flags & 0x80000400:                       # S_ATTR_PURE_INSTRUCTIONS / SOME_INSTRUCTIONS
                    textsz += size
                    for j in range(off, off + size, 4):
                        ins = struct.unpack_from('<I', kc, j)[0]
                        k2 = classify(ins)
                        if k2:
                            c[k2] += 1
                            if k2 == 'ldraa/b' and (ins >> 22) & 1:
                                ldr_neg += 1
        p += sz
    tot.update(c)
    if want or sum(c.values()) > 0:
        print('%-55s text %6d KB  %s' % (name[:55], textsz >> 10, dict(c)))
print('TOTAL', dict(tot), 'ldraa with negative offset:', ldr_neg, 'kexts:', len(entries))
