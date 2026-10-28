#ifdef _WIN32
#include "resource_network/necko_helper.h"

namespace ruyijs::resource_network {
bool NeckoPythonPath(std::wstring* python) {
  wchar_t self[MAX_PATH];
  const DWORD length = GetModuleFileNameW(nullptr, self, MAX_PATH);
  if (!length || length >= MAX_PATH) return false;
  python->assign(self, length);
  auto slash = python->find_last_of(L"\\/");
  if (slash == std::wstring::npos || !slash) return false;
  slash = python->find_last_of(L"\\/", slash - 1);
  if (slash == std::wstring::npos) return false;
  *python = python->substr(0, slash) + L"\\vendor\\necko-derived\\python\\python.exe";
  return true;
}
}

#endif
