#include "runtime/pipe_async.h"
#include <new>

namespace ruyijs {
PipeAsync::PipeAsync() {
#ifdef _WIN32
  accept.value.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  read.value.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
  write.value.hEvent = CreateEventW(nullptr, TRUE, FALSE, nullptr);
#endif
}
PipeAsync::~PipeAsync() {
#ifdef _WIN32
  if (accept.value.hEvent) CloseHandle(accept.value.hEvent);
  if (read.value.hEvent) CloseHandle(read.value.hEvent);
  if (write.value.hEvent) CloseHandle(write.value.hEvent);
#endif
}
bool PipeAsync::Valid() const {
#ifdef _WIN32
  return accept.value.hEvent && read.value.hEvent && write.value.hEvent;
#else
  return true;
#endif
}
PipeAsync* NewPipeAsync() {
  try {
    auto* state = new PipeAsync;
    if (state->Valid()) return state;
    delete state;
  } catch (...) {}
  return nullptr;
}
#ifdef _WIN32
void Pipe::Close() {
  if (async_) {
    if (handle_) {
      CancelIoEx(handle_, nullptr);
      CancelPipeOperation(handle_, async_->accept);
      CancelPipeOperation(handle_, async_->read);
      CancelPipeOperation(handle_, async_->write);
    }
    delete async_;
    async_ = nullptr;
  }
  if (handle_) { CloseHandle(handle_); handle_ = nullptr; }
}
#endif
bool Pipe::Queue(std::string frame) {
  if (!async_ || !ValidFrameSize(frame.size()) ||
      async_->terminal == PipeResult::Closed || async_->terminal == PipeResult::Failed)
    return false;
  auto& state = *async_;
  const size_t bytes = sizeof(uint32_t) + frame.size();
  if (state.outgoing.size() >= kMaxQueuedFrames || bytes > kMaxQueuedBytes - state.queuedBytes)
    return false;
  try { state.outgoing.push_back(std::move(frame)); }
  catch (...) { return false; }
  state.queuedBytes += bytes;
  return true;
}
size_t Pipe::queuedBytes() const { return async_ ? async_->queuedBytes : 0; }
size_t Pipe::queuedFrames() const { return async_ ? async_->outgoing.size() : 0; }
bool Pipe::connected() const { return async_ && async_->connected; }
PipeResult Pipe::Flush() {
  if (!async_ || !IsOpen()) return PipeResult::Failed;
  auto& state = *async_;
  if (state.terminal == PipeResult::Closed || state.terminal == PipeResult::Failed) return state.terminal;
  const auto connected = PipeAccept(handle_, state);
  if (connected != PipeResult::Ready) return connected;
  const auto status = PipeWrite(handle_, state);
  if (status == PipeResult::Closed || status == PipeResult::Failed) state.terminal = status;
  return status;
}
PipeResult Pipe::Poll(std::string* frame, bool* received) {
  *received = false;
  if (!async_ || !IsOpen()) return PipeResult::Failed;
  auto& state = *async_;
  if (state.terminal == PipeResult::Closed || state.terminal == PipeResult::Failed)
    return state.terminal;
  const auto connected = PipeAccept(handle_, state);
  if (connected != PipeResult::Ready) {
    state.terminal = connected;
    return connected;
  }
  const auto read = PipeRead(handle_, state);
  const auto write = PipeWrite(handle_, state);
  if (read == PipeResult::Closed || read == PipeResult::Failed) state.terminal = read;
  else if (write == PipeResult::Closed || write == PipeResult::Failed) state.terminal = write;
  if (state.received) {
    *frame = std::move(state.incoming);
    state.received = false; state.readingBody = false; state.readOffset = 0;
    *received = true;
    return PipeResult::Ready;
  }
  return state.terminal;
}
}
