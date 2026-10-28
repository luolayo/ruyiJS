#ifndef _WIN32
#include "resource_network/necko_helper.h"
#include <cerrno>
#include <climits>
#include <csignal>
#include <fcntl.h>
#include <filesystem>
#include <poll.h>
#include <spawn.h>
#include <sstream>
#include <sys/socket.h>
#include <sys/wait.h>
extern char** environ;

namespace ruyijs::resource_network {
uint32_t NeckoRemaining(uint64_t deadline) {
  const auto now = MonotonicMilliseconds();
  return now >= deadline ? 0 : uint32_t(std::min<uint64_t>(deadline - now, INT_MAX));
}
bool NeckoPipe::Open(bool) {
  int descriptors[2];
  if (socketpair(AF_UNIX, SOCK_STREAM, 0, descriptors)) return false;
  parent_.Reset(descriptors[0]); child_.Reset(descriptors[1]);
  const int enabled = 1;
  for (int fd : descriptors) {
    if (fcntl(fd, F_SETFD, FD_CLOEXEC) < 0 ||
        setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &enabled, sizeof(enabled))) return false;
  }
  return fcntl(parent_.Get(), F_SETFL, O_NONBLOCK) == 0;
}
bool NeckoPipe::Transfer(void* data, uint32_t size, bool writing, uint64_t deadline) {
  auto* bytes = static_cast<char*>(data);
  while (size) {
    const auto remaining = NeckoRemaining(deadline);
    if (!remaining) return false;
    pollfd descriptor{parent_.Get(), short(writing ? POLLOUT : POLLIN), 0};
    const auto ready = poll(&descriptor, 1, int(remaining));
    if (ready < 0 && errno == EINTR) continue;
    if (ready <= 0) return false;
    const auto count = writing ? send(parent_.Get(), bytes, size, 0) : recv(parent_.Get(), bytes, size, 0);
    if (count < 0 && (errno == EINTR || errno == EAGAIN)) continue;
    if (count <= 0) return false;
    bytes += count; size -= uint32_t(count);
  }
  return true;
}
bool NeckoPipe::Write(const void* data, uint32_t size, uint64_t deadline) {
  return Transfer(const_cast<void*>(data), size, true, deadline);
}
bool NeckoPipe::Read(void* data, uint32_t size, uint64_t deadline) {
  return Transfer(data, size, false, deadline);
}
NeckoHelper::~NeckoHelper() {
  std::lock_guard<std::mutex> guard(lock_);
  if (pid_ && !reaped_) {
    kill(pid_, SIGKILL);
    int status;
    while (waitpid(pid_, &status, 0) < 0 && errno == EINTR) {}
  }
}
bool NeckoHelper::Start(const std::wstring& executable, NeckoPipe& input, NeckoPipe& output, const wchar_t* mode) {
  std::lock_guard<std::mutex> guard(lock_);
  if (pid_) return false;
  std::vector<std::string> arguments{Utf8Path(executable), "-I", "-B", "-m", "ruyijs_necko.oneshot"};
  std::istringstream options(Utf8Path(mode ? mode : L""));
  for (std::string value; options >> value;) arguments.push_back(value);
  std::vector<char*> argv;
  for (auto& argument : arguments) argv.push_back(argument.data());
  argv.push_back(nullptr);
  std::vector<std::string> environment;
  for (char** item = environ; *item; ++item) {
    if (std::string_view(*item).starts_with("RUYIJS_NECKO_PARENT_PID=")) continue;
    environment.emplace_back(*item);
  }
  environment.push_back("RUYIJS_NECKO_PARENT_PID=" + std::to_string(getpid()));
  std::vector<char*> childEnvironment;
  for (auto& item : environment) childEnvironment.push_back(item.data());
  childEnvironment.push_back(nullptr);
  posix_spawn_file_actions_t actions;
  if (posix_spawn_file_actions_init(&actions)) return false;
  int error = posix_spawn_file_actions_adddup2(&actions, input.Child(), STDIN_FILENO);
  if (!error) error = posix_spawn_file_actions_adddup2(&actions, output.Child(), STDOUT_FILENO);
  if (!error) error = posix_spawn_file_actions_addopen(&actions, STDERR_FILENO, "/dev/null", O_WRONLY, 0);
  if (!error) error = posix_spawn(&pid_, arguments[0].c_str(), &actions, nullptr, argv.data(), childEnvironment.data());
  posix_spawn_file_actions_destroy(&actions);
  return error == 0;
}
void NeckoHelper::Cancel() {
  std::lock_guard<std::mutex> guard(lock_);
  if (pid_ && !reaped_) kill(pid_, SIGKILL);
}
bool NeckoHelper::Finish(uint64_t deadline) {
  while (NeckoRemaining(deadline)) {
    {
      std::lock_guard<std::mutex> guard(lock_);
      if (!pid_ || reaped_) return false;
      int status;
      const auto result = waitpid(pid_, &status, WNOHANG);
      if (result == pid_) { reaped_ = true; return WIFEXITED(status) && WEXITSTATUS(status) == 0; }
      if (result < 0 && errno != EINTR) return false;
    }
    SleepMilliseconds(1);
  }
  return false;
}
bool NeckoPythonPath(std::wstring* output) {
  const char* configured = std::getenv("RUYIJS_NECKO_PYTHON");
  const auto path = configured && *configured ? std::filesystem::path(configured) :
      std::filesystem::path(ExecutablePath()).parent_path().parent_path() / "vendor/necko-derived/bin/python3";
  if (access(path.c_str(), X_OK)) return false;
  *output = WidePath(path.string());
  return true;
}
}
#endif
