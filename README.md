# UniXNU-penang — Motorola moto g53 5G (XT2335, SM4350 "holi")

Device repository for [UniXNU](https://github.com/UniXNU/UniXNU): only what this board needs. Shared SM4350 support
lives in `UniXNU-sm4350-common`; the firmware is the separate `uefi-penang` (Mu-Silicium fork, branch `penang`).

Goal: iOS 27.0.1 (UniXNU's maintained `ipados-27.0.1-24A446` kernel profile, as is; iPhone12,1 24A446 userland) on a CPU without pointer authentication
(Cortex-A76/A55). That profile is arm64e; this board builds and prelinks it exactly as UniXNU does, then rewrites the
finished kernel (and Apple's kexts in it) without PAC, 1:1 (retaa/b -> ret, braa/blraa -> br/blr,
pac*/aut*/xpac* -> nop, auth bits of the chained fixups cleared). Proven on this phone: a de-PAC'd AppleMatch loads and
starts from a XnuPrelink fileset.

## Status (2026-11-18)

| Stage | State |
| --- | --- |
| UEFI (uefi-penang) | boots from RAM, display kept alive across ClockDxe, UniXNU menu shown |
| UniXNU payload + DarwinBoot | boot the **penang XNU port's** kernel to SpringBoard (interim: `scripts/mkunixnu-payload.py`) |
| UniXNU kernel (XnuPrelink + Apple kexts, no PAC) | pending: toolchain, de-PAC prelink step, holi drivers |

Known: the system resets ~40-70 s after SpringBoard (PS_HOLD), as on the old shim path; under investigation.

## Local patches to UniXNU (until upstreamed)

- `patches/unixnu/0001-ramdisk-find-payload-inside-initrd.patch`: penang's ABL puts vendor_boot's ramdisk before the
  boot image's, so the payload FAT does not start at `linux,initrd-start`; search it (4-byte aligned).
- `patches/unixnu/0002-darwinboot-32mb-base-for-16k-kernel.patch`: only for the interim 16 KiB-page penang kernel
  (start.s maps 32 MiB L2 blocks from physBase).
- `patches/unixnu/0003-kernel-xnu-arch-override.patch`: `[kernel] xnu_arch` builds the xnu-12377 (arm64e) series as
  plain arm64, with the Linux deployment target taken from the profile.
- `patches/unixnu/0004-xnuprelink-penang-layout.patch`: the native `__DATA` may grow into the old `__PRELINK_INFO`.

Kernelcache: `scripts/kextpac/make-kernelcache.sh` fetches the profile's kernelcache (pinned sha256) and rewrites it
without PAC, resealing corecrypto's FIPS HMAC; `scripts/env.sh` hands it to the prelink.

## Boot

    fastboot boot <boot image>     # never flash: RAM boot only

The interim payload script needs `tools/adt.py` and `tools/mkpayload.py` of the penang XNU port next to it.

## Credits

- [UniXNU](https://github.com/UniXNU/UniXNU) (BSD-2-Clause-Patent): boot manager, DarwinBoot, XnuPrelink and the
  `ipados-27.0.1-24A446` profile this board uses unchanged (its no-PAC differences are `[os_overrides]` in board.toml).
- [IOS-26-Hot](https://github.com/nithinyadavamaraboina-online/IOS-26-Hot) (MIT, (c) 2026 dipa-studio): the userland
  de-PAC rewriter (`de-pac-arm64e.py`) whose 1:1 rules `scripts/kextpac/depac_kc.py` applies to the kexts, and the
  iOS 26 root and kernel patch base of the penang XNU port.
- [Bergamota](https://github.com/ry-diffusion/bergamota): prior art for iOS on a CPU without PAC (no code used).
- [Project Silicium](https://github.com/Project-Silicium/Mu-Silicium): the UEFI base of `uefi-penang`.
