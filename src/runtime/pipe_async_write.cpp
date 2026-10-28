#include "runtime/pipe_async.h"

namespace ruyijs {
PipeResult PipeWrite(PipeHandle pipe, PipeAsync& state) {
  for (unsigned operation = 0; operation < 8 && !state.outgoing.empty(); ++operation) {
    auto& frame = state.outgoing.front();
    if (!state.writeOffset) state.writeLength = uint32_t(frame.size());
    const bool header = state.writeOffset < sizeof(uint32_t);
    const size_t offset = header ? state.writeOffset : state.writeOffset - sizeof(uint32_t);
    char* bytes = header ? reinterpret_cast<char*>(&state.writeLength) : frame.data();
    const size_t total = header ? sizeof(uint32_t) : frame.size();
    PipeCount count = 0;
    const auto result = PipeIo(pipe, state.write, true, bytes + offset, PipeCount(total - offset), &count);
    if (result != PipeResult::Ready) return result;
    state.writeOffset += count;
    if (state.writeOffset == frame.size() + sizeof(uint32_t)) {
      state.queuedBytes -= frame.size() + sizeof(uint32_t);
      state.outgoing.pop_front(); state.writeOffset = 0;
    }
  }
  return PipeResult::Ready;
}
}
