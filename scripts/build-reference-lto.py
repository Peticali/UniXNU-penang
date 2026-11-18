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
