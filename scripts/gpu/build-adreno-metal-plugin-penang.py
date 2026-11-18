#!/usr/bin/env python3
"""PENANG (moto g53, Linux host): build NativeAdrenoMetal.bundle for ARM64/iOS 17 ABI (our de-PAC'd iOS 26 root).

Same compile and link as scripts/build-adreno-metal-plugin.py --target ios --no-replay, with Linux stand-ins:
run with PATH=/mnt/nvme/xnu-build/unixnu/bin:$PATH (xcrun/clang/strip/dwarfdump wrappers, ld64.lld, theos SDK).
Differences: no -Werror (Linux clang 23 warns where Apple clang does not), the Rust bridge is the one already built by
build-adreno-metal-bridge-penang.py, ad-hoc signatures with theos ldid (no codesign, no CDHash/trust module, which
belong to UniXNU's owner trust cache), no adrenoprobed daemon. Output: build/adreno-metal-plugin/NativeAdrenoMetal.bundle."""
import hashlib
import json
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LDID = '/mnt/nvme/xnu-build/theos/toolchain/linux/iphone/bin/ldid'
OUT = ROOT / 'build/adreno-metal-plugin'
bundle = OUT / 'NativeAdrenoMetal.bundle'
if OUT.exists():
    shutil.rmtree(OUT)
bundle.mkdir(parents=True)
sdk = subprocess.check_output(['xcrun', '--sdk', 'iphoneos', '--show-sdk-path'], text=True).strip()
base = ['xcrun', 'clang', '-target', 'arm64-apple-ios17.0', '-isysroot', sdk, '-O2', '-g', '-Wall', '-Wextra',
        '-fstack-protector-strong']
source_hash = hashlib.sha256()
for path in sorted((ROOT / 'drivers/AdrenoMetal').rglob('*')):
    if path.is_file() and '.git' not in path.parts and path.relative_to(ROOT / 'drivers/AdrenoMetal').parts[0] != 'tools' and \
            path.suffix in ('.h', '.mm', '.cpp', '.rs', '.patch'):
        source_hash.update(str(path.relative_to(ROOT / 'drivers/AdrenoMetal')).encode())
        source_hash.update(path.read_bytes())
metal_build_id = source_hash.hexdigest()
base += ['-DNATIVE_METAL_BUILD_ID="' + metal_build_id + '"']
manifest = {'metal_source_sha256': metal_build_id, 'target': 'ios', 'host': 'penang-linux'}
VULKAN_INCLUDE = ROOT / '.cache/mesa-work/include'
TURNIP = ROOT / 'build/mesa-tu-ios/src/freedreno/vulkan/libvulkan_freedreno.dylib'
if not TURNIP.is_file():
    raise SystemExit('Build Turnip first: python3 scripts/build-turnip-darwin.py --target ios')
profile = TURNIP.parents[3] / 'builtin-build-profile.json'
if profile.is_file():
    manifest['turnip'] = json.loads(profile.read_text())
subprocess.run([sys.executable, ROOT / 'scripts/gen-turnip-smoke-shaders.py'], check=True)
(ROOT / 'build/turnip-smoke/TurnipReplay.h').unlink(missing_ok=True)          # --no-replay
BRIDGE = ROOT / 'build/adreno-metal-bridge/ios/libadreno_metal_bridge.a'
if not BRIDGE.is_file():
    raise SystemExit('Build the bridge first: scripts/build-adreno-metal-bridge-penang.py --target ios --source <metal2vulkan>')
bridge_identity = json.loads(BRIDGE.with_suffix('.a.json').read_text())['identity']
manifest['component'] = subprocess.check_output(['git', '-C', str(ROOT / 'drivers/AdrenoMetal'), 'rev-parse', 'HEAD'], text=True).strip()
manifest['bridge_component'] = bridge_identity['component']
manifest['runtime_draw_checks'] = False
uuid = re.search(r'UUID:\s+([0-9a-fA-F-]{36})', subprocess.check_output(['xcrun', 'dwarfdump', '--uuid', str(TURNIP)], text=True))
if not uuid:
    raise SystemExit('Turnip must provide a Mach-O UUID for the shader cache identity')
manifest['runtime'] = bridge_identity['runtime']
manifest['turnip_uuid'] = uuid[1].replace('-', '').lower()
manifest['cache_build'] = manifest['runtime'] + '-' + manifest['turnip_uuid']
(bundle / 'gpu-build.json').write_text(json.dumps(manifest, indent=2) + '\n')
pm4 = OUT / 'AdrenoPM4.o'
subprocess.run([*base, '-std=c11', '-c', ROOT / 'kits/AdrenoPM4/AdrenoPM4.c', '-o', pm4], check=True)
exe = bundle / 'NativeAdrenoMetal'
subprocess.run([*(['xcrun', 'clang++'] + base[2:]), '-std=c++17', '-fobjc-arc', '-Wno-deprecated-declarations', '-bundle',
                '-I', ROOT / 'drivers/Adreno740', '-I', ROOT / 'kits/AdrenoPM4', '-I', VULKAN_INCLUDE, '-I', ROOT / 'build/turnip-smoke',
                '-x', 'objective-c++', ROOT / 'drivers/AdrenoMetal/NativeAdrenoMetalPlugin.mm',
                ROOT / 'drivers/AdrenoMetal/NativeBridgeMetalFrontend.mm', '-x', 'none', pm4, BRIDGE,
                '-Wl,-dead_strip', '-lobjc', '-framework', 'Foundation', '-framework', 'Metal', '-framework', 'IOSurface', '-o', exe],
               check=True)
subprocess.run(['strip', '-x', exe], check=True)
turnip_lib = bundle / 'libvulkan_freedreno.dylib'
shutil.copyfile(TURNIP, turnip_lib)
subprocess.run(['strip', '-x', turnip_lib], check=True)
subprocess.run([sys.executable, ROOT / 'scripts/macho-self-bind-weak-imports.py', turnip_lib], check=True)
(bundle / 'Info.plist').write_bytes(plistlib.dumps(dict(
    CFBundleIdentifier='org.blu-sharky.NativeAdrenoMetal', CFBundleExecutable='NativeAdrenoMetal', CFBundlePackageType='BNDL',
    CFBundleVersion='1', CFBundleShortVersionString='1', NSPrincipalClass='NativeAdrenoMetalDevice', MinimumOSVersion='17.0'),
    fmt=plistlib.FMT_XML))
for binary, ident in ((turnip_lib, 'org.blu-sharky.turnip'), (exe, 'org.blu-sharky.NativeAdrenoMetal')):
    subprocess.run([LDID, '-S', '-I' + ident, binary], check=True)
header = exe.read_bytes()[:16]
magic, cputype, subtype = (int.from_bytes(header[i:i + 4], 'little') for i in (0, 4, 8))
assert (magic, cputype, subtype & 0xffffff) == (0xfeedfacf, 0x100000c, 0), 'expected an ARM64 Mach-O'
print('PASS: penang NativeAdrenoMetal.bundle (%d + %d bytes, ad-hoc signed)' % (exe.stat().st_size, turnip_lib.stat().st_size))
