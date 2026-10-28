#ifndef RUYIJS_NATIVE_CONSTRUCTOR_TRACE_H
#define RUYIJS_NATIVE_CONSTRUCTOR_TRACE_H
#include "js/CallArgs.h"
#if __has_include("vm/StandaloneTrace.h")
#define RUYIJS_HAS_STANDALONE_TRACE 1
#include "vm/StandaloneTrace.h"
#else
#define RUYIJS_HAS_STANDALONE_TRACE 0
#endif

namespace ruyijs {
class NativeConstructorTrace final {
 public:
  NativeConstructorTrace(JSContext* cx, const JS::CallArgs& args);
  ~NativeConstructorTrace();
  NativeConstructorTrace(const NativeConstructorTrace&) = delete;
  NativeConstructorTrace& operator=(const NativeConstructorTrace&) = delete;
  bool Finish(bool ok) { ok_ = ok; return ok; }
 private:
  JSContext* cx_;
  JS::CallArgs args_;
#if RUYIJS_HAS_STANDALONE_TRACE
  js::standalone_trace::CallState state_;
#endif
  bool enabled_ = false;
  bool ok_ = false;
};
}
#endif
