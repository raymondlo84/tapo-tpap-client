"""TPAP SPAKE2+ protocol prototype, derived from the tapo-rv30-ha reference.

Target: P115(US) at device-ip — plain HTTP on port 80 (tls:0), pake:[2] = userpw.
Usage: TPAP_HOST=device-ip TPAP_USER=... TPAP_PASS=... python tpap_proto.py [method [json_params]]
"""
import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import sys

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from ecdsa import NIST256p, ellipticcurve

P256_M = bytes.fromhex("02886e2f97ace46e55ba9dd7242579f2993b64e16ef3dcab95afd497333d8fa12f")
P256_N = bytes.fromhex("03d8bbd6c639c62937b04d997f38c3770719c629d7014d49a24b4f98baa1292b49")
PAKE_CTX = b"PAKE V1"

CIPHER_LABELS = {
    "aes_128_ccm": {
        "ks": b"tp-kdf-salt-aes128-key", "ki": b"tp-kdf-info-aes128-key",
        "ns": b"tp-kdf-salt-aes128-iv", "ni": b"tp-kdf-info-aes128-iv", "kl": 16,
    },
    "aes_256_ccm": {
        "ks": b"tp-kdf-salt-aes256-key", "ki": b"tp-kdf-info-aes256-key",
        "ns": b"tp-kdf-salt-aes256-iv", "ni": b"tp-kdf-info-aes256-iv", "kl": 32,
    },
    "chacha20_poly1305": {
        "ks": b"tp-kdf-salt-chacha20-key", "ki": b"tp-kdf-info-chacha20-key",
        "ns": b"tp-kdf-salt-chacha20-iv", "ni": b"tp-kdf-info-chacha20-iv", "kl": 32,
    },
}

TAG_LEN = 16
NONCE_LEN = 12


def b64e(b): return base64.b64encode(b).decode()
def b64d(s): return base64.b64decode(s)
def md5hex(s): return hashlib.md5(s.encode()).hexdigest()
def sha1hex(s): return hashlib.sha1(s.encode()).hexdigest()
def sha256(d): return hashlib.sha256(d).digest()
def sha512(d): return hashlib.sha512(d).digest()


def hkdf(master, salt, info, length, alg="SHA256"):
    return HKDF(algorithm=hashes.SHA512() if alg.upper() == "SHA512" else hashes.SHA256(),
                length=length, salt=salt, info=info).derive(master)


def hkdf_expand(label, prk, dlen, alg):
    return HKDF(algorithm=hashes.SHA512() if alg.upper() == "SHA512" else hashes.SHA256(),
                length=dlen, salt=b"\x00" * dlen, info=label.encode()).derive(prk)


def hmac_fn(alg, key, data):
    h = hashlib.sha512 if alg.upper() == "SHA512" else hashlib.sha256
    return hmac.new(key, data, h).digest()


def pbkdf2(pw, salt, iters, length):
    return hashlib.pbkdf2_hmac("sha256", pw, salt, iters, length)


def sec1_xy(sec1):
    p = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sec1)
    n = p.public_numbers()
    return n.x, n.y


def xy_unc(x, y):
    return ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key().public_bytes(
        __import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding"]).Encoding.X962,
        __import__("cryptography.hazmat.primitives.serialization", fromlist=["PublicFormat"]).PublicFormat.UncompressedPoint)


def l8(b): return len(b).to_bytes(8, "little") + b


def encode_w(w):
    ml = 1 if w == 0 else (w.bit_length() + 7) // 8
    u = w.to_bytes(ml, "big", signed=False)
    return (b"\x00" + u) if (ml % 2 != 0 and u[0] & 0x80) else u


def derive_cipher(shared, cid, hkdf_hash):
    L = CIPHER_LABELS[cid]
    key = hkdf(shared, salt=L["ks"], info=L["ki"], length=L["kl"], alg=hkdf_hash)
    nonce = hkdf(shared, salt=L["ns"], info=L["ni"], length=NONCE_LEN, alg=hkdf_hash)
    return key, nonce


def nonce(base, seq): return base[:-4] + struct.pack(">I", seq)


def derive_ab(cred, salt, iters, hl=32):
    iD = hl + 8
    out = pbkdf2(cred, salt, iters, 2 * iD)
    return int.from_bytes(out[:iD], "big"), int.from_bytes(out[iD:], "big")


