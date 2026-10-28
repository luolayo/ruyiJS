#pragma once
#include "core.h"
#include <algorithm>
#include <string>
#include <string_view>

struct Exchange {
  ReadCallback read;
  WriteCallback write;
  void* context;
  std::string method, headers, pending;
  uint64_t remaining = 0, sent = 0, requestLength = 0;
  bool requestChunked = false, requestSized = false, chunked = false, sized = false;
  bool chunkEnd = false, done = false, reusable = false, received = false;
  int failure = 0;
  int Fill();
  int Line(std::string* output);
  int HeaderBlock();
  int Read(uint8_t* bytes, uint32_t size, uint32_t* count);
};
inline std::string Lower(std::string value) {
  for (auto& c : value) if (c >= 'A' && c <= 'Z') c += 'a' - 'A';
  return value;
}
inline std::string Trim(std::string value) {
  auto start = value.find_first_not_of(" \t");
  return start == value.npos ? "" : value.substr(start, value.find_last_not_of(" \t") - start + 1);
}
bool Decimal(const std::string& value, uint64_t* result);
inline bool HeaderToken(const std::string& value) {
  if(value.empty())return false;
  for(unsigned char c:value)if(!((c>='a'&&c<='z')||(c>='A'&&c<='Z')||(c>='0'&&c<='9')||
      std::string_view("!#$%&'*+-.^_`|~").find(c)!=std::string_view::npos))return false;
  return true;
}
