#ifndef _WIN32
#include "runtime/pipe_async.h"
#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

namespace ruyijs {
bool ConfigurePipeSocket(int socket, bool asynchronous) {
  const int flags = fcntl(socket, F_GETFD);
  if (flags < 0 || fcntl(socket, F_SETFD, flags | FD_CLOEXEC) < 0) return false;
  const int status = fcntl(socket, F_GETFL);
  if (status < 0 || fcntl(socket, F_SETFL,
      asynchronous ? status | O_NONBLOCK : status & ~O_NONBLOCK) < 0) return false;
#ifdef SO_NOSIGPIPE
  const int enabled = 1;
  if (setsockopt(socket, SOL_SOCKET, SO_NOSIGPIPE, &enabled, sizeof(enabled)) < 0)
    return false;
#endif
  return true;
}

namespace {
bool Address(const char* name, sockaddr_un* address) {
  if (!name || name[0] != '/' || strlen(name) >= sizeof(address->sun_path))
    return false;
  *address = {};
  address->sun_family = AF_UNIX;
  memcpy(address->sun_path, name, strlen(name) + 1);
  return true;
}
}

bool Pipe::Connect(const char* name) { return OpenClient(name, false); }
bool Pipe::OpenClient(const char* name, bool asynchronous) {
  sockaddr_un address{};
  if (IsOpen() || !Address(name, &address)) return false;
  const int socket = ::socket(AF_UNIX, SOCK_STREAM, 0);
  if (socket < 0) return false;
  if (!ConfigurePipeSocket(socket, asynchronous)) { close(socket); return false; }
  const int result = connect(socket, reinterpret_cast<sockaddr*>(&address), sizeof(address));
  if (result < 0 && !(asynchronous && errno == EINPROGRESS)) {
    close(socket);
    return false;
  }
  handle_ = socket;
  return true;
}

bool Pipe::Listen(const char* name) { return OpenServer(name, false); }
bool Pipe::OpenServer(const char* name, bool asynchronous) {
  sockaddr_un address{};
  if (IsOpen() || !Address(name, &address)) return false;
  const int socket = ::socket(AF_UNIX, SOCK_STREAM, 0);
  if (socket < 0) return false;
  if (!ConfigurePipeSocket(socket, asynchronous) ||
      bind(socket, reinterpret_cast<sockaddr*>(&address), sizeof(address)) < 0) {
    // A failed bind never owns the path and must not unlink another listener.
    close(socket);
    return false;
  }
  if (listen(socket, 1) < 0) { close(socket); unlink(name); return false; }
  handle_ = socket;
  socketPath_ = name;
  return true;
}

bool Pipe::Accept() {
  if (!IsOpen() || async_ || socketPath_.empty()) return false;
  int accepted;
  do { accepted = accept(handle_, nullptr, nullptr); } while (accepted < 0 && errno == EINTR);
  if (accepted < 0) return false;
  if (!ConfigurePipeSocket(accepted, false)) { close(accepted); return false; }
  close(handle_);
  handle_ = accepted;
  return true;
}

bool Pipe::Transfer(void* data, unsigned length, bool writing) {
  if (!IsOpen() || async_) return false;
  auto* bytes = static_cast<char*>(data);
  while (length) {
#ifdef MSG_NOSIGNAL
    constexpr int flags = MSG_NOSIGNAL;
#else
    constexpr int flags = 0;
#endif
    const auto count = writing ? send(handle_, bytes, length, flags)
                               : recv(handle_, bytes, length, 0);
    if (count < 0 && errno == EINTR) continue;
    if (count <= 0) return false;
    bytes += count;
    length -= static_cast<unsigned>(count);
  }
  return true;
}

void Pipe::Close() {
  if (IsOpen()) { close(handle_); handle_ = -1; }
  delete async_;
  async_ = nullptr;
  if (!socketPath_.empty()) {
    unlink(socketPath_.c_str());
    socketPath_.clear();
  }
}
}
#endif
