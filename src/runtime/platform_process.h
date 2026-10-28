#pragma once
#include <chrono>
#include <cstdint>
#include <string>
#include <string_view>
#include <algorithm>
#include <thread>
#ifdef _WIN32
#include <windows.h>
#else
#include <codecvt>
#include <locale>
#include <mach-o/dyld.h>
#include <unistd.h>
#endif

namespace ruyijs {
inline uint64_t MonotonicMilliseconds() {
#ifdef _WIN32
  return GetTickCount64();
#else
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
#endif
}
inline uint64_t CurrentProcessId() {
#ifdef _WIN32
  return GetCurrentProcessId();
#else
  return getpid();
#endif
}
inline void SleepMilliseconds(unsigned value) {
  std::this_thread::sleep_for(std::chrono::milliseconds(value));
}
#ifndef _WIN32
inline std::wstring WidePath(const std::string& value) {
  return std::wstring_convert<std::codecvt_utf8<wchar_t>>().from_bytes(value);
}
inline std::string Utf8Path(std::wstring_view value) {
  return std::wstring_convert<std::codecvt_utf8<wchar_t>>().to_bytes(value.data(), value.data() + value.size());
}
inline std::string ExecutablePath() {
  uint32_t length = 0;
  _NSGetExecutablePath(nullptr, &length);
  std::string path(length, '\0');
  if (_NSGetExecutablePath(path.data(), &length)) return {};
  path.resize(std::char_traits<char>::length(path.data()));
  return path;
}
#endif
}
