#ifdef __APPLE__
#include "web_geometry/svg_path.h"
#include <CoreGraphics/CoreGraphics.h>
#include <numbers>

namespace ruyijs::web_geometry {
namespace {
void Arc(CGMutablePathRef path, const std::array<float, 7>& v) {
  const auto start = CGPathGetCurrentPoint(path);
  double rx = std::abs(v[0]), ry = std::abs(v[1]);
  if (!rx || !ry) { CGPathAddLineToPoint(path, nullptr, v[5], v[6]); return; }
  if (start.x == v[5] && start.y == v[6]) return;
  const double phi = v[2] * std::numbers::pi / 180, cosine = std::cos(phi), sine = std::sin(phi);
  const double dx = (start.x - v[5]) / 2, dy = (start.y - v[6]) / 2;
  const double x = cosine * dx + sine * dy, y = -sine * dx + cosine * dy;
  const double scale = x*x/(rx*rx) + y*y/(ry*ry);
  if (scale > 1) { rx *= std::sqrt(scale); ry *= std::sqrt(scale); }
  const double denominator = rx*rx*y*y + ry*ry*x*x;
  const double factor = (bool(v[3]) == bool(v[4]) ? -1 : 1) *
      std::sqrt(std::max(0.0, (rx*rx*ry*ry - denominator) / denominator));
  const double cx = factor * rx * y / ry, cy = -factor * ry * x / rx;
  const double ux = (x-cx)/rx, uy = (y-cy)/ry, vx = (-x-cx)/rx, vy = (-y-cy)/ry;
  const double angle = std::atan2(uy, ux);
  double delta = std::atan2(ux*vy-uy*vx, ux*vx+uy*vy);
  if (v[4] && delta < 0) delta += 2 * std::numbers::pi;
  if (!v[4] && delta > 0) delta -= 2 * std::numbers::pi;
  CGAffineTransform transform{rx*cosine, rx*sine, -ry*sine, ry*cosine,
      cosine*cx-sine*cy+(start.x+v[5])/2, sine*cx+cosine*cy+(start.y+v[6])/2};
  CGPathAddArc(path, &transform, 0, 0, 1, angle, angle+delta, delta < 0);
}
}
bool SvgPathBounds(const std::vector<domain::geometry::SvgPathCommand>& commands,
                   float stroke, domain::geometry::SvgBox* out) {
  CGMutablePathRef path = CGPathCreateMutable();
  if (!path) return false;
  for (const auto& command : commands) {
    const auto& v = command.values;
    switch (command.kind) {
      case 'M': CGPathMoveToPoint(path, nullptr, v[0], v[1]); break;
      case 'L': CGPathAddLineToPoint(path, nullptr, v[0], v[1]); break;
      case 'C': CGPathAddCurveToPoint(path, nullptr, v[0], v[1], v[2], v[3], v[4], v[5]); break;
      case 'Q': CGPathAddQuadCurveToPoint(path, nullptr, v[0], v[1], v[2], v[3]); break;
      case 'A': Arc(path, v); break;
      case 'Z': CGPathCloseSubpath(path); break;
      default: CGPathRelease(path); return false;
    }
  }
  CGPathRef outline = stroke > 0 ? CGPathCreateCopyByStrokingPath(path, nullptr, stroke,
      kCGLineCapButt, kCGLineJoinMiter, 4) : CGPathRetain(path);
  CGPathRelease(path);
  if (!outline) return false;
  const CGRect box = CGPathGetPathBoundingBox(outline);
  CGPathRelease(outline);
  *out = CGRectIsNull(box) ? domain::geometry::SvgBox{} : domain::geometry::SvgBox{
      float(box.origin.x), float(box.origin.y), float(box.size.width), float(box.size.height)};
  return true;
}
}
#endif
