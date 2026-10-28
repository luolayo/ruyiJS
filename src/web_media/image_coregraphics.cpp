#ifdef __APPLE__
#include "web_media/image_codec.h"
#include <CoreGraphics/CoreGraphics.h>
#include <ImageIO/ImageIO.h>
#include <limits>

namespace ruyijs::web_media {
namespace {
CFStringRef Type(const std::string& mime) {
  if (mime == "image/png" || mime == "image/x-png") return CFSTR("public.png");
  if (mime == "image/jpeg" || mime == "image/jpg" || mime == "image/pjpeg") return CFSTR("public.jpeg");
  if (mime == "image/gif") return CFSTR("com.compuserve.gif");
  if (mime == "image/bmp" || mime == "image/x-ms-bmp") return CFSTR("com.microsoft.bmp");
  if (mime == "image/x-icon" || mime == "image/vnd.microsoft.icon") return CFSTR("com.microsoft.ico");
  if (mime == "image/webp") return CFSTR("org.webmproject.webp");
  if (mime == "image/avif") return CFSTR("public.avif");
  return nullptr;
}
double Number(CFDictionaryRef properties, CFStringRef group, CFStringRef key, double fallback) {
  auto dictionary = static_cast<CFDictionaryRef>(CFDictionaryGetValue(properties, group));
  if (!dictionary || CFGetTypeID(dictionary) != CFDictionaryGetTypeID()) return fallback;
  auto value = static_cast<CFNumberRef>(CFDictionaryGetValue(dictionary, key));
  double result;
  return value && CFGetTypeID(value) == CFNumberGetTypeID() &&
      CFNumberGetValue(value, kCFNumberDoubleType, &result) ? result : fallback;
}
}
bool ImageCodecSupports(const std::string& mime) {
  const auto type = Type(mime);
  if (!type) return false;
  CFArrayRef types = CGImageSourceCopyTypeIdentifiers();
  const bool supported = types && CFArrayContainsValue(types, CFRangeMake(0, CFArrayGetCount(types)), type);
  if (types) CFRelease(types);
  return supported;
}
domain::web_media::ImageDecodeStatus DecodeImageBytes(const std::string& mime, const std::vector<uint8_t>& bytes,
    uint32_t width, uint32_t height, bool noColor, domain::web_media::ImageData* output) {
  using Status = domain::web_media::ImageDecodeStatus;
  if (!ImageCodecSupports(mime)) return Status::Unsupported;
  if (bytes.empty() || bytes.size() > domain::web_media::kEncodedImageLimit) return Status::InvalidData;
  CFDataRef data = CFDataCreate(nullptr, bytes.data(), bytes.size());
  CGImageSourceRef source = data ? CGImageSourceCreateWithData(data, nullptr) : nullptr;
  if (data) CFRelease(data);
  if (!source) return Status::InvalidData;
  struct SourceOwner { CGImageSourceRef value; ~SourceOwner() { CFRelease(value); } } owner{source};
  const auto type = CGImageSourceGetType(source);
  if (!type || !CFEqual(type, Type(mime))) return Status::InvalidData;
  const auto count = CGImageSourceGetCount(source);
  if (!count || count > 10000) return Status::InvalidData;
  output->frames.clear(); output->animated = count > 1; output->repetitions = 0;
  uint64_t timestamp = 0, pixels = 0;
  for (size_t index = 0; index < count; ++index) {
    CGImageRef image = CGImageSourceCreateImageAtIndex(source, index, nullptr);
    if (!image) return Status::InvalidData;
    domain::web_media::ImageFrame frame;
    frame.width = width && height ? width : uint32_t(CGImageGetWidth(image));
    frame.height = width && height ? height : uint32_t(CGImageGetHeight(image));
    pixels += uint64_t(frame.width) * frame.height;
    if (!frame.width || !frame.height || pixels > domain::web_media::kImagePixelLimit) { CGImageRelease(image); return Status::InvalidData; }
    frame.pixels.resize(size_t(frame.width) * frame.height * 4);
    CGColorSpaceRef space = noColor ? CGColorSpaceCreateDeviceRGB() : CGColorSpaceCreateWithName(kCGColorSpaceSRGB);
    CGContextRef context = CGBitmapContextCreate(frame.pixels.data(), frame.width, frame.height, 8,
        size_t(frame.width) * 4, space, kCGBitmapByteOrder32Little | kCGImageAlphaPremultipliedFirst);
    CGColorSpaceRelease(space);
    if (!context) { CGImageRelease(image); return Status::OutOfMemory; }
    CGContextDrawImage(context, CGRectMake(0, 0, frame.width, frame.height), image);
    CGContextRelease(context); CGImageRelease(image);
    frame.opaque = true;
    for (size_t at = 3; at < frame.pixels.size(); at += 4) if (frame.pixels[at] != 255) { frame.opaque = false; break; }
    frame.animated = output->animated;
    CFDictionaryRef properties = CGImageSourceCopyPropertiesAtIndex(source, index, nullptr);
    if (properties && count > 1) {
      double delay = Number(properties, kCGImagePropertyGIFDictionary, kCGImagePropertyGIFUnclampedDelayTime,
          Number(properties, kCGImagePropertyGIFDictionary, kCGImagePropertyGIFDelayTime, 0.1));
      if (mime == "image/png") delay = Number(properties, kCGImagePropertyPNGDictionary, kCGImagePropertyAPNGUnclampedDelayTime, 0.1);
      if (mime == "image/webp") delay = Number(properties, kCGImagePropertyWebPDictionary, kCGImagePropertyWebPUnclampedDelayTime, 0.1);
      frame.duration = uint64_t(std::max(0.0, delay) * 1000000);
    }
    if (properties) CFRelease(properties);
    frame.timestamp = timestamp; timestamp += frame.duration;
    output->frames.push_back(std::move(frame));
  }
  CFDictionaryRef properties = CGImageSourceCopyProperties(source, nullptr);
  if (properties && count > 1) {
    double loops = Number(properties, kCGImagePropertyGIFDictionary, kCGImagePropertyGIFLoopCount, 1);
    if (mime == "image/png") loops = Number(properties, kCGImagePropertyPNGDictionary, kCGImagePropertyAPNGLoopCount, 1);
    if (mime == "image/webp") loops = Number(properties, kCGImagePropertyWebPDictionary, kCGImagePropertyWebPLoopCount, 1);
    output->repetitions = loops == 0 ? std::numeric_limits<double>::infinity() : std::max(0.0, loops - 1);
  }
  if (properties) CFRelease(properties);
  return Status::Ok;
}
domain::web_media::ImageDecodeStatus DecodeAvifBytes(const std::vector<uint8_t>& bytes,
    uint32_t width, uint32_t height, domain::web_media::ImageData* output) {
  return DecodeImageBytes("image/avif", bytes, width, height, false, output);
}
}
#endif
