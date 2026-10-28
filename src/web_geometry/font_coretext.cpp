#ifdef __APPLE__
#include "web_geometry/font_coretext.h"
#include "web_geometry/font_config.h"
#include "runtime/platform_process.h"
#include "firefox_font_prefs.h"
#include <cmath>
#include <mutex>

namespace ruyijs::web_geometry {
struct FontCollection {};
SystemFonts::SystemFonts() = default;
SystemFonts::~SystemFonts() = default;
namespace {
std::mutex languageLock;
std::string browserLanguage;
std::string LanguageGroup(std::string language) {
  if (language.empty()) { std::lock_guard<std::mutex> guard(languageLock); language = browserLanguage; }
  if (language.starts_with("zh")) return language.find("TW") != language.npos ? "zh-TW" : "zh-CN";
  for (const char* name : {"ja", "ko", "ar", "he", "th", "el"}) if (language.starts_with(name)) return name;
  if (language.starts_with("ru") || language.starts_with("uk")) return "x-cyrillic";
  return "x-western";
}
std::string Preference(const std::string& key) {
  for (const auto& entry : kFontPreferences) if (key == entry.key) return entry.value;
  return {};
}
}
void SetBrowserLanguage(const std::string& language) {
  std::lock_guard<std::mutex> guard(languageLock); browserLanguage = language;
}
std::string DefaultGenericFamily() {
  const auto value = Preference("font.default." + LanguageGroup({}));
  return value.empty() ? "serif" : value;
}
CTFontRef CoreTextFont(const FontInput& input) {
  if (!std::isfinite(input.size) || input.size <= 0 || !std::isfinite(input.scale) || input.scale <= 0) return nullptr;
  std::string family = input.family.substr(0, input.family.find(','));
  auto begin = family.find_first_not_of(" \t\"'");
  auto end = family.find_last_not_of(" \t\"'");
  family = begin == family.npos ? DefaultGenericFamily() : family.substr(begin, end - begin + 1);
  if (family == "-moz-default") family = DefaultGenericFamily();
  if (family == "system-ui") return CTFontCreateUIFontForLanguage(kCTFontUIFontSystem, input.size, nullptr);
  for (const char* generic : {"serif", "sans-serif", "monospace", "cursive", "fantasy"}) {
    if (family != generic) continue;
    const auto override = GenericFamilyOverride(generic);
    family = override.empty() ? Preference("font.name." + std::string(generic) + "." + LanguageGroup(input.language)) : override;
    break;
  }
  if (family.empty() || !FontFamilyVisible(WidePath(family))) family = "Times";
  CFStringRef name = CFStringCreateWithBytes(nullptr, reinterpret_cast<const UInt8*>(family.data()), family.size(), kCFStringEncodingUTF8, false);
  if (!name) return nullptr;
  CTFontRef font = CTFontCreateWithName(name, input.size, nullptr);
  CFRelease(name);
  CTFontSymbolicTraits traits = (input.italic ? kCTFontItalicTrait : 0) | (input.weight >= 600 ? kCTFontBoldTrait : 0);
  if (font && traits) {
    CTFontRef styled = CTFontCreateCopyWithSymbolicTraits(font, input.size, nullptr, traits, traits);
    if (styled) { CFRelease(font); font = styled; }
  }
  return font;
}
CTLineRef CoreTextLine(const std::u16string& text, CTFontRef font) {
  CFStringRef value = CFStringCreateWithCharacters(nullptr, reinterpret_cast<const UniChar*>(text.data()), text.size());
  if (!value) return nullptr;
  const void* keys[] = {kCTFontAttributeName, kCTForegroundColorFromContextAttributeName};
  const void* values[] = {font, kCFBooleanTrue};
  CFDictionaryRef attributes = CFDictionaryCreate(nullptr, keys, values, 2, &kCFTypeDictionaryKeyCallBacks, &kCFTypeDictionaryValueCallBacks);
  CFAttributedStringRef styled = attributes ? CFAttributedStringCreate(nullptr, value, attributes) : nullptr;
  CTLineRef line = styled ? CTLineCreateWithAttributedString(styled) : nullptr;
  if (styled) CFRelease(styled);
  if (attributes) CFRelease(attributes);
  CFRelease(value);
  return line;
}
bool SystemFonts::MeasureCanvas(const std::u16string& text, const FontInput& input, CanvasTextMetrics* out) {
  *out = {};
  if (text.size() > 65536) return false;
  CTFontRef font = CoreTextFont(input);
  if (!font) return false;
  CTLineRef line = CoreTextLine(text, font);
  if (!line) { CFRelease(font); return false; }
  out->width = float(CTLineGetTypographicBounds(line, nullptr, nullptr, nullptr));
  const auto bounds = CTLineGetBoundsWithOptions(line, kCTLineBoundsUseGlyphPathBounds);
  out->ink = !CGRectIsEmpty(bounds);
  out->ink_left = CGRectGetMinX(bounds); out->ink_right = CGRectGetMaxX(bounds);
  out->ink_top = -CGRectGetMaxY(bounds); out->ink_bottom = -CGRectGetMinY(bounds);
  out->font_ascent = CTFontGetAscent(font); out->font_descent = CTFontGetDescent(font);
  const auto height = out->font_ascent + out->font_descent;
  out->em_ascent = height ? input.size * out->font_ascent / height : 0;
  out->em_descent = input.size - out->em_ascent;
  out->ideographic_baseline = -out->font_descent;
  CFRelease(line); CFRelease(font);
  return true;
}
bool SystemFonts::LineMetrics(const FontInput& input, double* content, double* normal) {
  CTFontRef font = CoreTextFont(input);
  if (!font) return false;
  *content = CTFontGetAscent(font) + CTFontGetDescent(font);
  *normal = *content + CTFontGetLeading(font);
  CFRelease(font); return true;
}
bool SystemFonts::SvgLengthMetrics(const FontInput& input, float* ex, float* ch, float* ic, float* cap) {
  CTFontRef font = CoreTextFont(input);
  if (!font) return false;
  *ex = float(CTFontGetXHeight(font)); *cap = float(CTFontGetCapHeight(font));
  CTLineRef zero = CoreTextLine(u"0", font), ideograph = CoreTextLine(u"水", font);
  *ch = zero ? float(CTLineGetTypographicBounds(zero, nullptr, nullptr, nullptr)) : 0;
  *ic = ideograph ? float(CTLineGetTypographicBounds(ideograph, nullptr, nullptr, nullptr)) : 0;
  if (zero) CFRelease(zero);
  if (ideograph) CFRelease(ideograph);
  CFRelease(font); return zero && ideograph;
}
bool SystemFonts::Measure(const std::u16string& source, const FontInput& input, domain::geometry::SvgTextMeasurement* out) {
  *out = {};
  std::u16string text;
  bool space = true;
  for (auto c : source) {
    const bool current = c == u' ' || c == u'\t' || c == u'\r' || c == u'\n';
    if (!current || !space) text += current ? u' ' : c;
    space = current;
  }
  if (!text.empty() && text.back() == u' ') text.pop_back();
  if (text.empty() || input.size == 0) return true;
  CanvasTextMetrics metrics;
  if (!MeasureCanvas(text, input, &metrics)) return false;
  out->length = metrics.width;
  out->box = {float(input.x + metrics.ink_left), float(input.y + metrics.ink_top),
              float(metrics.ink_right - metrics.ink_left), float(metrics.ink_bottom - metrics.ink_top)};
  out->transformed = input.transform.Apply(out->box);
  CTFontRef font = CoreTextFont(input);
  CTLineRef line = font ? CoreTextLine(text, font) : nullptr;
  if (!line) { if (font) CFRelease(font); return false; }
  for (size_t i = 0; i < text.size(); ++i) {
    const auto left = CTLineGetOffsetForStringIndex(line, i, nullptr);
    const auto right = CTLineGetOffsetForStringIndex(line, i + 1, nullptr);
    out->characters.push_back({float(input.x + std::min(left, right)), float(input.y - metrics.font_ascent),
                              float(std::abs(right - left)), float(metrics.font_ascent + metrics.font_descent)});
  }
  CFRelease(line); CFRelease(font); return true;
}
}
#endif
