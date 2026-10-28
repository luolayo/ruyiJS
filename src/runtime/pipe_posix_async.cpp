#ifndef _WIN32
#include "runtime/pipe_async.h"
#include <cerrno>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace ruyijs {
namespace {
PipeResult Error(int code) {
  if (code == EINTR || code == EAGAIN || code == EWOULDBLOCK)
    return PipeResult::Pending;
  if (code == EPIPE || code == ECONNRESET || code == ENOTCONN)
    return PipeResult::Closed;
  return PipeResult::Failed;
}
}

PipeResult PipeAccept(PipeHandle& pipe, PipeAsync& state) {
  if (state.connected) return PipeResult::Ready;
  if (state.server) {
    const int accepted = accept(pipe, nullptr, nullptr);
    if (accepted < 0) return Error(errno);
    if (!ConfigurePipeSocket(accepted, true)) { close(accepted); return PipeResult::Failed; }
    close(pipe);
    pipe = accepted;
    state.connected = true;
    return PipeResult::Ready;
  }
  pollfd descriptor{pipe, POLLOUT, 0};
  const int ready = poll(&descriptor, 1, 0);
  if (ready < 0) return Error(errno);
  if (!ready) return PipeResult::Pending;
  int error = 0;
  socklen_t length = sizeof(error);
  if (getsockopt(pipe, SOL_SOCKET, SO_ERROR, &error, &length) < 0) return Error(errno);
  if (error) return Error(error);
  if (!(descriptor.revents & POLLOUT)) return PipeResult::Failed;
  state.connected = true;
  return PipeResult::Ready;
}

PipeResult PipeIo(PipeHandle pipe, PipeOperation&, bool writing,
                    void* bytes, PipeCount size, PipeCount* transferred) {
  *transferred = 0;
#ifdef MSG_NOSIGNAL
  constexpr int flags = MSG_NOSIGNAL;
#else
  constexpr int flags = 0;
#endif
  const auto count = writing ? send(pipe, bytes, size, flags) : recv(pipe, bytes, size, 0);
  if (count < 0) return Error(errno);
  if (!count) return PipeResult::Closed;
  *transferred = static_cast<PipeCount>(count);
  return PipeResult::Ready;
}
}
#endif
