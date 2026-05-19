"""LTC Wallet — litecoinspace.org API + manual P2PKH (base58/ecdsa)."""

import hashlib
import os
import secrets
import struct
from datetime import datetime, timezone

import base58
import ecdsa
import requests

API_BASE = os.environ.get("LTCSPACE_API_BASE", "https://litecoinspace.org/api")
SAT = 100_000_000

# LTC mainnet:
# WIF prefix 0xB0, P2PKH prefix 0x30 ("L..."), P2SH prefix 0x32 ("M..." / "3...").
LTC_WIF_PREFIX = 0xB0
LTC_P2PKH_PREFIX = 0x30


def _ripemd160(data: bytes) -> bytes:
    h = hashlib.new("ripemd160")
    h.update(data)
    return h.digest()


def _hash160(data: bytes) -> bytes:
    return _ripemd160(hashlib.sha256(data).digest())


def _double_sha256(data: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(data).digest()).digest()


def _pubkey_to_p2pkh(pubkey_bytes: bytes) -> str:
    payload = bytes([LTC_P2PKH_PREFIX]) + _hash160(pubkey_bytes)
    checksum = _double_sha256(payload)[:4]
    return base58.b58encode(payload + checksum).decode()


def _wif_from_priv(priv32: bytes, compressed: bool = True) -> str:
    payload = bytes([LTC_WIF_PREFIX]) + priv32
    if compressed:
        payload += b"\x01"
    checksum = _double_sha256(payload)[:4]
    return base58.b58encode(payload + checksum).decode()


def _priv_from_wif(wif: str) -> tuple[bytes, bool]:
    raw = base58.b58decode_check(wif)
    if raw[0] != LTC_WIF_PREFIX:
        raise ValueError("Not a LTC WIF")
    if len(raw) == 34 and raw[-1] == 0x01:
        return raw[1:33], True
    return raw[1:33], False


def _pubkey_compressed(priv32: bytes) -> bytes:
    sk = ecdsa.SigningKey.from_string(priv32, curve=ecdsa.SECP256k1)
    vk = sk.get_verifying_key()
    x = vk.pubkey.point.x()
    y = vk.pubkey.point.y()
    prefix = b"\x02" if (y % 2 == 0) else b"\x03"
    return prefix + x.to_bytes(32, "big")


def _iso(ts: int) -> str:
    if not ts:
        return ""
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


