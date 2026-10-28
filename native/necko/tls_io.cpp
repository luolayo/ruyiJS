#include "tls.h"
#include <cstring>
#include <mutex>

namespace {
Tls& Owner(PRFileDesc* fd) { return *reinterpret_cast<Tls*>(fd->secret); }
PRStatus Close(PRFileDesc* fd) { fd->secret=nullptr;fd->dtor(fd);return PR_SUCCESS; }
PRInt32 Read(PRFileDesc* fd, void* bytes, PRInt32 size) {
  auto& tls=Owner(fd);uint32_t count=0;
  int result=tls.read(tls.context,static_cast<uint8_t*>(bytes),uint32_t(size),&count);
  if(result){PR_SetError(result==-2?PR_WOULD_BLOCK_ERROR:PR_IO_ERROR,0);return -1;}
  if(count>uint32_t(size)){PR_SetError(PR_IO_ERROR,0);return -1;}
  return PRInt32(count);
}
PRInt32 Write(PRFileDesc* fd,const void* bytes,PRInt32 size) {
  auto& tls=Owner(fd);uint32_t count=uint32_t(size);
  int result=tls.nonblocking&&tls.writeSome?tls.writeSome(tls.context,static_cast<const uint8_t*>(bytes),size,&count):
      tls.write(tls.context,static_cast<const uint8_t*>(bytes),size);
  if(result){PR_SetError(result==-2?PR_WOULD_BLOCK_ERROR:PR_IO_ERROR,0);return -1;}
  return PRInt32(count);
}
PRInt32 Recv(PRFileDesc* fd,void* bytes,PRInt32 size,PRIntn flags,PRIntervalTime) {
  if(flags){PR_SetError(PR_INVALID_ARGUMENT_ERROR,0);return -1;}return Read(fd,bytes,size);
}
PRInt32 Send(PRFileDesc* fd,const void* bytes,PRInt32 size,PRIntn flags,PRIntervalTime) {
  if(flags){PR_SetError(PR_INVALID_ARGUMENT_ERROR,0);return -1;}return Write(fd,bytes,size);
}
PRStatus Address(PRFileDesc*,PRNetAddr* address) {
  std::memset(address,0,sizeof(*address));address->inet.family=PR_AF_INET;
  address->inet.port=PR_htons(443);address->inet.ip=PR_htonl(PR_INADDR_LOOPBACK);return PR_SUCCESS;
}
PRStatus GetOption(PRFileDesc* fd,PRSocketOptionData* option) {
  if(option->option==PR_SockOpt_Nonblocking){option->value.non_blocking=Owner(fd).nonblocking;return PR_SUCCESS;}
  PR_SetError(PR_INVALID_ARGUMENT_ERROR,0);return PR_FAILURE;
}
PRStatus SetOption(PRFileDesc*,const PRSocketOptionData*) {return PR_SUCCESS;}
PRInt32 Available(PRFileDesc* fd){return Owner(fd).idle(Owner(fd).context)?0:1;}
PRInt64 Available64(PRFileDesc* fd){return Available(fd);}
PRInt16 Poll(PRFileDesc* fd,PRInt16 flags,PRInt16* output){
  *output=flags&PR_POLL_WRITE;
  if((flags&PR_POLL_READ)&&Available(fd))*output|=PR_POLL_READ;
  return *output;
}
}
PRFileDesc* CallbackSocket(Tls* tls) {
  static PRIOMethods methods;
  static PRDescIdentity identity;
  static std::once_flag once;
  std::call_once(once,[]{
    methods=*PR_GetDefaultIOMethods();methods.file_type=PR_DESC_SOCKET_TCP;
    methods.close=Close;methods.read=Read;methods.write=Write;methods.recv=Recv;methods.send=Send;
    methods.getpeername=Address;methods.getsockname=Address;methods.getsocketoption=GetOption;
    methods.setsocketoption=SetOption;methods.available=Available;methods.available64=Available64;methods.poll=Poll;
    identity=PR_GetUniqueIdentity("ruyijs-nss-callback");
  });
  auto* fd=PR_CreateIOLayerStub(identity,&methods);
  if(fd)fd->secret=reinterpret_cast<PRFilePrivate*>(tls);
  return fd;
}
