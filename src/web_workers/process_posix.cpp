#ifndef _WIN32
#include "web_workers/process.h"
#include "runtime/platform_process.h"
#include <cerrno>
#include <csignal>
#include <spawn.h>
#include <sys/wait.h>
extern char** environ;

namespace ruyijs::web_workers {
Process::~Process() { Stop(); }
bool Process::Running() const {
  if (!pid_ || reaped_) return false;
  int status = 0;
  const auto result = waitpid(pid_, &status, WNOHANG);
  if (result == pid_ || (result < 0 && errno == ECHILD)) reaped_ = true;
  return !reaped_;
}
unsigned Process::id() const { return unsigned(pid_); }
bool Process::Queue(std::string frame) { return Running() && pipe_.Queue(std::move(frame)); }
PipeResult Process::Poll(std::string* frame, bool* received) {
  const auto result = pipe_.Poll(frame, received);
  if (!*received && result == PipeResult::Pending && !pipe_.connected() && !Running())
    return PipeResult::Closed;
  return result;
}
bool Process::Stop() {
  if (Running()) {
    kill(-pid_, SIGKILL);
    int status;
    while (waitpid(pid_, &status, 0) < 0 && errno == EINTR) {}
  }
  pid_ = 0; reaped_ = false;
  pipe_.Close();
  if (!socketDirectory_.empty()) { rmdir(socketDirectory_.c_str()); socketDirectory_.clear(); }
  return true;
}
StartResult Process::Start(std::wstring_view executable, std::string initial, WorkerKind kind) noexcept {
  if (pid_) return {StartError::Active};
  if (executable.empty() || executable.find(L'\0') != executable.npos ||
      !Pipe::ValidFrameSize(initial.size())) return {StartError::InvalidInput};
  auto fail = [this](StartError error, int code) { Stop(); return StartResult{error, unsigned(code)}; };
  char directory[] = "/tmp/ruyijs-worker-XXXXXX";
  if (!mkdtemp(directory)) return {StartError::Pipe, unsigned(errno)};
  socketDirectory_ = directory;
  std::string name = socketDirectory_ + "/rpc.sock";
  if (!pipe_.ListenAsync(name.c_str()) || !pipe_.Queue(std::move(initial)))
    return fail(StartError::Pipe, errno);
  std::string path = Utf8Path(executable);
  const char* workerKind = kind == WorkerKind::Service ? "service" : kind == WorkerKind::Shared ? "shared" : "dedicated";
  char* argv[] = {path.data(), const_cast<char*>("--ruyijs-worker"), name.data(),
                 const_cast<char*>("--ruyijs-worker-kind"), const_cast<char*>(workerKind), nullptr};
  posix_spawnattr_t attributes;
  int error = posix_spawnattr_init(&attributes);
  if (error) return fail(StartError::Create, error);
  error = posix_spawnattr_setflags(&attributes, POSIX_SPAWN_SETPGROUP);
  if (!error) error = posix_spawnattr_setpgroup(&attributes, 0);
  if (!error) error = posix_spawn(&pid_, path.c_str(), nullptr, &attributes, argv, environ);
  posix_spawnattr_destroy(&attributes);
  if (error) return fail(StartError::Create, error);
  return {};
}
}
#endif
