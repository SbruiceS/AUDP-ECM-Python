"""Property-based tests (Hypothesis)."""

from hypothesis import given, settings
from hypothesis import strategies as st

import audp_ecm as ecm

CODES = [(7, 3), (15, 11), (31, 23), (64, 48), (255, 223)]


@st.composite
def rs_case(draw):
    n, k = draw(st.sampled_from(CODES))
    data = draw(st.binary(min_size=k, max_size=k))
    r = n - k
    s = draw(st.integers(0, r))
    e = draw(st.integers(0, (r - s) // 2))
    positions = draw(st.permutations(range(n)))[: e + s]
    values = draw(st.lists(st.integers(1, 255), min_size=e + s, max_size=e + s))
    return n, k, data, positions[:s], positions[s:], values


@settings(max_examples=300, deadline=None)
@given(rs_case())
def test_rs_corrects_within_budget(case):
    n, k, data, eras, errs, values = case
    rs = ecm.ReedSolomon(n, k)
    rx = bytearray(rs.encode(data))
    for p, v in zip(eras + errs, values):
        rx[p] ^= v
    res = rs.decode(rx, eras)
    assert res.data == data


@settings(max_examples=200, deadline=None)
@given(
    st.sampled_from([(15, 11), (31, 23), (64, 48)]),
    st.integers(1, 6),
    st.data(),
)
def test_burst_roundtrip_with_max_burst(code, depth, data):
    n, k = code
    codec = ecm.BurstCodec(n, k, depth)
    payload = data.draw(st.binary(max_size=codec.capacity))
    tx = bytearray(codec.protect(payload))
    burst = codec.burst_tolerance
    start = data.draw(st.integers(0, len(tx) - burst))
    for i in range(start, start + burst):
        tx[i] ^= 0x80 | (i & 0x7F)
    assert codec.recover(tx) == payload


@settings(max_examples=300, deadline=None)
@given(st.binary(max_size=4096))
def test_crc_roundtrip(data):
    assert ecm.verify_crc16(ecm.append_crc16(data)) == data
