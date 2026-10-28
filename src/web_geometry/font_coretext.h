#pragma once
#ifdef __APPLE__
#include "web_geometry/system_font.h"
#include <CoreText/CoreText.h>
namespace ruyijs::web_geometry {
CTFontRef CoreTextFont(const FontInput& input);
CTLineRef CoreTextLine(const std::u16string& text, CTFontRef font);
}
#endif
