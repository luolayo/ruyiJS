#ifndef RUYIJS_PIPE_ASYNC_H
#define RUYIJS_PIPE_ASYNC_H
#include "runtime/pipe.h"
#ifdef _WIN32
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <windows.h>
#endif
#include <cstdint>
#include <deque>

namespace ruyijs {
#ifdef _WIN32
using PipeHandle = HANDLE;
using PipeCount = DWORD;
#else
using PipeHandle = int;
using PipeCount = uint32_t;
#endif
struct PipeOperation {
#ifdef _WIN32
  OVERLAPPED value{};
#endif
  bool pending = false;
};
// The buffers passed to Windows remain in this object or at the front of its
// deque until their own completion is harvested, including cancellation.
struct PipeAsync {
  PipeOperation accept, read, write;
  bool server = false, connected = false, received = false;
  PipeResult terminal = PipeResult::Pending;
  uint32_t readLength = 0, writeLength = 0;
  size_t readOffset = 0, writeOffset = 0, queuedBytes = 0;
  bool readingBody = false;
  std::string incoming;
  std::deque<std::string> outgoing;
  PipeAsync();
  ~PipeAsync();
  bool Valid() const;
};
PipeAsync* NewPipeAsync();
#ifdef _WIN32
void CancelPipeOperation(HANDLE pipe, PipeOperation& operation);
PipeResult PipeError(DWORD error);
#else
bool ConfigurePipeSocket(int socket, bool asynchronous);
#endif
PipeResult PipeAccept(PipeHandle& pipe, PipeAsync& state);
PipeResult PipeIo(PipeHandle pipe, PipeOperation& operation, bool writing,
                   void* bytes, PipeCount size, PipeCount* transferred);
PipeResult PipeRead(PipeHandle pipe, PipeAsync& state);
PipeResult PipeWrite(PipeHandle pipe, PipeAsync& state);
}
#endif
