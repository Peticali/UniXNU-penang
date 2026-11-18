#!/usr/bin/env python3
"""Explain a "fileset: original component called an unmapped kernel function from ADDR" panic.

  scripts/unmapped-call.py CALLER [FRAME ...]   (addresses as printed by the panic screen)

For each frame: the fileset entry and segment it lies in, and for kernel frames the native symbol (the prelink's
segment_layout maps the collection back to the native kernel). For the caller: the call before it, the import stub
and GOT slot it goes through, the original kernel function that slot bound to in Apple's kernelcache, its first
instructions, and whether the prelink record lists it as stubbed. That address is what a reviewed fixture entry
(kits/XnuPrelink/fixtures/fileset-24A446-symbols.json, see patches/unixnu/0007) pins to a native symbol.
"""
import json
import os
import struct
import subprocess
import sys
from pathlib import Path

OUT = Path(os.environ.get('UNIXNU_OUT', '/mnt/nvme/xnu-build/unixnu/UniXNU/out/penang/ipados-27.0.1-24A446/penang'))
KC = Path(os.environ.get('UNIXNU_KERNELCACHE', '/mnt/nvme/xnu-build/ios26/kc/24A446__iPad17,3/24A446__iPad17,1_2_3_4/'
                                               'kernelcache.release.iPad17,1_2_3_4'))
NATIVE = OUT / 'tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf'
fs = (OUT / 'kernel/kernel.macho').read_bytes()
kc = KC.read_bytes()
record = json.loads((OUT / 'kernel/kernel.json').read_text())
slide = int(record['collection_slide'], 16)


def commands(data, off=0):
    p = off + 32
    for _ in range(struct.unpack_from('<I', data, off + 16)[0]):
        cmd, size = struct.unpack_from('<II', data, p)
        yield cmd, p, size
        p += size


def segments(data, off=0):
    for cmd, p, _ in commands(data, off):
        if cmd == 0x19:
            vm, vs, fo, fsz = struct.unpack_from('<QQQQ', data, p + 24)
            yield data[p + 8:p + 24].rstrip(b'\0').decode(), vm, vs, fo, fsz


def file_offset(data, va):
    for _, vm, _, fo, fsz in segments(data):
        if vm <= va < vm + fsz:
            return fo + va - vm
    raise SystemExit(f'{va:#x} is not file-backed')


entries = []
for cmd, p, size in commands(fs):
    if cmd == 0x80000035:
        vm, fo, name = struct.unpack_from('<QQI', fs, p + 8)
        entries.append((fs[p + name:p + size].split(b'\0')[0].decode(), fo))
ranges = [(vm, vm + vs, name, seg) for name, fo in entries for seg, vm, vs, _, _ in segments(fs, fo) if vs]
layout = record['statistics']['segment_layout']


def where(va):
    for lo, hi, name, seg in ranges:
        if lo <= va < hi:
            return name, seg, va - lo
    return '?', '?', 0


def native_symbol(va):
    for info in layout.values():
        new, old, size = (int(info[k], 16) for k in ('new', 'old', 'size'))
        if new <= va < new + size:
            out = subprocess.run(['llvm-symbolizer', f'--obj={NATIVE}', hex(va - new + old)], capture_output=True, text=True)
            return out.stdout.split('\n')[0]
    return ''


def disassemble(data, va, count):
    raw = data[file_offset(data, va):file_offset(data, va) + 4 * count]
    out = subprocess.run(['llvm-mc', '--disassemble', '-triple=arm64e-apple-ios', '-mattr=+v8.5a,+pauth'],
                         input=' '.join(f'0x{b:02x}' for b in raw), capture_output=True, text=True).stdout
    return [line.strip() for line in out.splitlines() if line.strip() and not line.strip().startswith('.')]


addresses = [int(a, 16) for a in sys.argv[1:]]
for va in addresses:
    name, seg, off = where(va)
    print(f'{va:#x}  {name} {seg}+{off:#x}  {native_symbol(va) if name == "com.apple.kernel" else ""}')

caller = addresses[0]
call = struct.unpack_from('<I', fs, file_offset(fs, caller - 4))[0]
if call >> 26 != 0b100101:
    sys.exit(f'the instruction before {caller:#x} is not a bl: {call:#010x}')
stub = caller - 4 + (((call & 0x3ffffff) ^ 0x2000000) - 0x2000000) * 4
lines = disassemble(fs, stub, 4)
print(f'\ncall {caller - 4:#x} -> stub {stub:#x}: ' + ' | '.join(lines))
adrp, add = (struct.unpack_from('<I', fs, file_offset(fs, stub + 4 * i))[0] for i in range(2))
if adrp & 0x9f000000 != 0x90000000:
    sys.exit('the stub does not start with adrp: not an import stub')
imm = ((adrp >> 29) & 3) | (((adrp >> 5) & 0x7ffff) << 2)
imm = (imm ^ 0x100000) - 0x100000
slot = (stub & ~0xfff) + (imm << 12) + ((add >> 10) & 0xfff)
raw = struct.unpack_from('<Q', kc, file_offset(kc, slot - slide))[0]
target = min(vm for _, vm, _, _, _ in segments(kc)) + (raw & 0x3fffffff)
stubbed = any(f'{target + slide:#x}' in sites for sites in record['stubbed'].values())
print(f'GOT slot {slot:#x} (original {slot - slide:#x}) -> original kernel function {target:#x}'
      f' (collection {target + slide:#x}; {"stubbed" if stubbed else "not in the stubbed list"})')
for line in disassemble(kc, target, 24):
    print('   ', line)