def build_cred(extra, user, pw, mac12):
    if not extra:
        return (user + "/" + pw) if user else pw
    t = (extra.get("type") or "").lower()
    p = extra.get("params") or {}
    if t == "password_shadow":
        pid = int(p.get("passwd_id", 0))
        if pid == 2:
            return sha1hex(pw)
        if pid == 3 and user and len(mac12) == 12:
            mac = ":".join(mac12[i:i + 2] for i in range(0, 12, 2)).upper()
            return sha1hex(md5hex(user) + "_" + mac)
        return pw
    if t == "password_sha_with_salt":
        name = "admin" if int(p.get("sha_name", -1)) == 0 else "user"
        try:
            salt = base64.b64decode(p.get("sha_salt", "")).decode()
            return hashlib.sha256((name + salt + pw).encode()).hexdigest()
        except Exception:
            return pw
    return (user + "/" + pw) if user else pw


class Tapap:
    def __init__(self, host, username, password, port=80, tls=False):
        self.base = ("https" if tls else "http") + f"://{host}:{port}"
        self.username = username
        self.password = password
        self.http = requests.Session()
        self.mac = ""
        self.pake = []
        self.session_id = ""
        self.seq = 1
        self.cipher_id = "aes_128_ccm"
        self.hkdf_hash = "SHA256"
        self.key = b""
        self.base_nonce = b""

    def post(self, path, body=None, binary=False):
        url = self.base + path
        if binary:
            r = self.http.post(url, data=body,
                               headers={"Content-Type": "application/octet-stream"}, timeout=15)
        else:
            r = self.http.post(url, json=body,
                               headers={"Content-Type": "application/json"}, timeout=15)
        print(f"  POST {path} -> HTTP {r.status_code} ({len(r.content)}B)", file=sys.stderr)
        r.raise_for_status()
        return r.content if binary else r.json()

    def discover(self):
        d = self.post("/", {"method": "login", "params": {"sub_method": "discover"}})
        r = d["result"]
        self.mac = (r.get("mac") or "").replace("-", "").replace(":", "")
        self.pake = (r.get("tpap") or {}).get("pake") or []
        print(f"discover: mac={self.mac} pake={self.pake} tls={r.get('tpap',{}).get('tls')} port={r.get('tpap',{}).get('port')}", file=sys.stderr)
        return r

    def authenticate(self):
        ptype = ("default_userpw" if 0 in self.pake else
                 "userpw" if 2 in self.pake else
                 "shared_token" if 3 in self.pake else "userpw")
        ur = b64e(secrets.token_bytes(32))
        reg = self.post("/", {"method": "login", "params": {
            "sub_method": "pake_register",
            "username": md5hex("admin"),
            "user_random": ur,
            "cipher_suites": [1],
            "encryption": ["aes_128_ccm", "chacha20_poly1305", "aes_256_ccm"],
            "passcode_type": ptype,
            "stok": None,
        }})
        if reg.get("error_code", 0):
            raise RuntimeError(f"pake_register failed: {reg}")
        r = reg["result"]
        print(f"pake_register: {json.dumps({k: v for k, v in r.items() if k not in ('dev_share', 'dev_salt')})}", file=sys.stderr)

        st = int(r.get("cipher_suites") or 2)
        iters = int(r.get("iterations") or 10000)
        self.cipher_id = (r.get("encryption") or "aes_128_ccm").lower().replace("-", "_")
        self.hkdf_hash = "SHA512" if st in (2, 4, 5, 7, 9) else "SHA256"
        cmac = st in (8, 9)
        dlen = 64 if self.hkdf_hash == "SHA512" else 32
        print(f"params: cipher_suites={st} iters={iters} encryption={self.cipher_id} hkdf={self.hkdf_hash} extra_crypt={r.get('extra_crypt')}", file=sys.stderr)

        mac12 = self.mac
        cred = build_cred(r.get("extra_crypt") or {}, self.username, self.password, mac12)

        G = NIST256p.generator
        order = G.order()
        curve = NIST256p.curve
        Mx, My = sec1_xy(P256_M)
        Nx, Ny = sec1_xy(P256_N)
        M = ellipticcurve.Point(curve, Mx, My, order)
        N = ellipticcurve.Point(curve, Nx, Ny, order)

        a, b = derive_ab(cred.encode(), b64d(r["dev_salt"]), iters)
        w, h = a % order, b % order
        x = secrets.randbelow(order - 1) + 1

        L = x * G + w * M
        L_enc = xy_unc(L.x(), L.y())
        Rx, Ry = sec1_xy(b64d(r["dev_share"]))
        R = ellipticcurve.Point(curve, Rx, Ry, order)
        R_enc = xy_unc(R.x(), R.y())
        Rp = R + (-(w * N))
        Z_enc = xy_unc((x * Rp).x(), (x * Rp).y())
        V_enc = xy_unc(((h % order) * Rp).x(), ((h % order) * Rp).y())

        hfn = sha512 if self.hkdf_hash == "SHA512" else sha256
        ctx = hfn(PAKE_CTX + b64d(ur) + b64d(r["dev_random"]))
        trans = (l8(ctx) + l8(b"") + l8(b"")
                 + l8(xy_unc(Mx, My)) + l8(xy_unc(Nx, Ny))
                 + l8(L_enc) + l8(R_enc) + l8(Z_enc) + l8(V_enc)
                 + l8(encode_w(w)))
        T = hfn(trans)

        ml = 16 if cmac else 32
        conf = hkdf_expand("ConfirmationKeys", T, ml * 2, self.hkdf_hash)
        KcA, KcB = conf[:ml], conf[ml:ml + ml]
        shared = hkdf_expand("SharedKey", T, dlen, self.hkdf_hash)
        from cryptography.hazmat.primitives.cmac import CMAC
        from cryptography.hazmat.primitives.ciphers import algorithms as _algs
        mac_fn = (lambda k, d: (CMAC(_algs.AES(k)).update(d), CMAC(_algs.AES(k)).finalize())[1]) if cmac else (lambda k, d: hmac_fn(self.hkdf_hash, k, d))
        u_conf = mac_fn(KcA, R_enc)
        e_conf = mac_fn(KcB, L_enc)

        share = self.post("/", {"method": "login", "params": {
            "sub_method": "pake_share",
            "user_share": b64e(L_enc),
            "user_confirm": b64e(u_conf),
        }})
        if share.get("error_code", 0):
            raise RuntimeError(f"pake_share failed: {share}")
        s = share["result"]
        if (s.get("dev_confirm") or "").lower() != b64e(e_conf).lower():
            raise RuntimeError("SPAKE2+ confirmation mismatch — wrong password or derivation")
        self.session_id = s.get("sessionId") or s.get("stok") or ""
        self.seq = int(s.get("start_seq") or 1)
        self.key, self.base_nonce = derive_cipher(shared, self.cipher_id, self.hkdf_hash)
        print(f"AUTH OK session={self.session_id[:8]}... seq={self.seq}", file=sys.stderr)

    def send(self, method, params=None):
        if not self.session_id:
            self.authenticate()
        for attempt in range(2):
            try:
                pt = json.dumps({"method": method, "params": params or {}}).encode()
                aead = AESCCM(self.key, tag_length=TAG_LEN)
                if self.cipher_id.startswith("aes_"):
                    ct = aead.encrypt(nonce(self.base_nonce, self.seq), pt, None)
                else:
                    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
                    ct = ChaCha20Poly1305(self.key).encrypt(nonce(self.base_nonce, self.seq), pt, None)
                payload = struct.pack(">I", self.seq) + ct
                raw = self.post(f"/stok={self.session_id}/ds", payload, binary=True)
                if len(raw) < 4 + TAG_LEN:
                    raise RuntimeError(f"Response too short ({len(raw)} bytes): {raw!r}")
                rseq = struct.unpack(">I", raw[:4])[0]
                aead = AESCCM(self.key, tag_length=TAG_LEN)
                if self.cipher_id.startswith("aes_"):
                    plain = aead.decrypt(nonce(self.base_nonce, rseq), raw[4:], None)
                else:
                    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
                    plain = ChaCha20Poly1305(self.key).decrypt(nonce(self.base_nonce, rseq), raw[4:], None)
                self.seq += 1
                resp = json.loads(plain.decode())
                if resp.get("error_code", 0):
                    raise RuntimeError(f"Device error {resp['error_code']}: {resp}")
                return resp
            except RuntimeError as e:
                msg = str(e)
                if attempt == 0 and "mismatch" not in msg and "too short" in msg:
                    print(f"  retrying with re-auth ({msg})...", file=sys.stderr)
                    self.session_id = ""
                    self.authenticate()
                else:
                    raise

    def close(self):
        try:
            self.post("/", {"method": "logout", "params": {}})
        except Exception:
            pass


def main():
    host = os.environ.get("TPAP_HOST", "device-ip")
    user = os.environ.get("TPAP_USER", "")
    pw = os.environ.get("TPAP_PASS", "")
    port = int(os.environ.get("TPAP_PORT", "80"))
    tls = os.environ.get("TPAP_TLS", "0") == "1"
    # TPAP method names are snake_case; camelCase returns error_code -1002.
    method = sys.argv[1] if len(sys.argv) > 1 else "get_device_info"
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}

    c = Tapap(host, user, pw, port=port, tls=tls)
    c.discover()
    c.authenticate()
    resp = c.send(method, params)
    print(json.dumps(resp, indent=2))


if __name__ == "__main__":
    main()
