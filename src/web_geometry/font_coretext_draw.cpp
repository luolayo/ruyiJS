#ifdef __APPLE__
#include "web_geometry/font_coretext.h"
#include <cmath>

namespace ruyijs::web_geometry {
namespace {
void AppendPath(void* context, const CGPathElement* element) {
  auto& path = *static_cast<CanvasTextPath*>(context);
  const auto* p = element->points;
  switch (element->type) {
    case kCGPathElementMoveToPoint: path.Move(p[0].x, p[0].y); break;
    case kCGPathElementAddLineToPoint: path.Line(p[0].x, p[0].y); break;
    case kCGPathElementAddQuadCurveToPoint: path.Quad(p[0].x, p[0].y, p[1].x, p[1].y); break;
    case kCGPathElementAddCurveToPoint: path.Cubic(p[0].x, p[0].y, p[1].x, p[1].y, p[2].x, p[2].y); break;
    case kCGPathElementCloseSubpath: path.Close(); break;
  }
}
}
bool SystemFonts::BuildCanvasTextPath(const std::u16string& text, const FontInput& input, CanvasTextPath* output) {
  if (text.size() > 65536) return false;
  CTFontRef primary = CoreTextFont(input);
  CTLineRef line = primary ? CoreTextLine(text, primary) : nullptr;
  if (!line) { if (primary) CFRelease(primary); return false; }
  CFArrayRef runs = CTLineGetGlyphRuns(line);
  for (CFIndex r = 0; r < CFArrayGetCount(runs); ++r) {
    auto run = static_cast<CTRunRef>(CFArrayGetValueAtIndex(runs, r));
    auto font = static_cast<CTFontRef>(CFDictionaryGetValue(CTRunGetAttributes(run), kCTFontAttributeName));
    const auto count = CTRunGetGlyphCount(run);
    std::vector<CGGlyph> glyphs(count); std::vector<CGPoint> positions(count);
    CTRunGetGlyphs(run, CFRangeMake(0, 0), glyphs.data());
    CTRunGetPositions(run, CFRangeMake(0, 0), positions.data());
    for (CFIndex i = 0; i < count; ++i) {
      const CGAffineTransform transform{1, 0, 0, -1, input.x + positions[i].x, input.y - positions[i].y};
      CGPathRef path = CTFontCreatePathForGlyph(font, glyphs[i], &transform);
      if (path) { CGPathApply(path, output, AppendPath); CGPathRelease(path); }
    }
  }
  CFRelease(line); CFRelease(primary); return true;
}
bool SystemFonts::BuildCanvasGlyphMasks(const std::u16string& text, const FontInput& input,
                                       const float matrix[6], const uint8_t[3], std::vector<CanvasGlyphMask>* output) {
  CanvasTextMetrics metrics;
  if (!MeasureCanvas(text, input, &metrics)) return false;
  if (!metrics.ink) return true;
  CGAffineTransform transform{matrix[0], matrix[1], matrix[2], matrix[3], matrix[4], matrix[5]};
  CGRect box = CGRectApplyAffineTransform(CGRectMake(input.x + metrics.ink_left, input.y + metrics.ink_top,
      metrics.ink_right - metrics.ink_left, metrics.ink_bottom - metrics.ink_top), transform);
  const double left = std::floor(CGRectGetMinX(box)) - 1, top = std::floor(CGRectGetMinY(box)) - 1;
  const double width = std::ceil(CGRectGetMaxX(box)) + 1 - left, height = std::ceil(CGRectGetMaxY(box)) + 1 - top;
  if (!std::isfinite(width) || !std::isfinite(height) || width <= 0 || height <= 0 ||
      width > 65536 || height > 65536 || width * height > 64 * 1024 * 1024 ||
      std::abs(left) > INT_MAX || std::abs(top) > INT_MAX) return false;
  CanvasGlyphMask mask;
  mask.left = int(left); mask.top = int(top); mask.width = int(width); mask.height = int(height);
  mask.coverage.resize(size_t(mask.width) * mask.height);
  CGColorSpaceRef space = CGColorSpaceCreateDeviceGray();
  CGContextRef context = CGBitmapContextCreate(mask.coverage.data(), mask.width, mask.height, 8, mask.width, space, kCGImageAlphaNone);
  CGColorSpaceRelease(space);
  CTFontRef font = CoreTextFont(input);
  CTLineRef line = font ? CoreTextLine(text, font) : nullptr;
  if (!context || !line) {
    if (context) CGContextRelease(context);
    if (line) CFRelease(line);
    if (font) CFRelease(font);
    return false;
  }
  CGContextTranslateCTM(context, -left, -top);
  CGContextConcatCTM(context, transform);
  CGContextTranslateCTM(context, input.x, input.y);
  CGContextScaleCTM(context, 1, -1);
  CGContextSetGrayFillColor(context, 1, 1);
  CGContextSetTextPosition(context, 0, 0);
  CTLineDraw(line, context);
  CFRelease(line); CFRelease(font); CGContextRelease(context);
  output->push_back(std::move(mask));
  return true;
}
}
#endif
