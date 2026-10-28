#include "exchange.h"
#include <charconv>
#include <cstdio>
#include <memory>

bool Decimal(const std::string& value, uint64_t* result) {
  auto parsed = std::from_chars(value.data(), value.data() + value.size(), *result);
  return parsed.ec == std::errc{} && parsed.ptr == value.data() + value.size();
}
namespace {
int Write(Exchange& e, const std::string& value) {
  return e.write(e.context, reinterpret_cast<const uint8_t*>(value.data()), uint32_t(value.size()));
}
}
NECKO_API int necko_exchange_open(const char* method, const char* target, const char* headers,
    ReadCallback read, WriteCallback write, void* context, void** output) {
  *output = nullptr;
  auto e = std::make_unique<Exchange>();
  e->read = read; e->write = write; e->context = context; e->method = method;
  if (!HeaderToken(method) || std::string(target).find_first_of("\r\n ") != std::string::npos) return 1;
  std::string fields(headers);
  if (fields.size() > 65536 || std::string(target).size() > 65536) return 1;
  size_t at = 0, count = 0;
  while (at < fields.size()) {
    auto end = fields.find("\r\n", at), colon = fields.find(':', at);
    if (++count > 256 || end == fields.npos || colon >= end) return 1;
    const auto name = fields.substr(at, colon-at), value = Trim(fields.substr(colon+1,end-colon-1));
    if (!HeaderToken(name) || value.find_first_of("\r\n") != value.npos) return 1;
    if (Lower(name) == "content-length") {
      uint64_t length;
      if (!Decimal(value,&length) || (e->requestSized && length != e->requestLength)) return 1;
      e->requestSized=true; e->requestLength=length;
    }
    if (Lower(name) == "transfer-encoding") {
      if (e->requestChunked || Lower(value) != "chunked") return 1;
      e->requestChunked = true;
    }
    at=end+2;
  }
  if (e->requestSized && e->requestChunked) return 1;
  const int error = Write(*e, std::string(method)+" "+target+" HTTP/1.1\r\n"+fields+"\r\n");
  if (error) return error;
  *output=e.release();return 0;
}
NECKO_API int necko_exchange_write(void* handle,const uint8_t* bytes,uint32_t size) {
  auto& e=*static_cast<Exchange*>(handle);
  if (e.received || (e.requestSized && (e.sent > e.requestLength || size > e.requestLength-e.sent)) ||
      (!e.requestSized && !e.requestChunked && size)) return 1;
  if (!size) return 0;
  if (e.requestChunked) {
    char length[32];std::snprintf(length,sizeof(length),"%x\r\n",size);
    if (int error=Write(e,length)) return error;
  }
  if (int error=e.write(e.context,bytes,size)) return error;
  if (e.requestChunked) if (int error=Write(e,"\r\n")) return error;
  e.sent+=size;return 0;
}
NECKO_API int necko_exchange_receive(void* handle) {
  auto& e=*static_cast<Exchange*>(handle);
  if (e.received || (e.requestSized && e.sent!=e.requestLength)) return 1;
  if (e.requestChunked) if (int error=Write(e,"0\r\n\r\n")) return error;
  e.received=true;
  return e.failure=e.HeaderBlock();
}
NECKO_API const char* necko_exchange_headers(void* handle) {return static_cast<Exchange*>(handle)->headers.c_str();}
NECKO_API int necko_exchange_read(void* handle,uint8_t* bytes,uint32_t size,uint32_t* count) {
  auto& e=*static_cast<Exchange*>(handle);
  *count=0;
  if (e.failure) return e.failure;
  if (!e.received) return 1;
  return e.failure=e.Read(bytes,size,count);
}
NECKO_API int necko_exchange_reusable(void* handle) {
  auto& e=*static_cast<Exchange*>(handle);return e.done&&e.reusable&&!e.failure&&e.pending.empty();
}
NECKO_API void necko_exchange_close(void* handle) {delete static_cast<Exchange*>(handle);}
