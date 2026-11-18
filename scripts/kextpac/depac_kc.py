#!/usr/bin/env python3
"""De-PAC an arm64e kernelcache fileset for a CPU without pointer authentication (ARMv8.2, e.g. Cortex-A76/A55).

  depac_kc.py IN_KERNELCACHE OUT_KERNELCACHE [--with-kernel] [--only BUNDLE ...]

1. Code (every section with instructions, of every fileset entry, or only the named ones): the PAC forms that are
   UNDEFINED without FEAT_PAuth become their plain equivalents, one instruction for one, in place:
     retaa/retab -> ret            braa/brab Rn,Rm -> br Rn     blraa/blrab Rn,Rm -> blr Rn
     braaz/brabz Rn -> br Rn       blraaz/blrabz Rn -> blr Rn   eretaa/eretab -> eret
     pac*/aut*/xpac* (data-processing, register form) -> nop   (pointers are never signed: nothing to strip)
   The hint-space forms (paciasp, autibsp, pacia1716...) are architectural NOPs on such a CPU and stay.
   ldraa/ldrab and pacga have no 1:1 equivalent and stop the tool if present.
2. Pointers: every DYLD_CHAINED_PTR_64_KERNEL_CACHE (format 8) fixup with isAuth=1 becomes a plain rebase to the
   same target (isAuth, key, addrDiv and diversity cleared; target, cacheLevel and next kept).
The Mach-O header's cpusubtype stays arm64e (the loader's choice is separate).

Written for the penang port. The 1:1 rewrite rules are the ones of IOS-26-Hot's tools/de-pac-arm64e.py
(https://github.com/nithinyadavamaraboina-online/IOS-26-Hot, MIT, Copyright (c) 2026 dipa-studio), which de-PACs
the userland; this tool adds the kernelcache fileset walk and the chained-fixup auth bits."""
import struct, sys, collections, hmac, hashlib

src, dst = sys.argv[1], sys.argv[2]
with_kernel = '--with-kernel' in sys.argv
if with_kernel:
    sys.argv.remove('--with-kernel')
only = sys.argv[sys.argv.index('--only') + 1:] if '--only' in sys.argv else None
kc = bytearray(open(src, 'rb').read())

def rewrite(i):
    if i in (0xd65f0bff, 0xd65f0fff): return 0xd65f03c0, 'ret'
    if i in (0xd69f0bff, 0xd69f0fff): return 0xd69f03e0, 'eret'
    m = i & 0xfffffc00
    rn = (i >> 5) & 31
    if m in (0xd71f0800, 0xd71f0c00): return 0xd61f0000 | rn << 5, 'br'
    if m in (0xd73f0800, 0xd73f0c00): return 0xd63f0000 | rn << 5, 'blr'
    m2 = i & 0xfffffc1f
    if m2 in (0xd61f081f, 0xd61f0c1f): return 0xd61f0000 | rn << 5, 'br'
    if m2 in (0xd63f081f, 0xd63f0c1f): return 0xd63f0000 | rn << 5, 'blr'
    if i & 0xffffc000 == 0xdac10000: return 0xd503201f, 'nop'
    if (i & 0xff200400) in (0xf8200400, 0xf8a00400): raise SystemExit('ldraa/ldrab at an instruction: no 1:1 rewrite')
    # pacga Xd, Xn, Xm -> mov Xd, xzr: every generic signature is 0, so signing and checking still agree.
    if i & 0xffe0fc00 == 0x9ac03000: return 0xaa1f03e0 | (i & 31), 'pacga-zero'
    # msr/mrs of the PAC key registers (APIA/APIB/APDA/APDB/APGA: op0 3, op1 0, CRn 2, CRm 1..3): no keys here.
    if (i & 0xfff00000) in (0xd5100000, 0xd5300000) and (i >> 16) & 7 == 0 and (i >> 12) & 15 == 2 and (i >> 8) & 15 in (1, 2, 3):
        return (0xaa1f03e0 | (i & 31), 'key-mrs-zero') if i & 0x200000 else (0xd503201f, 'key-msr-nop')
    return None, None

ncmds = struct.unpack_from('<I', kc, 16)[0]
o = 32
entries, segs, fixups = [], [], None
for _ in range(ncmds):
    cmd, sz = struct.unpack_from('<II', kc, o)
    if cmd == 0x80000035:
        vmaddr, fileoff, nameoff = struct.unpack_from('<QQI', kc, o + 8)
        entries.append((kc[o + nameoff:kc.index(b'\0', o + nameoff)].decode(), fileoff))
    elif cmd == 0x19:
        vmaddr, vmsize, fileoff, filesize = struct.unpack_from('<QQQQ', kc, o + 24)
        segs.append((vmaddr, vmsize, fileoff, filesize))
    elif cmd == 0x80000034:
        fixups = struct.unpack_from('<II', kc, o + 8)
    o += sz

