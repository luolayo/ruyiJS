#ifndef _WIN32
#include "web_crypto/cng_backend.h"
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <limits>
#include <memory>

namespace ruyijs::web_crypto {
const EVP_MD* OpenSslDigest(HashAlgorithm hash) {
  switch (hash) {
    case HashAlgorithm::Sha1: return EVP_sha1();
    case HashAlgorithm::Sha256: return EVP_sha256();
    case HashAlgorithm::Sha384: return EVP_sha384();
    case HashAlgorithm::Sha512: return EVP_sha512();
  }
  return nullptr;
}
bool ComputeDigest(HashAlgorithm hash, const void* input, size_t size, DigestBytes* out) noexcept {
  unsigned length = 0;
  if (!EVP_Digest(input, size, out->data, &length, OpenSslDigest(hash), nullptr)) return false;
  out->size = length;
  return true;
}
bool Hmac(HashAlgorithm hash, const Bytes& key, const Bytes& data, Bytes* out) {
  if (key.size() > INT_MAX) return false;
  unsigned length = EVP_MAX_MD_SIZE;
  out->resize(length);
  const uint8_t empty = 0;
  if (!HMAC(OpenSslDigest(hash), key.empty() ? &empty : key.data(), int(key.size()),
            data.data(), data.size(), out->data(), &length)) return false;
  out->resize(length);
  return true;
}
static const EVP_CIPHER* Cipher(size_t size, bool gcm) {
  if (size == 16) return gcm ? EVP_aes_128_gcm() : EVP_aes_128_cbc();
  if (size == 24) return gcm ? EVP_aes_192_gcm() : EVP_aes_192_cbc();
  if (size == 32) return gcm ? EVP_aes_256_gcm() : EVP_aes_256_cbc();
  return nullptr;
}
bool AesCbc(const Bytes& key, const Bytes& iv, const Bytes& input, bool encrypt, Bytes* out) {
  const auto* cipher = Cipher(key.size(), false);
  if (!cipher || iv.size() != 16 || input.size() > INT_MAX - 16) return false;
  std::unique_ptr<EVP_CIPHER_CTX, decltype(&EVP_CIPHER_CTX_free)> context(EVP_CIPHER_CTX_new(), EVP_CIPHER_CTX_free);
  if (!context || !EVP_CipherInit_ex(context.get(), cipher, nullptr, key.data(), iv.data(), encrypt)) return false;
  out->resize(input.size() + 16);
  int length = 0, last = 0;
  if (!EVP_CipherUpdate(context.get(), out->data(), &length, input.data(), int(input.size())) ||
      !EVP_CipherFinal_ex(context.get(), out->data() + length, &last)) { out->clear(); return false; }
  out->resize(size_t(length + last));
  return true;
}
bool AesGcm(const Bytes& key, const Bytes& iv, const Bytes& aad, size_t tag,
            const Bytes& input, bool encrypt, Bytes* out) {
  const auto* cipher = Cipher(key.size(), true);
  if (!cipher || iv.empty() || iv.size() > INT_MAX || aad.size() > INT_MAX ||
      input.size() > INT_MAX - 16 || tag < 4 || tag > 16 || (!encrypt && input.size() < tag)) return false;
  std::unique_ptr<EVP_CIPHER_CTX, decltype(&EVP_CIPHER_CTX_free)> context(EVP_CIPHER_CTX_new(), EVP_CIPHER_CTX_free);
  if (!context || !EVP_CipherInit_ex(context.get(), cipher, nullptr, nullptr, nullptr, encrypt) ||
      !EVP_CIPHER_CTX_ctrl(context.get(), EVP_CTRL_GCM_SET_IVLEN, int(iv.size()), nullptr) ||
      !EVP_CipherInit_ex(context.get(), nullptr, nullptr, key.data(), iv.data(), encrypt)) return false;
  int ignored = 0, length = 0, last = 0;
  if (!aad.empty() && !EVP_CipherUpdate(context.get(), nullptr, &ignored, aad.data(), int(aad.size()))) return false;
  const size_t size = encrypt ? input.size() : input.size() - tag;
  out->resize(size + 16);
  if (!EVP_CipherUpdate(context.get(), out->data(), &length, input.data(), int(size))) return false;
  if (!encrypt && !EVP_CIPHER_CTX_ctrl(context.get(), EVP_CTRL_GCM_SET_TAG, int(tag),
                                      const_cast<uint8_t*>(input.data() + size))) return false;
  if (!EVP_CipherFinal_ex(context.get(), out->data() + length, &last)) { out->clear(); return false; }
  out->resize(size_t(length + last) + (encrypt ? tag : 0));
  return !encrypt || EVP_CIPHER_CTX_ctrl(context.get(), EVP_CTRL_GCM_GET_TAG, int(tag), out->data() + length + last);
}
}
#endif
