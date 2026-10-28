#ifdef _WIN32
#include "resource_network/necko_pipe.h"
#include <string>

namespace ruyijs::resource_network {
uint32_t NeckoRemaining(uint64_t deadline) {
  const auto now = GetTickCount64();
  return now >= deadline ? 0 : DWORD(deadline - now);
}
bool NeckoPipe::Open(bool parentWrites) {
  static LONG sequence = 0;
  const auto name = L"\\\\.\\pipe\\ruyijs-necko-" + std::to_wstring(GetCurrentProcessId()) +
      L"-" + std::to_wstring(GetTickCount64()) + L"-" + std::to_wstring(InterlockedIncrement(&sequence));
  parent_.Reset(CreateNamedPipeW(name.c_str(),
      (parentWrites ? PIPE_ACCESS_OUTBOUND : PIPE_ACCESS_INBOUND) |
          FILE_FLAG_OVERLAPPED | FILE_FLAG_FIRST_PIPE_INSTANCE,
      PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT | PIPE_REJECT_REMOTE_CLIENTS,
      1, 65536, 65536, 0, nullptr));
  if (!parent_) return false;
  SECURITY_ATTRIBUTES inherit{sizeof(inherit), nullptr, TRUE};
  child_.Reset(CreateFileW(name.c_str(), parentWrites ? GENERIC_READ : GENERIC_WRITE,
      0, &inherit, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr));
  event_.Reset(CreateEventW(nullptr, TRUE, FALSE, nullptr));
  if (!child_ || !event_) return false;
  OVERLAPPED connected{};
  connected.hEvent = event_.Get();
  // The local client was opened first, so connect completes immediately.
  if (ConnectNamedPipe(parent_.Get(), &connected)) return true;
  const DWORD error = GetLastError();
  if (error == ERROR_IO_PENDING) {
    DWORD ignored = 0;
    CancelIoEx(parent_.Get(), &connected);
    GetOverlappedResult(parent_.Get(), &connected, &ignored, TRUE);
  }
  return error == ERROR_PIPE_CONNECTED;
}
bool NeckoPipe::Transfer(void* data, uint32_t size, bool writing, uint64_t deadline) {
  auto* bytes = static_cast<char*>(data);
  uint32_t done = 0;
  while (done < size) {
    if (!NeckoRemaining(deadline)) return false;
    OVERLAPPED io{};
    io.hEvent = event_.Get();
    if (!ResetEvent(io.hEvent)) return false;
    DWORD moved = 0;
    const DWORD amount = size - done > 65536 ? 65536 : size - done;
    const BOOL ready = writing ?
        WriteFile(parent_.Get(), bytes + done, amount, &moved, &io) :
        ReadFile(parent_.Get(), bytes + done, amount, &moved, &io);
    if (!ready) {
      if (GetLastError() != ERROR_IO_PENDING) return false;
      if (WaitForSingleObject(io.hEvent, NeckoRemaining(deadline)) != WAIT_OBJECT_0) {
        CancelIoEx(parent_.Get(), &io);
        // Complete cancellation before the OVERLAPPED or caller buffer dies.
        GetOverlappedResult(parent_.Get(), &io, &moved, TRUE);
        return false;
      }
      if (!GetOverlappedResult(parent_.Get(), &io, &moved, FALSE)) return false;
    }
    if (!moved || moved > amount) return false;
    done += moved;
  }
  return true;
}
bool NeckoPipe::Write(const void* data, uint32_t size, uint64_t deadline) {
  return Transfer(const_cast<void*>(data), size, true, deadline);
}
bool NeckoPipe::Read(void* data, uint32_t size, uint64_t deadline) {
  return Transfer(data, size, false, deadline);
}
}

#endif
