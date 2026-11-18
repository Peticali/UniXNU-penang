#!/bin/bash
# An LTO-capable ld64 for the iPadOS 27 RELEASE comparison kernel (scripts/build-reference-lto.py), next to the
# UniXNU Linux toolchain and without touching it:
#   <toolchain>/ld64-lto/bin/ld          cctools-port at the toolchain's ref, --enable-lto-support
#   <toolchain>/ld64-lto/lib/libLTO.so   libLTO of the toolchain's LLVM commit (CROSS_CLANG's bitcode), AArch64 only
#   scripts/setup-ld64-lto.sh [TOOLCHAIN_DIR]   (default /mnt/nvme/xnu-build/unixnu/toolchain)
set -eu
T=${1:-/mnt/nvme/xnu-build/unixnu/toolchain}
P=$T/ld64-lto
DISPATCH=$T/prefix/CommandLineTools/usr/libdispatch
CCTOOLS_REF=$(sed -n "s/^CCTOOLS_PORT_REF = '\(.*\)'/\1/p" "$T/setup-toolchain-nvme.py")
LLVM_COMMIT=$(sed -n "s/^LLVM_COMMIT = '\(.*\)'/\1/p" "$T/setup-toolchain-nvme.py")
mkdir -p "$T/src" "$P/lib"

if [ ! -x "$P/bin/ld" ]; then
	S=$T/src/cctools-port-lto
	[ -d "$S" ] || git clone -q https://github.com/tpoechtrager/cctools-port.git "$S"
	git -C "$S" checkout -q "$CCTOOLS_REF"
	cd "$S/cctools"
	CC=clang CXX=clang++ ./configure --prefix="$P" --target=arm64-apple-darwin --program-prefix= --enable-lto-support \
		--with-llvm-config="$(command -v llvm-config)" --with-libdispatch="$DISPATCH" --with-libblocksruntime="$DISPATCH"
	make -j"$(nproc)" PROGRAM_PREFIX=
	make install PROGRAM_PREFIX=
fi

if [ ! -f "$P/lib/libLTO.so" ]; then
	S=$T/src/llvm-${LLVM_COMMIT:0:8}
	mkdir -p "$S"; cd "$S"
	[ -d .git ] || { git init -q; git remote add origin https://github.com/llvm/llvm-project; }
	git fetch -q --depth 1 origin "$LLVM_COMMIT"; git checkout -q FETCH_HEAD
	cmake -G Ninja -S llvm -B build -DLLVM_TARGETS_TO_BUILD=AArch64 -DCMAKE_BUILD_TYPE=Release -DLLVM_ENABLE_ASSERTIONS=ON \
		-DLLVM_INCLUDE_TESTS=OFF -DLLVM_INCLUDE_EXAMPLES=OFF -DLLVM_INCLUDE_BENCHMARKS=OFF -DLLVM_PARALLEL_LINK_JOBS=2 \
		-DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++
	ninja -C build LTO
	cp -L build/lib/libLTO.so "$P/lib/libLTO.so"
fi
"$P/bin/ld" -v 2>&1 | head -1
echo "libLTO: $P/lib/libLTO.so"
