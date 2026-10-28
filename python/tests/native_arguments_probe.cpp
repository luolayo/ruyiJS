#include "runtime/arguments.h"
#include <iostream>
#include <string>
#include <unistd.h>

int main(int argc, char** argv) {
  ruyijs::Arguments arguments;
  if (!arguments.Prepare(&argc, &argv)) return 1;
  std::cout << getpid() << '\n';
  for (int i = 1; i < argc; ++i) std::cout << argv[i] << '\n';
  if (argc > 2 && std::string(argv[1]) == "--ruyijs-runtime") {
    std::string value;
    if (!ruyijs::ReadUTF8File(argv[2], &value)) return 2;
    std::cout << value << '\n';
  }
  return 0;
}
