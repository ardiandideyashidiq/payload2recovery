CC ?= gcc
CFLAGS ?= -O2 -Wall -Wextra -pedantic -std=c11

NDK_DIR ?= /home/rd/Android/Sdk/ndk/29.0.14206865
NDK_BIN ?= $(NDK_DIR)/toolchains/llvm/prebuilt/linux-x86_64/bin
AARCH64_CC ?= $(NDK_BIN)/aarch64-linux-android30-clang
AARCH64_STRIP ?= $(NDK_BIN)/llvm-strip

TARGET_HOST = wipe-super-host
TARGET_ARM64 = superwipe
INSTALL_DEST = ../../src/payload2recovery/assets/tools/$(TARGET_ARM64)

all: host arm64

host: $(TARGET_HOST)

arm64: $(TARGET_ARM64)

$(TARGET_HOST): wipe-super.c
	$(CC) $(CFLAGS) -o $@ $<

$(TARGET_ARM64): wipe-super.c
	$(AARCH64_CC) -O2 -static -Wall -Wextra -o $@ $<
	$(AARCH64_STRIP) --strip-all $@

install: $(TARGET_ARM64)
	cp $(TARGET_ARM64) $(INSTALL_DEST)
	chmod 755 $(INSTALL_DEST)

clean:
	rm -f $(TARGET_HOST) $(TARGET_ARM64)

.PHONY: all host arm64 install clean
