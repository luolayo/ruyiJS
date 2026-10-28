#ifndef RUYIJS_NECKO_PIPE_H
#define RUYIJS_NECKO_PIPE_H
#include "runtime/platform_process.h"
#ifdef _WIN32
#include <windows.h>
#endif
#include <cstdint>

namespace ruyijs::resource_network {
#ifdef _WIN32
class NeckoHandle {
 public:
  explicit NeckoHandle(HANDLE value = nullptr) : value_(value) {}
  ~NeckoHandle() { Reset(); }
  NeckoHandle(const NeckoHandle&) = delete;
  NeckoHandle& operator=(const NeckoHandle&) = delete;
  HANDLE Get() const { return value_; }
  explicit operator bool() const { return value_ && value_ != INVALID_HANDLE_VALUE; }
  void Reset(HANDLE value = nullptr) {
    if (*this) CloseHandle(value_);
    value_ = value;
  }
 private:
  HANDLE value_;
};
#else
class NeckoHandle {
 public:
  explicit NeckoHandle(int value = -1) : value_(value) {}
  ~NeckoHandle() { Reset(); }
  NeckoHandle(const NeckoHandle&) = delete;
  NeckoHandle& operator=(const NeckoHandle&) = delete;
  int Get() const { return value_; }
  explicit operator bool() const { return value_ >= 0; }
  void Reset(int value = -1) { if (*this) close(value_); value_ = value; }
 private:
  int value_;
};
#endif
uint32_t NeckoRemaining(uint64_t deadline);
class NeckoPipe {
 public:
  bool Open(bool parentWrites);
  auto Child() const { return child_.Get(); }
  void CloseChild() { child_.Reset(); }
  void CloseParent() { parent_.Reset(); }
  bool Write(const void* data, uint32_t size, uint64_t deadline);
  bool Read(void* data, uint32_t size, uint64_t deadline);
 private:
  bool Transfer(void* data, uint32_t size, bool writing, uint64_t deadline);
  NeckoHandle parent_, child_, event_;
};
}
#endif
