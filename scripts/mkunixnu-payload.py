#!/usr/bin/env python3
"""Build the UniXNU payload (FAT ramdisk) that boots our own xnu through DarwinBoot.

  mkunixnu-payload.py KERNEL ADT OUT.img --cmdline "..." [--timeout N] [--size-mib N]

Volume layout (UniXNU docs/concepts/payload.md):
  /EFI/UniXNU/unixnu.toml              one "xnu" entry, args = the command line
  /EFI/UniXNU/Payloads/kernel.macho      KERNEL with its chained rebases resolved (as tools/mkpayload.py does for
                                       the shim: our xnu only rebases kernel collections itself)
  /EFI/UniXNU/Payloads/kernel.macho.adt  ADT + /chosen/darwinboot-memory-size = sweet-mem-size, so DarwinBoot hands
                                       xnu the same RAM window the shim does (0xe8000000.., the UEFI reserves the
                                       GPU pool and TZ below it)
"""
import argparse, os, struct, subprocess, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import adt  # noqa: E402
import mkpayload  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument('kernel'); ap.add_argument('adt'); ap.add_argument('out')
ap.add_argument('--cmdline', required=True)
ap.add_argument('--timeout', type=int, default=3)
ap.add_argument('--size-mib', type=int, default=48)
a = ap.parse_args()

for ch in a.cmdline.split():
    k, _, v = ch.partition('=')
    ok = all(c.isalnum() or c in '_.-' for c in k) and all(c.isalnum() or c in '_.,-' for c in v)
    if not ok:
        sys.exit(f'mkunixnu-payload: argument {ch!r} is outside what UniXNU accepts ([A-Za-z0-9_.-]+[=[A-Za-z0-9_.,-]+])')
if len(a.cmdline) > 1000:
    sys.exit('mkunixnu-payload: command line longer than 1000 bytes')

buf = bytearray(open(a.kernel, 'rb').read())
m = mkpayload.parse_macho(buf)
assert m['ftype'] == 2, 'DarwinBoot takes MH_EXECUTE kernels only'
nfix = mkpayload.apply_chained_fixups(buf, m)

root, _ = adt.parse(adt.load(a.adt))
chosen = next(c for c in root.children if c.name == 'chosen')
phys, size = (struct.unpack('<Q', chosen.prop(p))[0] for p in ('sweet-phys-base', 'sweet-mem-size'))
assert chosen.prop('darwinboot-memory-size') is None
chosen.props.append(('darwinboot-memory-size', 0, struct.pack('<Q', size)))
adt_blob = adt.serialize(root)

toml = f'''version = 1

[boot]
timeout = {a.timeout}
fallback_timeout = {a.timeout}
connect_all = false
default = "xnu"

[ui]
title = "UniXNU penang"

[[entry]]
id = "xnu"
title = "iOS (penang xnu)"
type = "xnu"
path = "Payloads/kernel.macho"
args = "{a.cmdline}"
'''

with tempfile.TemporaryDirectory() as d:
    files = {'kernel.macho': bytes(buf), 'kernel.macho.adt': adt_blob, 'unixnu.toml': toml.encode()}
    for n, v in files.items():
        open(os.path.join(d, n), 'wb').write(v)
    if os.path.exists(a.out):
        os.unlink(a.out)
    run = lambda *c: subprocess.run(c, check=True, stdout=subprocess.DEVNULL)
    run('mkfs.fat', '-C', '-F', '16', '-n', 'UNIXNU', a.out, str(a.size_mib * 1024))
    run('mmd', '-i', a.out, '::/EFI', '::/EFI/UniXNU', '::/EFI/UniXNU/Payloads')
    run('mcopy', '-i', a.out, os.path.join(d, 'unixnu.toml'), '::/EFI/UniXNU/unixnu.toml')
    run('mcopy', '-i', a.out, os.path.join(d, 'kernel.macho'), '::/EFI/UniXNU/Payloads/kernel.macho')
    run('mcopy', '-i', a.out, os.path.join(d, 'kernel.macho.adt'), '::/EFI/UniXNU/Payloads/kernel.macho.adt')
print(f'payload {a.out}: kernel {len(buf)} bytes ({nfix} rebases resolved), ADT {len(adt_blob)} bytes, '
      f'window {size:#x} (expect physBase {phys:#x})')
