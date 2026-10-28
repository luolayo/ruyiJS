#include "core.h"
#include <brotli/decode.h>
#include <algorithm>
#include <cstdlib>
#include <new>

namespace {
struct Decoder {
  BrotliDecoderState* state=nullptr;
  size_t limit=0,used=0,peak=0;
  bool refused=false;
};
struct alignas(max_align_t) Block {size_t size;};
void* Allocate(void* context,size_t size) {
  auto& d=*static_cast<Decoder*>(context);
  if(size>d.limit-d.used){d.refused=true;return nullptr;}
  auto* block=static_cast<Block*>(std::malloc(sizeof(Block)+size));
  if(!block)return nullptr;
  block->size=size;d.used+=size;d.peak=std::max(d.peak,d.used);return block+1;
}
void Release(void* context,void* memory) {
  if(!memory)return;auto* block=static_cast<Block*>(memory)-1;
  static_cast<Decoder*>(context)->used-=block->size;std::free(block);
}
}
NECKO_API uint32_t rb_version(){return BrotliDecoderVersion();}
NECKO_API void* rb_create(size_t limit) {
  auto* d=new(std::nothrow) Decoder;if(!d)return nullptr;d->limit=limit;
  d->state=BrotliDecoderCreateInstance(Allocate,Release,d);
  if(!d->state){delete d;return nullptr;}return d;
}
NECKO_API int rb_process(void* handle,const uint8_t* input,size_t* consumed,uint8_t* output,size_t* produced) {
  auto& d=*static_cast<Decoder*>(handle);size_t available=*consumed,capacity=*produced;
  int result=BrotliDecoderDecompressStream(d.state,&available,&input,&capacity,&output,nullptr);
  *consumed-=available;*produced-=capacity;return result;
}
NECKO_API size_t rb_used(void* handle){return static_cast<Decoder*>(handle)->used;}
NECKO_API size_t rb_peak(void* handle){return static_cast<Decoder*>(handle)->peak;}
NECKO_API int rb_refused(void* handle){return static_cast<Decoder*>(handle)->refused;}
NECKO_API int rb_error(void* handle){return BrotliDecoderGetErrorCode(static_cast<Decoder*>(handle)->state);}
NECKO_API size_t rb_close(void* handle) {
  auto* d=static_cast<Decoder*>(handle);BrotliDecoderDestroyInstance(d->state);
  size_t remaining=d->used;delete d;return remaining;
}
