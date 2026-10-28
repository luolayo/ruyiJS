#include "tls.h"
#include <memory>
#include <mutex>
#include <vector>

namespace {
thread_local std::string errorText;
SECStatus Verify(void* context,PRFileDesc* fd,PRBool,PRBool) {
  auto& tls=*static_cast<Tls*>(context);
  CERTCertList* chain=SSL_PeerCertificateChain(fd);
  if(!chain)return SECFailure;
  std::vector<uint8_t> bytes;
  bool bounded=true;
  for(auto* node=CERT_LIST_HEAD(chain);!CERT_LIST_END(node,chain);node=CERT_LIST_NEXT(node)) {
    const auto& der=node->cert->derCert;
    if(der.len>1024*1024||bytes.size()+der.len+4>4*1024*1024){bounded=false;break;}
    for(int shift=24;shift>=0;shift-=8)bytes.push_back(uint8_t(der.len>>shift));
    bytes.insert(bytes.end(),der.data,der.data+der.len);
  }
  CERT_DestroyCertList(chain);
  if(!bounded||bytes.empty()||tls.verify(tls.context,bytes.data(),uint32_t(bytes.size()))){
    PR_SetError(SEC_ERROR_UNTRUSTED_CERT,0);return SECFailure;
  }
  return SECSuccess;
}
}
int TlsError() {
  const auto error=PR_GetError();
  const char* text=PR_ErrorToString(error,PR_LANGUAGE_I_DEFAULT);
  errorText=text?text:"NSS operation failed";
  return error==PR_WOULD_BLOCK_ERROR?1:-1;
}
NECKO_API const char* necko_tls_error(){return errorText.c_str();}
NECKO_API const char* necko_tls_nss_version(){return NSS_GetVersion();}
NECKO_API const char* necko_tls_nspr_version(){return PR_GetVersion();}
NECKO_API int necko_tls_open(const char* host,const char* peer,int http2,
    ReadCallback read,WriteCallback write,CancelCallback idle,VerifyCallback verify,DecodeCallback decode,
    void* context,const char*,uint32_t certificates,const char*,uint32_t privateKey,void** output) {
  *output=nullptr;
  if(certificates||privateKey){errorText="Client certificate support is not implemented in the macOS bridge";return -1;}
  static std::once_flag once;static bool initialized=false;
  std::call_once(once,[]{initialized=NSS_NoDB_Init(nullptr)==SECSuccess&&NSS_SetDomesticPolicy()==SECSuccess;});
  if(!initialized)return TlsError();
  auto tls=std::make_unique<Tls>();tls->read=read;tls->write=write;tls->idle=idle;tls->verify=verify;
  tls->decode=decode;tls->context=context;
  PRFileDesc* socket=CallbackSocket(tls.get());
  if(!socket)return TlsError();
  tls->fd=SSL_ImportFD(nullptr,socket);
  if(!tls->fd){PR_Close(socket);return TlsError();}
  SSLVersionRange versions{SSL_LIBRARY_VERSION_TLS_1_2,SSL_LIBRARY_VERSION_TLS_1_3};
  const unsigned char h2[]={2,'h','2',8,'h','t','t','p','/','1','.','1'};
  const unsigned char h1[]={8,'h','t','t','p','/','1','.','1'};
  if(SSL_OptionSet(tls->fd,SSL_SECURITY,PR_TRUE)!=SECSuccess||
     SSL_OptionSet(tls->fd,SSL_HANDSHAKE_AS_CLIENT,PR_TRUE)!=SECSuccess||
     SSL_OptionSet(tls->fd,SSL_ENABLE_ALPN,PR_TRUE)!=SECSuccess||
     SSL_OptionSet(tls->fd,SSL_ENABLE_SESSION_TICKETS,PR_TRUE)!=SECSuccess||
     SSL_VersionRangeSet(tls->fd,&versions)!=SECSuccess||SSL_SetURL(tls->fd,host)!=SECSuccess||
     SSL_SetSockPeerID(tls->fd,peer)!=SECSuccess||SSL_AuthCertificateHook(tls->fd,Verify,tls.get())!=SECSuccess||
     SSL_SetNextProtoNego(tls->fd,http2?h2:h1,http2?sizeof(h2):sizeof(h1))!=SECSuccess||
     SSL_ResetHandshake(tls->fd,PR_FALSE)!=SECSuccess||SSL_ForceHandshake(tls->fd)!=SECSuccess)return TlsError();
  if(SSL_GetChannelInfo(tls->fd,&tls->info,sizeof(tls->info))!=SECSuccess)return TlsError();
  unsigned char protocol[256];unsigned length=0;SSLNextProtoState state;
  if(SSL_GetNextProto(tls->fd,&state,protocol,&length,sizeof(protocol))!=SECSuccess)return TlsError();
  tls->alpn.assign(reinterpret_cast<const char*>(protocol),length);
  *output=tls.release();return 0;
}
NECKO_API int necko_tls_read(void* handle,uint8_t* bytes,uint32_t size,uint32_t* count) {
  *count=0;auto* tls=static_cast<Tls*>(handle);
  if(!size)return 0;
  if(tls->hasByte){
    bytes[0]=tls->byte;tls->hasByte=false;*count=1;
    if(size==1)return 0;
    const auto rest=PR_Read(tls->fd,bytes+1,int32_t(size-1));
    if(rest>0)*count+=uint32_t(rest);
    if(rest==0)tls->eof=true;
    if(rest<0&&PR_GetError()!=PR_WOULD_BLOCK_ERROR)return TlsError();
    return 0;
  }
  if(tls->eof)return 0;
  const auto result=PR_Read(tls->fd,bytes,int32_t(size));
  if(result<0)return TlsError();*count=uint32_t(result);return 0;
}
NECKO_API int necko_tls_write_some(void* handle,const uint8_t* bytes,uint32_t size,uint32_t* count) {
  *count=0;auto* tls=static_cast<Tls*>(handle);
  const auto result=PR_Write(tls->fd,bytes,int32_t(size));
  if(result<0)return TlsError();*count=uint32_t(result);return 0;
}
NECKO_API int necko_tls_write(void* handle,const uint8_t* bytes,uint32_t size) {
  while(size){uint32_t count;int result=necko_tls_write_some(handle,bytes,size,&count);
    if(result)return result;if(!count)return -1;bytes+=count;size-=count;}return 0;
}
NECKO_API void necko_tls_set_nonblocking(void* handle,WriteSomeCallback callback) {
  auto* tls=static_cast<Tls*>(handle);tls->writeSome=callback;tls->nonblocking=true;
}
NECKO_API void necko_tls_close(void* handle){delete static_cast<Tls*>(handle);}
NECKO_API int necko_tls_pending(void* handle){
  auto* tls=static_cast<Tls*>(handle);
  if(tls->hasByte)return 1;
  if(tls->eof)return -1;
  if(!tls->nonblocking)return tls->idle(tls->context)?0:1;
  const auto result=PR_Read(tls->fd,&tls->byte,1);
  if(result>0){tls->hasByte=true;return 1;}
  if(result==0){tls->eof=true;return -1;}
  return PR_GetError()==PR_WOULD_BLOCK_ERROR?0:-1;
}
NECKO_API const char* necko_tls_alpn(void* handle){return static_cast<Tls*>(handle)->alpn.c_str();}
NECKO_API uint16_t necko_tls_version(void* handle){return static_cast<Tls*>(handle)->info.protocolVersion;}
NECKO_API uint16_t necko_tls_cipher(void* handle){return static_cast<Tls*>(handle)->info.cipherSuite;}
NECKO_API int necko_tls_resumed(void* handle){return static_cast<Tls*>(handle)->info.resumed;}
