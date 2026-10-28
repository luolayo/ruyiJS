#ifndef _WIN32
#include "web_crypto/cng_backend.h"
#include <openssl/bn.h>
#include <openssl/ec.h>
#include <openssl/ecdsa.h>
#include <openssl/obj_mac.h>
#include <memory>

namespace ruyijs::web_crypto {
namespace ec = domain::crypto;
namespace {
using Key = std::unique_ptr<EC_KEY, decltype(&EC_KEY_free)>;
using Number = std::unique_ptr<BIGNUM, decltype(&BN_clear_free)>;
using Point = std::unique_ptr<EC_POINT, decltype(&EC_POINT_free)>;
int CurveId(const ec::EcCurve& curve) {
  return curve.size == 32 ? NID_X9_62_prime256v1 : curve.size == 48 ? NID_secp384r1 : NID_secp521r1;
}
Key Import(const ec::EcKey& value) {
  Key key(value.curve ? EC_KEY_new_by_curve_name(CurveId(*value.curve)) : nullptr, EC_KEY_free);
  if (!key || value.x.size() != value.curve->size || value.y.size() != value.curve->size) return {nullptr, EC_KEY_free};
  const auto* group = EC_KEY_get0_group(key.get());
  Number x(BN_bin2bn(value.x.data(), int(value.x.size()), nullptr), BN_clear_free);
  Number y(BN_bin2bn(value.y.data(), int(value.y.size()), nullptr), BN_clear_free);
  Point point(EC_POINT_new(group), EC_POINT_free);
  if (!x || !y || !point || !EC_POINT_set_affine_coordinates(group, point.get(), x.get(), y.get(), nullptr) ||
      !EC_KEY_set_public_key(key.get(), point.get())) return {nullptr, EC_KEY_free};
  if (!value.d.empty()) {
    Number d(BN_bin2bn(value.d.data(), int(value.d.size()), nullptr), BN_clear_free);
    if (!d || !EC_KEY_set_private_key(key.get(), d.get())) return {nullptr, EC_KEY_free};
  }
  if (EC_KEY_check_key(key.get()) != 1) return {nullptr, EC_KEY_free};
  return key;
}
bool Export(const BIGNUM* value, size_t size, Bytes* out) {
  out->resize(size);
  return value && BN_bn2binpad(value, out->data(), int(size)) == int(size);
}
}
bool EcGenerate(const ec::EcCurve& curve, bool, ec::EcKey* out) {
  Key key(EC_KEY_new_by_curve_name(CurveId(curve)), EC_KEY_free);
  if (!key || !EC_KEY_generate_key(key.get())) return false;
  Number x(BN_new(), BN_clear_free), y(BN_new(), BN_clear_free);
  if (!x || !y || !EC_POINT_get_affine_coordinates(EC_KEY_get0_group(key.get()),
      EC_KEY_get0_public_key(key.get()), x.get(), y.get(), nullptr)) return false;
  out->curve = &curve;
  return Export(x.get(), curve.size, &out->x) && Export(y.get(), curve.size, &out->y) &&
         Export(EC_KEY_get0_private_key(key.get()), curve.size, &out->d);
}
bool EcValidate(const ec::EcKey& value, bool) { return bool(Import(value)); }
bool EcdsaSign(const ec::EcKey& value, HashAlgorithm hash, const Bytes& message, Bytes* out) {
  auto key = Import(value);
  DigestBytes digest;
  if (!key || value.d.empty() || !ComputeDigest(hash, message.data(), message.size(), &digest)) return false;
  std::unique_ptr<ECDSA_SIG, decltype(&ECDSA_SIG_free)> signature(
      ECDSA_do_sign(digest.data, int(digest.size), key.get()), ECDSA_SIG_free);
  if (!signature) return false;
  const BIGNUM* r; const BIGNUM* s;
  ECDSA_SIG_get0(signature.get(), &r, &s);
  Bytes left, right;
  if (!Export(r, value.curve->size, &left) || !Export(s, value.curve->size, &right)) return false;
  *out = std::move(left); out->insert(out->end(), right.begin(), right.end());
  return true;
}
bool EcdsaVerify(const ec::EcKey& value, HashAlgorithm hash, const Bytes& message,
                 const Bytes& bytes, bool* valid) {
  *valid = false;
  auto key = Import(value);
  DigestBytes digest;
  if (!key || !ComputeDigest(hash, message.data(), message.size(), &digest)) return false;
  if (bytes.size() != 2 * value.curve->size) return true;
  std::unique_ptr<ECDSA_SIG, decltype(&ECDSA_SIG_free)> signature(ECDSA_SIG_new(), ECDSA_SIG_free);
  Number r(BN_bin2bn(bytes.data(), int(value.curve->size), nullptr), BN_clear_free);
  Number s(BN_bin2bn(bytes.data() + value.curve->size, int(value.curve->size), nullptr), BN_clear_free);
  if (!signature || !r || !s || !ECDSA_SIG_set0(signature.get(), r.get(), s.get())) return false;
  r.release(); s.release();
  *valid = ECDSA_do_verify(digest.data, int(digest.size), signature.get(), key.get()) == 1;
  return true;
}
bool EcdhSecret(const ec::EcKey& value, const ec::EcKey& peer, Bytes* out) {
  if (value.curve != peer.curve || value.d.empty()) return false;
  auto key = Import(value), publicKey = Import(peer);
  if (!key || !publicKey) return false;
  out->resize(value.curve->size);
  const int size = ECDH_compute_key(out->data(), out->size(), EC_KEY_get0_public_key(publicKey.get()), key.get(), nullptr);
  return size == int(out->size());
}
}
#endif
