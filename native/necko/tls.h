#pragma once
#include "core.h"
#include <nss.h>
#include <ssl.h>
#include <sslproto.h>
#include <cert.h>
#include <secerr.h>
#include <prerror.h>
#include <prinit.h>
#include <prnetdb.h>
#include <string>

struct Tls {
  PRFileDesc* fd = nullptr;
  ReadCallback read;
  WriteCallback write;
  WriteSomeCallback writeSome = nullptr;
  CancelCallback idle;
  VerifyCallback verify;
  DecodeCallback decode;
  void* context;
  bool nonblocking = false;
  bool hasByte = false, eof = false;
  uint8_t byte = 0;
  SSLChannelInfo info{};
  std::string alpn;
  ~Tls() { if (fd) PR_Close(fd); }
};
PRFileDesc* CallbackSocket(Tls* tls);
int TlsError();
