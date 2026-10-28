#include "runtime/page_helpers.h"
#include "jsapi.h"
#include "js/CallAndConstruct.h"
#include "js/PropertyAndElement.h"
#include "js/Realm.h"
#include "runtime/native_constructor_trace.h"
#include "jsfriendapi.h"
#include "js/Conversions.h"
#include "js/CharacterEncoding.h"

namespace ruyijs {
#if !RUYIJS_HAS_STANDALONE_TRACE
namespace {
bool HostCall(JSContext* cx, unsigned argc, JS::Value* vp) {
  auto args = JS::CallArgsFromVp(argc, vp);
  JS::RootedValue delegate(cx, js::GetFunctionNativeReserved(&args.callee(), 0));
  if (!args.isConstructing()) return JS::Call(cx, args.thisv(), delegate, JS::HandleValueArray(args), args.rval());
  JS::RootedObject target(cx, &args.newTarget().toObject()), instance(cx);
  if (!JS::Construct(cx, delegate, target, JS::HandleValueArray(args), &instance)) return false;
  args.rval().setObject(*instance);
  return true;
}
bool CreateHostFunction(JSContext* cx, unsigned argc, JS::Value* vp) {
  auto args = JS::CallArgsFromVp(argc, vp);
  if (argc < 4 || !args[0].isObject() || !JS::IsCallable(&args[0].toObject()) || !args[1].isString()) {
    JS_ReportErrorASCII(cx, "Invalid host function definition");
    return false;
  }
  JS::RootedString name(cx, args[1].toString());
  JS::UniqueChars text = JS_EncodeStringToUTF8(cx, name);
  uint32_t length;
  if (!text || !JS::ToUint32(cx, args[2], &length) || length > 65535) return false;
  JS::RootedFunction fn(cx, js::NewFunctionWithReserved(cx, HostCall, length,
      JS::ToBoolean(args[3]) ? JSFUN_CONSTRUCTOR : 0, text.get()));
  if (!fn) return false;
  JS::RootedObject object(cx, JS_GetFunctionObject(fn));
  js::SetFunctionNativeReserved(object, 0, args[0]);
  args.rval().setObject(*object);
  return true;
}
}
#endif
PageHelpers::PageHelpers(JSContext* cx, JS::HandleObject page)
    : cx_(cx), page_(cx, page), helpers_(cx) {}
bool PageHelpers::Ensure() {
  if (helpers_) return true;
#if RUYIJS_HAS_STANDALONE_TRACE
  JS::RootedObject holder(cx_, JS_NewPlainObject(cx_));
  JS::RootedValue helpers(cx_);
  if (!holder || !js::standalone_trace::DefineRuyijsObject(cx_, holder) ||
      !JS_GetProperty(cx_, holder, "ruyijs", &helpers)) return false;
  helpers_ = &helpers.toObject();
#else
  JS::RootedObject holder(cx_, JS_NewPlainObject(cx_));
  if (!holder || !JS_DefineFunction(cx_, holder, "createHostFunction", CreateHostFunction, 4, 0)) return false;
  helpers_ = holder;
#endif
  return true;
}
bool PageHelpers::Call(const char* method, const JS::HandleValueArray& args,
                         JS::MutableHandleValue result) {
  JSAutoRealm realm(cx_, page_);
  return Ensure() && JS_CallFunctionName(cx_, helpers_, method, args, result);
}
bool PageHelpers::Enabled() const {
#if RUYIJS_HAS_STANDALONE_TRACE
  return js::standalone_trace::IsEnabled(js::standalone_trace::Category::Ruyijs);
#else
  return false;
#endif
}
}
