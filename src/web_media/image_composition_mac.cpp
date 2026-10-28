#ifdef __APPLE__
#include "web_media/image_animation.h"
#include <algorithm>
#include <cstring>

namespace ruyijs::web_media {
bool ComposeImageAnimation(const std::string& mime, const ImageAnimation& input, uint32_t width,
                           uint32_t height, domain::web_media::ImageData* output) {
  if (!input.width || !input.height || uint64_t(input.width)*input.height > domain::web_media::kImagePixelLimit) return false;
  std::vector<uint8_t> canvas(size_t(input.width)*input.height*4), previous;
  uint64_t timestamp = 0;
  output->animated = true; output->repetitions = input.repetitions;
  for (const auto& patch : input.patches) {
    domain::web_media::ImageData decoded;
    if (DecodeImageBytes(mime, patch.encoded, 0, 0, true, &decoded) != domain::web_media::ImageDecodeStatus::Ok || decoded.frames.empty()) return false;
    auto& pixels = decoded.frames[0];
    if (pixels.width != patch.width || pixels.height != patch.height ||
        uint64_t(patch.x)+patch.width > input.width || uint64_t(patch.y)+patch.height > input.height) return false;
    if (patch.disposal == 2) previous = canvas;
    for (uint32_t y=0;y<patch.height;++y) for(uint32_t x=0;x<patch.width;++x) {
      const auto* source = &pixels.pixels[(size_t(y)*patch.width+x)*4];
      auto* target = &canvas[(size_t(y+patch.y)*input.width+x+patch.x)*4];
      for (unsigned c=0;c<4;++c) target[c] = patch.over ? uint8_t(std::min(255u,
          unsigned(source[c])+(unsigned(target[c])*(255-source[3])+127)/255)) : source[c];
    }
    domain::web_media::ImageFrame frame;
    frame.width = width && height ? width : input.width;
    frame.height = width && height ? height : input.height;
    if (uint64_t(frame.width)*frame.height > domain::web_media::kImagePixelLimit) return false;
    frame.pixels.resize(size_t(frame.width)*frame.height*4);
    for (uint32_t y=0;y<frame.height;++y) for(uint32_t x=0;x<frame.width;++x) {
      const auto sx=uint64_t(x)*input.width/frame.width, sy=uint64_t(y)*input.height/frame.height;
      std::memcpy(&frame.pixels[(size_t(y)*frame.width+x)*4], &canvas[(sy*input.width+sx)*4],4);
    }
    frame.animated=true; frame.timestamp=timestamp; frame.duration=patch.duration; timestamp+=patch.duration;
    frame.opaque=true;
    for(size_t i=3;i<frame.pixels.size();i+=4) if(frame.pixels[i]!=255) {frame.opaque=false;break;}
    output->frames.push_back(std::move(frame));
    if(patch.disposal==1) for(uint32_t y=0;y<patch.height;++y)
      std::memset(&canvas[(size_t(y+patch.y)*input.width+patch.x)*4],0,size_t(patch.width)*4);
    if(patch.disposal==2) canvas.swap(previous);
  }
  return true;
}
}
#endif
