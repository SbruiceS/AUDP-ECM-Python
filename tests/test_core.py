"""Functional, known-answer and security tests for the audp_ecm bindings."""

import threading

import pytest

import audp_ecm as ecm


# --- known answers (match the core repo's tests/unit/rs_known_answers.md) ----

def test_gf256_vectors():
    assert ecm.gf_mul(0x53, 0xCA) == 0x8F
    assert ecm.gf_mul(0xFF, 0xFF) == 0xE2
    assert ecm.gf_mul(0x80, 0x02) == 0x1D
    for a in range(1, 256):
        assert ecm.gf_mul(a, ecm.gf_inv(a)) == 1
        assert ecm.gf_pow(a, 255) == 1
    with pytest.raises(ValueError):
        ecm.gf_inv(0)


def test_crc16_check_value():
    assert ecm.crc16(b"123456789") == 0x29B1
    framed = ecm.append_crc16(b"ASPF")
    assert ecm.verify_crc16(framed) == b"ASPF"
    bad = bytearray(framed)
    bad[0] ^= 1
    with pytest.raises(ecm.DecodeError):
        ecm.verify_crc16(bad)
    with pytest.raises(ecm.InputLengthError):
        ecm.verify_crc16(b"\x01")


def test_rs_7_3_known_codeword():
    rs = ecm.ReedSolomon(7, 3)
    assert rs.encode(b"\x01\x02\x03") == bytes([0x17, 0x3A, 0x51, 0x52, 1, 2, 3])
    assert (rs.n, rs.k, rs.t) == (7, 3, 2)


# --- Reed–Solomon behaviour --------------------------------------------------

