#!/usr/bin/env python3
"""Pin one original kernel function to a native symbol in the 24A446 XnuPrelink fixture.

  scripts/pin-function.py ORIGINAL_ADDRESS NATIVE_SYMBOL "EVIDENCE"

ORIGINAL_ADDRESS is the function in Apple's kernelcache (0xfffffe..., as scripts/unmapped-call.py prints it). Its
size and digest are taken from XnuPrelink's own function boundaries, as the matcher checks them. Regenerate
patches/unixnu/0007 afterwards (git -C ../UniXNU/kits/XnuPrelink diff fixtures/ > patches/unixnu/0007-...).
"""
import hashlib
import json
import os
import sys
from pathlib import Path

UNIXNU = Path(os.environ.get('UNIXNU', '/mnt/nvme/xnu-build/unixnu/UniXNU'))
KC = Path(os.environ.get('UNIXNU_KERNELCACHE', '/mnt/nvme/xnu-build/ios26/kc/24A446__iPad17,3/24A446__iPad17,1_2_3_4/'
                                               'kernelcache.release.iPad17,1_2_3_4'))
FIXTURE = UNIXNU / 'kits/XnuPrelink/fixtures/fileset-24A446-symbols.json'
sys.path.insert(0, str(UNIXNU / 'kits/XnuPrelink'))
from kc_image import Image            # noqa: E402
from fileset_match import Side        # noqa: E402

address, symbol, evidence = int(sys.argv[1], 16), sys.argv[2], sys.argv[3]
raw = KC.read_bytes()
cache = Image(raw)
_, at = cache.entries['com.apple.kernel']
entry = Image(raw, at)
fn = Side(entry, cache.fixups(), entry.mapped()).functions.get(address)
if fn is None:
    sys.exit(f'{address:#x} is not a function start of the original kernel')
body = entry.read(address, fn['end'] - address)
text = FIXTURE.read_text()
fixture = json.loads(text)
if any(int(e['original'], 16) == address for e in fixture['functions']):
    sys.exit(f'{address:#x} is pinned already')
fixture['functions'].append({'original': f'{address:#x}', 'original_size': len(body),
                             'original_sha256': hashlib.sha256(body).hexdigest(), 'native_symbol': symbol,
                             'evidence': evidence})
FIXTURE.write_text(json.dumps(fixture, indent=2, ensure_ascii=False) + ('\n' if text.endswith('\n') else ''))
print(f'pinned {address:#x} ({len(body)} bytes) -> {symbol}')