class Wallet:
    SYMBOL = "LTC"
    NAME = "Litecoin"

    def __init__(self, private_key: str | None = None):
        if private_key:
            try:
                if len(private_key) == 64:
                    self._priv = bytes.fromhex(private_key)
                else:
                    self._priv, _ = _priv_from_wif(private_key)
            except Exception as e:
                raise ValueError(f"Invalid LTC private key: {e}")
        else:
            self._priv = secrets.token_bytes(32)
        self._pub = _pubkey_compressed(self._priv)
        self._address = _pubkey_to_p2pkh(self._pub)

    @property
    def address(self) -> str:
        return self._address

    @property
    def private_key_hex(self) -> str:
        return self._priv.hex()

    @property
    def wif(self) -> str:
        return _wif_from_priv(self._priv, compressed=True)

    def validate_address(self, addr: str) -> bool:
        if not isinstance(addr, str):
            return False
        if addr.startswith("ltc1"):  # bech32
            return 14 < len(addr) < 90
        try:
            raw = base58.b58decode_check(addr)
        except Exception:
            return False
        return raw[0] in (0x30, 0x32, 0x05)  # P2PKH, P2SH-new, P2SH-old

    def get_balance(self) -> dict:
        try:
            r = requests.get(f"{API_BASE}/address/{self.address}", timeout=30)
            r.raise_for_status()
            data = r.json()
            funded = int(data.get("chain_stats", {}).get("funded_txo_sum", 0))
            spent = int(data.get("chain_stats", {}).get("spent_txo_sum", 0))
            return {"native": (funded - spent) / SAT, "tokens": {}}
        except Exception as e:
            return {"native": 0.0, "tokens": {}, "error": str(e)}

    # ---------- send ----------

    def _get_utxos(self) -> list[dict]:
        r = requests.get(f"{API_BASE}/address/{self.address}/utxo", timeout=30)
        r.raise_for_status()
        return r.json()

    def _estimate_fee_per_vb(self) -> float:
        try:
            r = requests.get(f"{API_BASE}/v1/fees/recommended", timeout=15)
            r.raise_for_status()
            return float(r.json().get("halfHourFee", 5))
        except Exception:
            return 5.0

    def _enforce_low_s(self, der: bytes) -> bytes:
        # BIP-62 low-S
        ORDER = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141
        HALF = ORDER >> 1
        # parse DER: 30 LEN 02 RLEN R 02 SLEN S
        assert der[0] == 0x30
        r_len = der[3]
        r_start = 4
        s_start = r_start + r_len + 2
        s_len = der[s_start - 1]
        r = int.from_bytes(der[r_start:r_start + r_len], "big")
        s = int.from_bytes(der[s_start:s_start + s_len], "big")
        if s > HALF:
            s = ORDER - s
        def _enc(x: int) -> bytes:
            b = x.to_bytes((x.bit_length() + 7) // 8 or 1, "big")
            if b[0] & 0x80:
                b = b"\x00" + b
            return b
        r_b = _enc(r)
        s_b = _enc(s)
        body = b"\x02" + bytes([len(r_b)]) + r_b + b"\x02" + bytes([len(s_b)]) + s_b
        return b"\x30" + bytes([len(body)]) + body

    def _addr_to_p2pkh_script(self, addr: str) -> bytes:
        raw = base58.b58decode_check(addr)
        h160 = raw[1:]
        # OP_DUP OP_HASH160 <20> hash160 OP_EQUALVERIFY OP_CHECKSIG
        return b"\x76\xa9\x14" + h160 + b"\x88\xac"

    def send(self, to: str, amount: float) -> dict:
        if not self.validate_address(to):
            return {"success": False, "txid": None, "error": "Invalid LTC address"}
        if not to.startswith(("L", "M", "3")):
            return {
                "success": False,
                "txid": None,
                "error": "Only legacy/P2SH destinations supported (bech32 not yet implemented)",
            }
        try:
            send_sat = int(round(amount * SAT))
            utxos = self._get_utxos()
            utxos = [u for u in utxos if u.get("status", {}).get("confirmed", False)]
            if not utxos:
                return {"success": False, "txid": None, "error": "No confirmed UTXOs"}

            fee_per_vb = self._estimate_fee_per_vb()
            own_script = self._addr_to_p2pkh_script(self.address)
            to_script = self._addr_to_p2pkh_script(to)

            # Pick UTXOs greedily
            utxos.sort(key=lambda u: u["value"], reverse=True)
            chosen = []
            total = 0
            for u in utxos:
                chosen.append(u)
                total += u["value"]
                # Rough size estimate: 10 + 148*ins + 34*outs
                est_size = 10 + 148 * len(chosen) + 34 * 2
                fee = int(est_size * fee_per_vb)
                if total >= send_sat + fee:
                    break
            est_size = 10 + 148 * len(chosen) + 34 * 2
            fee = int(est_size * fee_per_vb)
            if total < send_sat + fee:
                return {"success": False, "txid": None, "error": "Insufficient funds"}
            change = total - send_sat - fee

            # Build tx (manual P2PKH)
            version = struct.pack("<I", 2)
            locktime = struct.pack("<I", 0)
            sequence = struct.pack("<I", 0xFFFFFFFF)
            sighash_all = struct.pack("<I", 1)

            outputs = []
            outputs.append(struct.pack("<Q", send_sat) + bytes([len(to_script)]) + to_script)
            if change > 0:
                outputs.append(struct.pack("<Q", change) + bytes([len(own_script)]) + own_script)
            outs_ser = bytes([len(outputs)]) + b"".join(outputs)

            signed_ins = []
            sk = ecdsa.SigningKey.from_string(self._priv, curve=ecdsa.SECP256k1)

            for idx, u in enumerate(chosen):
                # Сборка препрообраза для подписи (legacy SIGHASH_ALL)
                ins_ser = bytes([len(chosen)])
                for j, uu in enumerate(chosen):
                    prev_txid = bytes.fromhex(uu["txid"])[::-1]
                    prev_vout = struct.pack("<I", uu["vout"])
                    if j == idx:
                        script = own_script
                        ins_ser += prev_txid + prev_vout + bytes([len(script)]) + script + sequence
                    else:
                        ins_ser += prev_txid + prev_vout + b"\x00" + sequence
                preimage = version + ins_ser + outs_ser + locktime + sighash_all
                sig_hash = _double_sha256(preimage)
                sig_der = sk.sign_digest_deterministic(sig_hash, hashfunc=hashlib.sha256, sigencode=ecdsa.util.sigencode_der)
                sig_der = self._enforce_low_s(sig_der)
                sig_with_hashtype = sig_der + b"\x01"
                script_sig = bytes([len(sig_with_hashtype)]) + sig_with_hashtype + bytes([len(self._pub)]) + self._pub
                signed_ins.append((u, script_sig))

            # Final tx
            ins_final = bytes([len(signed_ins)])
            for u, ss in signed_ins:
                prev_txid = bytes.fromhex(u["txid"])[::-1]
                prev_vout = struct.pack("<I", u["vout"])
                ins_final += prev_txid + prev_vout + bytes([len(ss)]) + ss + sequence
            raw_tx = version + ins_final + outs_ser + locktime

            r = requests.post(f"{API_BASE}/tx", data=raw_tx.hex(), timeout=30)
            if r.status_code >= 400:
                return {"success": False, "txid": None, "error": f"broadcast: {r.text}"}
            txid = r.text.strip()
            return {"success": True, "txid": txid, "error": None}
        except Exception as e:
            return {"success": False, "txid": None, "error": str(e)}

    def get_history(self, limit: int = 20) -> list[dict]:
        try:
            r = requests.get(f"{API_BASE}/address/{self.address}/txs", timeout=30)
            r.raise_for_status()
            txs = r.json()[:limit]
        except Exception:
            return []
        out = []
        my = self.address
        for tx in txs:
            received = sum(
                v.get("value", 0) for v in tx.get("vout", [])
                if v.get("scriptpubkey_address") == my
            )
            spent = sum(
                vin.get("prevout", {}).get("value", 0) for vin in tx.get("vin", [])
                if vin.get("prevout", {}).get("scriptpubkey_address") == my
            )
            net = received - spent
            direction = "in" if net >= 0 else "out"
            counter_in = next(
                (vin.get("prevout", {}).get("scriptpubkey_address")
                 for vin in tx.get("vin", [])
                 if vin.get("prevout", {}).get("scriptpubkey_address") != my),
                None,
            )
            counter_out = next(
                (v.get("scriptpubkey_address") for v in tx.get("vout", [])
                 if v.get("scriptpubkey_address") != my),
                None,
            )
            out.append({
                "txid": tx.get("txid"),
                "from": counter_in if direction == "in" else my,
                "to": counter_out if direction == "out" else my,
                "amount": abs(net) / SAT,
                "time": _iso(tx.get("status", {}).get("block_time", 0)),
                "direction": direction,
            })
        return out


if __name__ == "__main__":
    w = Wallet()
    print(f"{w.NAME} address: {w.address}")
    print(f"private_key_hex: {w.private_key_hex[:10]}...")
    print(f"WIF: {w.wif}")
    print(f"valid: {w.validate_address(w.address)}")