def test_rs_errors_and_erasures_full_budget():
    rs = ecm.ReedSolomon(31, 23)
    data = bytes(range(23))
    cw = rs.encode(data)
    assert rs.is_codeword(cw)
    for s in range(0, 9):
        for e in range(0, (8 - s) // 2 + 1):
            rx = bytearray(cw)
            eras = list(range(31 - s, 31))
            for p in eras:
                rx[p] ^= 0x33
            for i in range(e):
                rx[2 * i] ^= 0x5C
            res = rs.decode(rx, eras)
            assert res.data == data and res.verified
            assert res.corrected_symbols == e and res.erasures == s
            assert rs.decode_euclidean(rx, eras).data == data


def test_rs_over_budget_raises():
    rs = ecm.ReedSolomon(15, 11)
    cw = bytearray(rs.encode(bytes(11)))
    for i in range(6):
        cw[i] ^= 0xFF
    try:
        res = rs.decode(cw)
    except ecm.DecodeError:
        return
    assert res.data != bytes(11)  # miscorrection to another codeword is the only alternative


def test_bytes_like_inputs():
    rs = ecm.ReedSolomon(15, 11)
    data = bytes(range(11))
    for form in (data, bytearray(data), memoryview(data)):
        assert rs.encode(form) == rs.encode(data)
    with pytest.raises(TypeError):
        rs.encode("not bytes")
    with pytest.raises(TypeError):
        rs.encode(memoryview(bytes(22))[::2])


# --- burst pipeline ----------------------------------------------------------

def test_burst_codec_exact_payload_and_tolerance():
    codec = ecm.BurstCodec.for_burst(31, 23, payload_len=40, burst_len=14)
    assert codec.burst_tolerance >= 14
    payload = b"node=17;soil_moisture=0.42;temp=21.7"
    tx = bytearray(codec.protect(payload))
    assert len(tx) == codec.encoded_len
    for i in range(30, 30 + codec.burst_tolerance):
        tx[i] ^= 0xC3
    assert codec.recover(tx) == payload


def test_burst_codec_stream_erasures():
    codec = ecm.BurstCodec(31, 23, 4)
    tx = bytearray(codec.protect(b"valve=open"))
    eras = list(range(10, 42))  # 32 = depth * (n - k)
    for i in eras:
        tx[i] = 0
    assert codec.recover(tx, eras) == b"valve=open"


def test_interleave_roundtrip():
    cws = [bytes([i] * 7) for i in range(3)]
    tx = ecm.interleave_codewords(cws)
    assert tx[:3] == bytes([0, 1, 2])
    assert ecm.deinterleave_codewords(tx, 3) == cws


# --- BCH, soft info, channels ------------------------------------------------

def test_bch_roundtrip():
    bch = ecm.BchCode(31, 2)
    assert (bch.n, bch.t) == (31, 2) and 0 < bch.k < 31
    bits = [bool(i % 3 == 0) for i in range(bch.k)]
    cw = bch.encode(bits)
    cw[0] = not cw[0]
    cw[7] = not cw[7]
    assert bch.decode(cw) == bits
    with pytest.raises(ecm.ConfigError):
        ecm.BchCode(15, 2)  # generator degree 16 > n (shortened BCH(255,.))


def test_mark_erasures_bounded():
    rel = [0.9, 0.1, 0.05, 0.3, 0.2, 0.95]
    assert ecm.mark_erasures(rel, 0.5) == [1, 2, 3, 4]
    assert ecm.mark_erasures(rel, 0.5, max_erasures=2) == [1, 2]


def test_channels_rates_and_validation():
    n = 20_000
    rx = ecm.SymbolErrorChannel(0.3).corrupt(bytes(n), seed=7)
    rate = sum(1 for b in rx if b) / n
    assert abs(rate - 0.3) < 0.02
    word, eras = ecm.ErasureChannel(0.2).corrupt(bytes(1000), seed=3)
    assert len(word) == 1000 and all(0 <= i < 1000 for i in eras)
    assert ecm.BurstErrorChannel(0.01, 0.5).mean_burst_length == pytest.approx(2.0)
    for bad in (-0.1, 1.5, float("nan"), float("inf")):
        with pytest.raises(ValueError):
            ecm.SymbolErrorChannel(bad)
    with pytest.raises(ValueError):
        ecm.BurstErrorChannel(0.1, 1.0)


# --- security / robustness ---------------------------------------------------

@pytest.mark.parametrize("n,k", [(0, 0), (10, 10), (256, 10), (5, 0)])
def test_invalid_config(n, k):
    with pytest.raises(ecm.ConfigError):
        ecm.ReedSolomon(n, k)


def test_invalid_lengths_and_indices():
    rs = ecm.ReedSolomon(15, 11)
    with pytest.raises(ecm.InputLengthError):
        rs.encode(bytes(10))
    with pytest.raises(ecm.InputLengthError):
        rs.decode(bytes(14))
    with pytest.raises(ecm.ErasureIndexError):
        rs.decode(bytes(15), [15])
    with pytest.raises(ecm.ErasureIndexError):
        rs.decode(bytes(15), [-1])
    with pytest.raises(ecm.InputLengthError):
        rs.decode(bytes(15), list(range(16)))
    with pytest.raises(TypeError):
        rs.decode(bytes(15), ["1"])
    with pytest.raises(ecm.ConfigError):
        ecm.BurstCodec(31, 23, 0)
    with pytest.raises(ecm.ConfigError):
        ecm.BurstCodec(31, 23, ecm.MAX_DEPTH + 1)
    codec = ecm.BurstCodec(15, 11, 2)
    with pytest.raises(ecm.InputLengthError):
        codec.protect(bytes(codec.capacity + 1))


def test_oversize_input_rejected_before_native():
    with pytest.raises(ecm.InputLengthError):
        ecm.crc16(bytearray(ecm.MAX_INPUT_BYTES + 1))


def test_garbage_never_crashes():
    import random

    rng = random.Random(1234)
    rs = ecm.ReedSolomon(31, 23)
    codec = ecm.BurstCodec(31, 23, 3)
    for _ in range(2000):
        rx = bytes(rng.getrandbits(8) for _ in range(31))
        eras = [rng.randrange(31) for _ in range(rng.randrange(10))]
        for fn in (lambda: rs.decode(rx, eras), lambda: rs.decode_euclidean(rx)):
            try:
                res = fn()
                assert res.verified and rs.is_codeword(rs.encode(res.data))
            except ecm.EcmError:
                pass
        try:
            codec.recover(rx * 3)
        except ecm.EcmError:
            pass


def test_objects_are_immutable_and_thread_safe():
    rs = ecm.ReedSolomon(64, 48)
    with pytest.raises(AttributeError):
        rs.n = 10  # read-only property
    data = bytes(range(48))
    cw = rs.encode(data)
    errors = []

    def worker(seed: int) -> None:
        try:
            for i in range(300):
                rx = bytearray(cw)
                rx[(seed + i) % 64] ^= 0xA5
                assert rs.decode(rx).data == data
        except Exception as exc:  # pragma: no cover - reported below
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(s,)) for s in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors


def test_exception_hierarchy():
    for cls in (ecm.ConfigError, ecm.InputLengthError, ecm.ErasureIndexError, ecm.DecodeError):
        assert issubclass(cls, ecm.EcmError)
    assert isinstance(ecm.__version__, str)
