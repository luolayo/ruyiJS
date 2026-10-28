#pragma once
#include <cstdint>
#include <cstddef>

using ReadCallback = int (*)(void*, uint8_t*, uint32_t, uint32_t*);
using WriteCallback = int (*)(void*, const uint8_t*, uint32_t);
using WriteSomeCallback = int (*)(void*, const uint8_t*, uint32_t, uint32_t*);
using CancelCallback = int (*)(void*);
using VerifyCallback = int (*)(void*, const uint8_t*, uint32_t);
using DecodeCallback = int (*)(void*, uint16_t, const uint8_t*, uint32_t, uint8_t*, uint32_t);

// Public C ABI recovered from the distributed Python adapter's ctypes signatures.
#define NECKO_API extern "C" __attribute__((visibility("default")))
