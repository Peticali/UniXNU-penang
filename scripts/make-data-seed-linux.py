#!/usr/bin/env python3
# SPDX-License-Identifier: BSD-2-Clause-Patent
"""First-install APFS Data seed (DBRDISK1 packed) on Linux: UniXNU's scripts/make-data-seed.py with mkapfs and the
linux-apfs-rw module in place of hdiutil, run as root (the seed keeps file owners).

    sudo python3 scripts/make-data-seed-linux.py --unixnu ../UniXNU OS.dmg OUTPUT.dbr --gib 95 [--skip-setup] [--build 24A446]

OS.dmg is the IPSW OS disk image (out/ipsw/<build>/<OS>.dmg), mounted read-only with apfs-fuse. The container is
created at its final size (a sparse file, mkapfs), so UniXNU's seed-data-grow.py (diskutil resizeContainer) is not
needed: packing keeps only the nonzero pages. Contents as make-data-seed.py: private/var of the OS volume without
staged_system_apps, the same empty directories, /tmp 1777, the same Setup and backboardd preferences. Needs apfsprogs
(mkapfs) and linux-apfs-rw (mount -t apfs -o readwrite). Refuses to overwrite OUTPUT: a seed is installation state.
"""
import argparse
import json
import os
from pathlib import Path
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile


def merge(mount, home, name, values):
    path = mount / home / 'Library/Preferences' / (name + '.plist')
    path.parent.mkdir(parents=True, exist_ok=True)
    content = plistlib.loads(path.read_bytes()) if path.is_file() else {}
    content.update(values)
    path.write_bytes(plistlib.dumps(content, fmt=plistlib.FMT_BINARY))
    path.chmod(0o644)


def copy_owner(src, dst):
    st = os.lstat(src)
    os.lchown(dst, st.st_uid, st.st_gid)
    if not stat.S_ISLNK(st.st_mode):
        os.chmod(dst, stat.S_IMODE(st.st_mode))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--unixnu', type=Path, required=True)
    parser.add_argument('os_image', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--gib', type=int, required=True)
    parser.add_argument('--build', default='24A446')
    parser.add_argument('--skip-setup', action='store_true')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('run as root: the seed keeps file owners')
    if args.output.exists():
        parser.error('refuse to overwrite an existing installation seed')
    if not 3 <= args.gib <= 1024:
        parser.error('--gib must be in 3..1024')
    sys.path.insert(0, str(args.unixnu.resolve() / 'drivers/DarwinBoot/Test'))
    import packed_ramdisk
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='new-data-', dir=args.output.parent) as td:
        work = Path(td)
        raw = work / 'seed.raw'
        with raw.open('wb') as f:
            f.truncate(args.gib << 30)
        subprocess.run(['mkapfs', '-L', 'Data', str(raw)], check=True)
        osm, mount = work / 'os', work / 'mount'
        osm.mkdir()
        mount.mkdir()
        subprocess.run(['apfs-fuse', '-o', 'allow_other', str(args.os_image), str(osm)], check=True)
        mounted = False
        try:
            source = osm / 'root/private/var'
            if not (osm / 'root/sbin/launchd').is_file() or not source.is_dir():
                raise SystemExit('not an IPSW OS volume')
            subprocess.run(['modprobe', 'apfs'], check=True)
            subprocess.run(['mount', '-t', 'apfs', '-o', 'loop,readwrite', str(raw), str(mount)], check=True)
            mounted = True
            copy_owner(source, mount)
            for current, dirs, files in os.walk(source, followlinks=False):
                dirs[:] = [name for name in dirs if name != 'staged_system_apps']
                dest = mount / Path(current).relative_to(source)
                dest.mkdir(exist_ok=True)
                copy_owner(current, dest)
                for name in list(dirs) + files:
                    src, dst = Path(current) / name, dest / name
                    if src.is_symlink():
                        dst.symlink_to(os.readlink(src))
                        copy_owner(src, dst)
                        if name in dirs:
                            dirs.remove(name)
                    elif src.is_file():
                        shutil.copy2(src, dst)
                        copy_owner(src, dst)
            for name in ('keybags', 'mobile/tmp', 'tmp', 'run', 'containers/Bundle',
                         'containers/Data/System', 'containers/Shared/SystemGroup', 'containers/Temp'):
                (mount / name).mkdir(parents=True, exist_ok=True)
            (mount / 'tmp').chmod(0o1777)
            # mobile's own tmp (launchd's fixup-mobile-tmp skips an existing directory): owned by mobile, as UniXNU-opi5plus found,
            # or the daemons that run as mobile (biomed, callservicesd, nsurlsessiond) exit 1 at startup and backboardd waits on biomed.
            os.chown(mount / 'mobile/tmp', 501, 501)
            (mount / 'mobile/tmp').chmod(0o755)
            if args.skip_setup:
                merge(mount, 'mobile', 'com.apple.purplebuddy', dict(SetupDone=True,
                      SetupFinishedAllSteps=True, SetupVersion=11, daemonizeNeedsToRun=False))
                merge(mount, 'mobile', 'com.apple.purplebuddy.notbackedup', {name: False for name in (
                    'ShouldRunDiagnosticsMiniBuddy', 'ShouldRunHSA2MiniBuddy', 'ShouldRunKeychainSyncMiniBuddy',
                    'ShouldRunMesaMiniBuddy', 'ShouldRunPaymentMiniBuddy', 'ShouldRunStandardMiniBuddy', 'SilentICDPUpgrade')})
                merge(mount, 'mobile', 'com.apple.managedconfiguration.notbackedup',
                      dict(LockdownActivationIndicatesCloudConfigurationAvailable=False))
                merge(mount, 'mobile', 'com.apple.springboard', dict(BKNoWatchdogs=True,
                      FBLaunchWatchdogExceptions={'com.apple.purplebuddy': 100.0}, MCForceShowCloudConfigurationUI=False))
                merge(mount, 'mobile', 'com.apple.migration', dict(LastSystemVersion=args.build,
                      DMUserDataDisposition=dict(SyntheticDidUpgrade=False, buildVersion=args.build)))
            for home in ('root', 'mobile'):
                for name in ('backboardd', '.GlobalPreferences'):
                    merge(mount, home, name, dict(CAEnableDeepFramebuffer=False,
                          CAEnableFramebufferCompression=False, CAEnableIOSurfaceCompression=False))
        finally:
            if mounted:
                subprocess.run(['umount', str(mount)], check=True)
            subprocess.run(['fusermount3', '-u', str(osm)], check=False)
        subprocess.run(['fsck.apfs', str(raw)], check=False)
        candidate = work / 'data.dbr'
        packed_ramdisk.pack(raw, candidate)
        candidate.replace(args.output)
    owner = os.environ.get('SUDO_UID'), os.environ.get('SUDO_GID')
    if all(owner):
        os.chown(args.output, int(owner[0]), int(owner[1]))
    print(json.dumps(dict(output=str(args.output), gib=args.gib, first_install=True, preserve_for_future_builds=True)))


if __name__ == '__main__':
    main()
