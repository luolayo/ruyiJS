// A transport peer, not a JavaScript runtime. Links the production Pipe code.
#include "runtime/pipe.h"
#include <chrono>
#include <iostream>
#include <string>
#include <thread>

using ruyijs::Pipe;
using ruyijs::PipeResult;

static int QueueChecks(const char* path) {
  Pipe pipe;
  if (!pipe.ListenAsync(path) || pipe.Queue("") || pipe.Queue(std::string(Pipe::kMaxFrame + 1, 'x')))
    return 31;
  if (!pipe.Queue(std::string(Pipe::kMaxFrame, 'x')) || pipe.Queue("x") ||
      pipe.queuedBytes() != Pipe::kMaxQueuedBytes) return 32;
  pipe.Close();
  if (pipe.queuedBytes() || pipe.queuedFrames() || !pipe.ListenAsync(path)) return 33;
  for (unsigned index = 0; index < Pipe::kMaxQueuedFrames; ++index)
    if (!pipe.Queue("x")) return 34;
  if (pipe.Queue("overflow") || pipe.queuedFrames() != Pipe::kMaxQueuedFrames) return 35;
  std::string frame;
  bool received = true;
  if (pipe.Flush() != PipeResult::Pending || pipe.Poll(&frame, &received) != PipeResult::Pending ||
      received || pipe.connected()) return 36;
  pipe.Close();
  pipe.Close();
  return 0;
}

static int AsyncEcho(Pipe& pipe) {
  const auto deadline = std::chrono::steady_clock::now() + std::chrono::seconds(10);
  bool finished = false;
  while (std::chrono::steady_clock::now() < deadline) {
    std::string frame;
    bool received = false;
    const auto result = pipe.Poll(&frame, &received);
    if (result == PipeResult::Failed) return 20;
    if (result == PipeResult::Closed) return 0;
    if (received) {
      finished = frame == "quit";
      if (!pipe.Queue(std::move(frame))) return 21;
    }
    const auto flushed = pipe.Flush();
    if (flushed == PipeResult::Failed) return 22;
    if (finished && !pipe.queuedFrames()) return 0;
    std::this_thread::sleep_for(std::chrono::milliseconds(1));
  }
  return 23;
}

int main(int argc, char** argv) {
  if (argc < 3) return 2;
  const std::string mode = argv[1];
  if (mode == "queue") return QueueChecks(argv[2]);
  Pipe pipe;
  if (mode == "collision") {
    // The caller owns an existing path. A failed listener must preserve it.
    return pipe.Listen(argv[2]) ? 40 : 0;
  }
  if (mode == "server" || mode == "async-server" || mode == "disconnect") {
    const bool opened = mode == "async-server" ? pipe.ListenAsync(argv[2]) : pipe.Listen(argv[2]);
    if (!opened) return 3;
    std::cout << "ready" << std::endl;
    if (mode == "async-server") return AsyncEcho(pipe);
    if (!pipe.Accept()) return 4;
    if (mode == "disconnect") {
      std::cout << "accepted" << std::endl;
      return pipe.Write(std::string(Pipe::kMaxFrame, 'x')) ? 41 : 0;
    }
  } else {
    const bool opened = mode == "async-client" ? pipe.ConnectAsync(argv[2]) : pipe.Connect(argv[2]);
    if (!opened) return 5;
    if (mode == "async-client") return AsyncEcho(pipe);
  }
  std::string frame;
  if (mode == "--ruyijs-rpc") {
    // Only exercise Context's startup/close lifecycle. Never claim eval support.
    if (!pipe.Read(&frame) || frame.find("\"close\"") == std::string::npos) return 6;
    return pipe.Write("{\"id\":1,\"ok\":true,\"value\":{\"type\":\"undefined\"}}") ? 0 : 7;
  }
  while (pipe.Read(&frame)) {
    if (!pipe.Write(frame)) return 8;
    if (frame == "quit") return 0;
  }
  return 0;
}
