#include "core.h"
#include <algorithm>
#include <cerrno>
#include <chrono>
#include <climits>
#include <cstring>
#include <fcntl.h>
#include <memory>
#include <string>
#include <cstdlib>
#include <netdb.h>
#include <poll.h>
#include <sys/socket.h>
#include <unistd.h>

namespace {
struct Socket {
  int fd = -1;
  ~Socket() { if (fd >= 0) close(fd); }
};
uint64_t Now() {
  return std::chrono::duration_cast<std::chrono::milliseconds>(
      std::chrono::steady_clock::now().time_since_epoch()).count();
}
int Wait(int fd, short events, uint64_t deadline, CancelCallback cancel = nullptr, void* context = nullptr) {
  for (;;) {
    if (cancel && cancel(context)) return 6;
    const auto now = Now();
    if (now >= deadline) return 5;
    pollfd descriptor{fd, events, 0};
    int wait = int(std::min<uint64_t>(deadline - now, cancel ? 25 : INT_MAX));
    int result = poll(&descriptor, 1, wait);
    if (result < 0 && errno == EINTR) continue;
    if (result < 0) return 6;
    if (!result) continue;
    if (descriptor.revents & POLLNVAL) return 6;
    return 0;
  }
}
}
NECKO_API int necko_socket_open_cancellable(const char* host, uint16_t port, uint32_t timeout,
    CancelCallback cancel, void* context, void** output) {
  *output = nullptr;
  addrinfo hints{}; hints.ai_family = AF_UNSPEC; hints.ai_socktype = SOCK_STREAM;
  addrinfo* addresses = nullptr;
  const std::string service = std::to_string(port);
  // The Python owner resolves hostnames in a cancellable worker before this call.
  hints.ai_flags = AI_NUMERICHOST | AI_NUMERICSERV;
  if (getaddrinfo(host, service.c_str(), &hints, &addresses)) return 2;
  std::unique_ptr<addrinfo, decltype(&freeaddrinfo)> owner(addresses, freeaddrinfo);
  const uint64_t deadline = Now() + timeout;
  int failure = 6;
  for (auto* address = addresses; address; address = address->ai_next) {
    auto socket = std::make_unique<Socket>();
    socket->fd = ::socket(address->ai_family, SOCK_STREAM, 0);
    if (socket->fd < 0) continue;
    const int enabled = 1;
    if (fcntl(socket->fd, F_SETFL, O_NONBLOCK) || fcntl(socket->fd, F_SETFD, FD_CLOEXEC) ||
        setsockopt(socket->fd, SOL_SOCKET, SO_NOSIGPIPE, &enabled, sizeof(enabled))) continue;
    if (connect(socket->fd, address->ai_addr, address->ai_addrlen) < 0) {
      if (errno != EINPROGRESS) continue;
      failure = Wait(socket->fd, POLLOUT, deadline, cancel, context);
      if (failure) continue;
      int error = 0; socklen_t length = sizeof(error);
      if (getsockopt(socket->fd, SOL_SOCKET, SO_ERROR, &error, &length) || error) { failure = 6; continue; }
    }
    *output = socket.release(); return 0;
  }
  return failure;
}
NECKO_API int necko_socket_open(const char* host, uint16_t port, uint32_t timeout, void** output) {
  return necko_socket_open_cancellable(host, port, timeout, nullptr, nullptr, output);
}
NECKO_API void necko_socket_close(void* handle) { delete static_cast<Socket*>(handle); }
NECKO_API void necko_socket_interrupt(void* handle) { shutdown(static_cast<Socket*>(handle)->fd, SHUT_RDWR); }
NECKO_API int necko_socket_idle(void* handle) {
  uint8_t byte;
  auto size = recv(static_cast<Socket*>(handle)->fd, &byte, 1, MSG_PEEK | MSG_DONTWAIT);
  return size < 0 && (errno == EAGAIN || errno == EWOULDBLOCK);
}
NECKO_API int necko_socket_peer(void* handle, char* host, uint32_t capacity, uint16_t* port) {
  sockaddr_storage address{}; socklen_t size = sizeof(address);
  if (getpeername(static_cast<Socket*>(handle)->fd, reinterpret_cast<sockaddr*>(&address), &size)) return 6;
  char service[16];
  if (getnameinfo(reinterpret_cast<sockaddr*>(&address), size, host, capacity,
                  service, sizeof(service), NI_NUMERICHOST | NI_NUMERICSERV)) return 6;
  *port = uint16_t(std::strtoul(service, nullptr, 10)); return 0;
}
NECKO_API int necko_socket_read(void* handle, uint8_t* bytes, uint32_t capacity, uint32_t timeout, uint32_t* count) {
  *count = 0; const auto fd = static_cast<Socket*>(handle)->fd;
  const auto deadline = Now() + timeout;
  for (;;) {
    auto size = recv(fd, bytes, capacity, 0);
    if (size >= 0) { *count = uint32_t(size); return 0; }
    if (errno == EINTR) continue;
    if (errno != EAGAIN && errno != EWOULDBLOCK) return 6;
    if (!timeout) return 5;
    const auto result = Wait(fd, POLLIN, deadline);
    if (result) return result;
  }
}
NECKO_API int necko_socket_write_some(void* handle, const uint8_t* bytes, uint32_t size, uint32_t* count) {
  *count = 0;
  ssize_t written;
  do { written = send(static_cast<Socket*>(handle)->fd, bytes, size, 0); } while (written < 0 && errno == EINTR);
  if (written < 0) return errno == EAGAIN || errno == EWOULDBLOCK ? 5 : 6;
  *count = uint32_t(written); return written || !size ? 0 : 6;
}
NECKO_API int necko_socket_write(void* handle, const uint8_t* bytes, uint32_t size, uint32_t timeout) {
  const auto deadline = Now() + timeout;
  while (size) {
    uint32_t written;
    const auto result = necko_socket_write_some(handle, bytes, size, &written);
    if (result == 5) { if (int error = Wait(static_cast<Socket*>(handle)->fd, POLLOUT, deadline)) return error; continue; }
    if (result) return result;
    bytes += written; size -= written;
  }
  return 0;
}
