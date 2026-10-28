#pragma once
#include "domain/web_media/image_data.h"
#include <algorithm>

namespace ruyijs::web_canvas {
inline void DecodedCanvasPixels(const domain::web_media::ImageFrame& image, std::vector<uint8_t>* output) {
  *output = image.pixels;
  for (size_t at = 0; at + 3 < output->size(); at += 4) {
    const unsigned alpha = image.pixels[at + 3];
    for (unsigned channel = 0; channel < 3; ++channel)
      (*output)[at + channel] = alpha ? uint8_t(std::min(255u,
          unsigned(image.pixels[at + 2 - channel]) * 255 / alpha)) : 0;
  }
}
}