done = collections.Counter()
for name, fo in entries:
    if (only and name not in only) or (name == 'com.apple.kernel' and not with_kernel):
        continue                                    # (unless --with-kernel: a native arm64e kernel is rewritten too)
    if name == 'com.apple.kernel' and with_kernel and struct.unpack_from('<I', kc, fo + 8)[0] != struct.unpack_from('<I', kc, 8)[0]:
        # DarwinBoot wants the kernel entry's cpusubtype to equal the collection's. Upstream clang leaves out the
        # kernel pointer-auth ABI bit Apple's sets (0x80000002 vs 0xc0000002); there is no PAC left after this tool.
        struct.pack_into('<I', kc, fo + 8, struct.unpack_from('<I', kc, 8)[0])
        done['kernel-cpusubtype'] += 1
    nc = struct.unpack_from('<I', kc, fo + 16)[0]
    # corecrypto's FIPS POST checks HMAC-SHA256 (one zero-byte key) of its __TEXT_EXEC,__text against __fips_hmacs:
    # remember the field if it covers the original bytes, and seal the rewritten ones below (as XnuPrelink reseals).
    sect = {}
    p = fo + 32
    for _ in range(nc):
        cmd, sz = struct.unpack_from('<II', kc, p)
        if cmd == 0x19:
            for k in range(struct.unpack_from('<I', kc, p + 64)[0]):
                q = p + 72 + 80 * k
                sname, segname = (kc[q + o:q + o + 16].split(b'\0')[0].decode() for o in (0, 16))
                sect[(segname, sname)] = struct.unpack_from('<QQI', kc, q + 32)
        p += sz
    seal = None
    if ('__TEXT_EXEC', '__text') in sect and any(n == '__fips_hmacs' for _, n in sect):
        _, tsize, toff = sect[('__TEXT_EXEC', '__text')]
        _, hsize, hoff = next(v for (_, n), v in sect.items() if n == '__fips_hmacs')
        if hsize == 32 and hmac.new(b'\0', bytes(kc[toff:toff + tsize]), hashlib.sha256).digest() == bytes(kc[hoff:hoff + 32]):
            seal = (toff, tsize, hoff)
    p = fo + 32
    for _ in range(nc):
        cmd, sz = struct.unpack_from('<II', kc, p)
        if cmd == 0x19:
            for k in range(struct.unpack_from('<I', kc, p + 64)[0]):
                q = p + 72 + 80 * k
                addr, size, off = struct.unpack_from('<QQI', kc, q + 32)
                if struct.unpack_from('<I', kc, q + 64)[0] & 0x80000400:
                    for j in range(off, off + size, 4):
                        new, kind = rewrite(struct.unpack_from('<I', kc, j)[0])
                        if new is not None:
                            struct.pack_into('<I', kc, j, new)
                            done[kind] += 1
        p += sz
    if seal:
        toff, tsize, hoff = seal
        kc[hoff:hoff + 32] = hmac.new(b'\0', bytes(kc[toff:toff + tsize]), hashlib.sha256).digest()
        done['fips-reseal'] += 1
print('code:', dict(done))

base = min(s[0] for s in segs)
def vm_to_file(vmoff):
    va = base + vmoff
    for vmaddr, vmsize, fileoff, filesize in segs:
        if vmaddr <= va < vmaddr + filesize:
            return fileoff + va - vmaddr
    return None

doff, dsz = fixups
_, starts_off = struct.unpack_from('<II', kc, doff)
so = doff + starts_off
auth = plain = 0
for i in range(struct.unpack_from('<I', kc, so)[0]):
    off = struct.unpack_from('<I', kc, so + 4 + 4 * i)[0]
    if off == 0:
        continue
    s = so + off
    size, page_size, fmt, seg_off, max_valid, page_count = struct.unpack_from('<IHHQIH', kc, s)
    assert fmt == 8, fmt
    for pg in range(page_count):
        start = struct.unpack_from('<H', kc, s + 22 + 2 * pg)[0]
        if start == 0xffff:
            continue
        fo = vm_to_file(seg_off + pg * page_size + start)
        while fo is not None:
            v = struct.unpack_from('<Q', kc, fo)[0]
            nxt = (v >> 51) & 0xfff
            if v >> 63:
                v &= (1 << 30) - 1 | (3 << 30) | (0xfff << 51)   # keep target, cacheLevel, next; isAuth/key/addrDiv/diversity 0
                struct.pack_into('<Q', kc, fo, v)
                auth += 1
            else:
                plain += 1
            fo = fo + nxt * 4 if nxt else None
print('pointers: %d signed -> plain, %d already plain' % (auth, plain))
open(dst, 'wb').write(kc)
