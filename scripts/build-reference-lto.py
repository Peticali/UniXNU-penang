#!/usr/bin/env python3
"""UniXNU's build-fileset-release-reference.py --lto on a Linux host.

The iPadOS 27 prelink pairs Apple's kernel functions with the native kernel through a symbol-bearing
RELEASE comparison kernel. UniXNU builds it with LTO (as Apple's kernel is): without LTO the pairing
leaves ~2000 functions stubbed instead of the profile's 24 (prelink-regression.json), and the first
original component to call one panics ("original component called an unmapped kernel function").

The toolchain's ld64 (cctools-port) is built --disable-lto-support. This runs the reference build with
an LTO-capable ld64 of the same version first in xcrun's and clang's search, and LIBLTO pointing at a
libLTO.so of the toolchain's own LLVM commit (bitcode from CROSS_CLANG is read by the same LLVM).
Built by scripts/setup-ld64-lto.sh into UNIXNU_LD64_LTO (default <toolchain>/ld64-lto).
"""
import os
import subprocess
import sys
from pathlib import Path

tree = Path.cwd()
# penang: the reference only names Apple's functions for the prelink, so a device patch that adds its own code (console
# mirror, panic cave, probes) does not need a 6-minute LTO rebuild. An existing reference is kept unless REFERENCE=rebuild
# (after a UniXNU update or a change to code Apple's kexts call). Rebuilding it from a source that carries the board's
# own debug code also costs pairings: on 2026-11-18 a reference built with the ramoops console and panic cave paired 268
# fewer functions (mach_absolute_time among them) than the one built at 11:22 (lto-1e088df9bd4cfb54), now kept.
final = tree / 'build/xnu/fileset-reference/mach.release.bcm2837.unstripped.noctf'
if final.is_file() and os.environ.get('REFERENCE') != 'rebuild':
    print(f'reference kept: {final} (REFERENCE=rebuild to rebuild it)')
    sys.exit(0)
root = Path(os.environ.get('UNIXNU_LD64_LTO', '/mnt/nvme/xnu-build/unixnu/toolchain/ld64-lto'))
ld, liblto = root / 'bin/ld', root / 'lib/libLTO.so'
for path in (ld, liblto):
    if not path.is_file():
        sys.exit(f'{path} missing: run scripts/setup-ld64-lto.sh')
shim = root / 'shim'                       # only `ld`: every other tool still comes from the toolchain
shim.mkdir(exist_ok=True)
if not (shim / 'ld').exists():
    (shim / 'ld').symlink_to(ld)
env = dict(os.environ, PATH=f'{shim}{os.pathsep}{os.environ.get("PATH", "")}', LIBLTO=str(liblto),
           XNU_TOOLCHAIN_BIN=f'{shim} {os.environ.get("XNU_TOOLCHAIN_BIN", "")}'.strip())
script = tree / 'scripts/build-fileset-release-reference.py'
sys.exit(subprocess.run(['python3', str(script), '--lto', *sys.argv[1:]], env=env).returncode)
