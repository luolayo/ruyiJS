#include "exchange.h"
#include <charconv>
#include <cstring>

int Exchange::Fill() {
  uint8_t buffer[16384]; uint32_t size=0;
  int error=read(context,buffer,sizeof(buffer),&size);
  if (error) return error;
  if (!size) return 7;
  pending.append(reinterpret_cast<char*>(buffer),size);
  return 0;
}
int Exchange::Line(std::string* output) {
  for (;;) {
    auto end=pending.find("\r\n");
    if (end!=pending.npos) { if(end>65536)return 1;*output=pending.substr(0,end);pending.erase(0,end+2);return 0; }
    if (pending.size()>65536) return 1;
    if (int error=Fill()) return error;
  }
}
int Exchange::HeaderBlock() {
  for (unsigned interim=0;interim<16;++interim) {
    std::string line;
    if (int error=Line(&line)) return error;
    bool http11=line.starts_with("HTTP/1.1 ");
    if ((!http11&&!line.starts_with("HTTP/1.0 "))||line.size()<12||
        (line.size()>12&&line[12]!=' ')||line.find_first_of("\r\n")!=line.npos||line.find('\0')!=line.npos) return 1;
    uint64_t status;
    if(!Decimal(line.substr(9,3),&status)||status<100||status>599) return 1;
    headers=line+"\r\n";reusable=http11;sized=false;chunked=false;
    unsigned count=0;bool closeSeen=false;
    while(true) {
      if(int error=Line(&line))return error;
      if(line.empty())break;
      if(++count>256||headers.size()+line.size()+2>65536||line.find('\0')!=line.npos||line.find_first_of("\r\n")!=line.npos) return 1;
      auto colon=line.find(':');if(colon==line.npos||!colon||line[0]==' '||line[0]=='\t')return 1;
      auto name=Lower(line.substr(0,colon)),value=Lower(Trim(line.substr(colon+1)));
      if(!HeaderToken(name))return 1;
      if(name=="content-length") {
        uint64_t length;if(!Decimal(value,&length)||(sized&&length!=remaining))return 1;
        sized=true;remaining=length;
      }
      if(name=="transfer-encoding") {if(chunked||value!="chunked")return 1;chunked=true;}
      if(name=="connection") {
        if(value.find("close")!=value.npos){reusable=false;closeSeen=true;}
        else if(value=="keep-alive")reusable=true;
      }
      headers+=line+"\r\n";
    }
    if(closeSeen)reusable=false;
    if(chunked&&sized)return 1;
    if(status>=100&&status<200&&status!=101)continue;
    done=method=="HEAD"||status==204||status==304||status==101;
    if(status==101)reusable=false;
    if(chunked)remaining=0;
    if(!sized&&!chunked&&!done)reusable=false;
    if(sized&&!remaining)done=true;
    return 0;
  }
  return 1;
}
int Exchange::Read(uint8_t* bytes,uint32_t capacity,uint32_t* count) {
  *count=0;if(done||!capacity)return 0;
  if(chunked&&!remaining) {
    std::string line;
    if(chunkEnd) {if(int error=Line(&line))return error;if(!line.empty())return 1;chunkEnd=false;}
    if(int error=Line(&line))return error;
    auto number=line.substr(0,line.find(';'));
    auto parsed=std::from_chars(number.data(),number.data()+number.size(),remaining,16);
    if(number.empty()||parsed.ec!=std::errc{}||parsed.ptr!=number.data()+number.size())return 1;
    if(!remaining) {
      size_t size=0;unsigned fields=0;
      for(;;) {
        if(int error=Line(&line))return error;
        if(line.empty())break;
        size+=line.size()+2;
        auto colon=line.find(':');
        if(++fields>256||size>65536||colon==line.npos||!HeaderToken(line.substr(0,colon))||
            line.find('\0')!=line.npos||line.find_first_of("\r\n")!=line.npos)return 1;
      }
      done=true;return 0;
    }
  }
  if(pending.empty()) {
    int error=Fill();
    if(error==7&&!sized&&!chunked){done=true;return 0;}
    if(error)return error;
  }
  size_t size=std::min<size_t>(capacity,pending.size());
  if(sized||chunked)size=std::min<uint64_t>(size,remaining);
  std::memcpy(bytes,pending.data(),size);pending.erase(0,size);*count=uint32_t(size);
  if(sized||chunked)remaining-=size;
  if(sized&&!remaining)done=true;
  if(chunked&&!remaining)chunkEnd=true;
  return 0;
}
