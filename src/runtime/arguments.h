#ifndef RUYIJS_ARGUMENTS_H
#define RUYIJS_ARGUMENTS_H
#include <string>
#include <vector>

namespace ruyijs {
// Product mode owns UTF-8 argv and expands per-process trace paths.
// This object outlives OptionParser and every borrowed option value.
class Arguments final {
 public:
  bool Prepare(int* count, char*** values);
 private:
  std::vector<std::string> strings_;
  std::vector<char*> pointers_;
};
bool ReadUTF8File(const char* path, std::string* output);
}
#endif
