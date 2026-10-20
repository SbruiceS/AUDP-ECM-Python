"""AUDP-ECM: error correction for unreliable telemetry links.

Reed–Solomon over GF(256), binary BCH, CRC-16/CCITT-FALSE and a
burst-resilient pipeline that interleaves across codewords.

This library corrects *channel noise*. It is not cryptography: CRC and
Reed–Solomon do not authenticate data. Use a MAC/AEAD for that.

All functions accept any bytes-like object (``bytes``, ``bytearray``,
``memoryview``, ...). Mutable inputs are copied first, so another thread
cannot change the buffer while the native code (which releases the GIL)
is reading it.
"""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence, Tuple, Union

from . import _native
from ._native import (
    MAX_DEPTH,
    MAX_INPUT_BYTES,
    BchCode,
    ConfigError,
    DecodeError,
    DecodeResult,
    EcmError,
    ErasureIndexError,
    InputLengthError,
)

__version__: str = _native.__version__

BytesLike = Union[bytes, bytearray, memoryview]

__all__ = [
    "__version__",
    "MAX_DEPTH",
    "MAX_INPUT_BYTES",
    "BytesLike",
    "EcmError",
    "ConfigError",
    "InputLengthError",
    "ErasureIndexError",
    "DecodeError",
    "DecodeResult",
    "ReedSolomon",
    "BurstCodec",
    "BchCode",
    "SymbolErrorChannel",
    "BurstErrorChannel",
    "ErasureChannel",
    "gf_mul",
    "gf_inv",
    "gf_pow",
    "crc16",
    "append_crc16",
    "verify_crc16",
    "interleave_codewords",
    "deinterleave_codewords",
    "mark_erasures",
]


def _as_bytes(data: BytesLike, name: str = "data") -> bytes:
    """Return an immutable ``bytes`` snapshot of a bytes-like object."""
    if isinstance(data, bytes):
        return data
    if isinstance(data, (bytearray, memoryview)):
        if isinstance(data, memoryview) and not data.c_contiguous:
            raise TypeError(f"{name}: memoryview must be C-contiguous")
        snapshot = bytes(data)
    elif isinstance(data, str):
        raise TypeError(f"{name}: expected bytes-like object, got str (encode it first)")
    else:
        try:
            snapshot = bytes(memoryview(data))
        except TypeError:
            raise TypeError(
                f"{name}: expected bytes-like object, got {type(data).__name__}"
            ) from None
    if len(snapshot) > MAX_INPUT_BYTES:
        raise InputLengthError(f"{name} too large ({len(snapshot)} > {MAX_INPUT_BYTES})")
    return snapshot


def _indices(values: Optional[Iterable[int]], name: str = "erasures") -> List[int]:
    if values is None:
        return []
    out: List[int] = []
    for v in values:
        if isinstance(v, bool) or not isinstance(v, int):
            raise TypeError(f"{name} must contain ints, got {type(v).__name__}")
        if v < 0:
            raise ErasureIndexError(f"{name} contains a negative index: {v}")
        out.append(v)
    return out


# --- GF(256) / CRC -----------------------------------------------------------

gf_mul = _native.gf_mul
gf_inv = _native.gf_inv
gf_pow = _native.gf_pow


def crc16(data: BytesLike) -> int:
    """CRC-16/CCITT-FALSE (detection only, not authentication)."""
    return _native.crc16(_as_bytes(data))


def append_crc16(data: BytesLike) -> bytes:
    """Return ``data`` followed by its big-endian CRC-16."""
    return _native.append_crc16(_as_bytes(data))


def verify_crc16(frame: BytesLike) -> bytes:
    """Verify and strip a trailing CRC-16; raises :class:`DecodeError` on mismatch."""
    return _native.verify_crc16(_as_bytes(frame, "frame"))


# --- Reed–Solomon ------------------------------------------------------------


class ReedSolomon:
    """Systematic RS(n, k) over GF(256); corrects 2·errors + erasures ≤ n − k.

    Immutable and safe to share between threads.
    """

    __slots__ = ("_rs",)

    def __init__(self, n: int, k: int) -> None:
        self._rs = _native.ReedSolomon(n, k)

    @property
    def n(self) -> int:
        return self._rs.n

    @property
    def k(self) -> int:
        return self._rs.k

    @property
    def t(self) -> int:
        """Unknown-error capability (n − k) // 2."""
        return self._rs.t

    def encode(self, data: BytesLike) -> bytes:
        """Encode exactly ``k`` bytes into an ``n``-byte codeword (parity first)."""
        return self._rs.encode(_as_bytes(data))

    def decode(self, received: BytesLike, erasures: Optional[Iterable[int]] = None) -> DecodeResult:
        """Decode ``n`` received bytes; ``erasures`` are known-bad positions."""
        return self._rs.decode(_as_bytes(received, "received"), _indices(erasures))

    def decode_euclidean(
        self, received: BytesLike, erasures: Optional[Iterable[int]] = None
    ) -> DecodeResult:
        """Same contract as :meth:`decode`, Euclidean key-equation solver."""
        return self._rs.decode_euclidean(_as_bytes(received, "received"), _indices(erasures))

    def syndromes(self, received: BytesLike) -> bytes:
        return self._rs.syndromes(_as_bytes(received, "received"))

    def is_codeword(self, word: BytesLike) -> bool:
        return self._rs.is_codeword(_as_bytes(word, "word"))

    def __repr__(self) -> str:
        return f"ReedSolomon(n={self.n}, k={self.k})"


class BurstCodec:
    """Length-framed, CRC-checked payload over ``depth`` interleaved RS(n, k) codewords.

    Corrects any contiguous burst of up to ``depth * t`` symbols and returns
    the exact payload.
    """

    __slots__ = ("_bc",)

    def __init__(self, n: int, k: int, depth: int) -> None:
        self._bc = _native.BurstCodec(n, k, depth)

    @staticmethod
    def depth_for(n: int, k: int, payload_len: int, burst_len: int) -> int:
        """Smallest depth that fits ``payload_len`` and survives ``burst_len``."""
        return _native.BurstCodec.depth_for(n, k, payload_len, burst_len)

    @classmethod
    def for_burst(cls, n: int, k: int, payload_len: int, burst_len: int) -> "BurstCodec":
        return cls(n, k, cls.depth_for(n, k, payload_len, burst_len))

    @property
    def depth(self) -> int:
        return self._bc.depth

    @property
    def capacity(self) -> int:
        return self._bc.capacity

    @property
    def encoded_len(self) -> int:
        return self._bc.encoded_len

    @property
    def burst_tolerance(self) -> int:
        return self._bc.burst_tolerance

    def protect(self, payload: BytesLike) -> bytes:
        return self._bc.protect(_as_bytes(payload, "payload"))

    def recover(self, received: BytesLike, erasures: Optional[Iterable[int]] = None) -> bytes:
        """``erasures`` index the transmitted stream."""
        return self._bc.recover(_as_bytes(received, "received"), _indices(erasures))

    def __repr__(self) -> str:
        return repr(self._bc)


def interleave_codewords(codewords: Sequence[BytesLike]) -> bytes:
    return _native.interleave_codewords([_as_bytes(c, "codeword") for c in codewords])


def deinterleave_codewords(data: BytesLike, depth: int) -> List[bytes]:
    return _native.deinterleave_codewords(_as_bytes(data), depth)


def mark_erasures(
    reliability: Sequence[float], threshold: float, max_erasures: Optional[int] = None
) -> List[int]:
    """Indices with reliability below ``threshold`` (bounded to the least reliable
    ``max_erasures`` if given; pass ``n - k`` to stay within the RS budget)."""
    return _native.mark_erasures([float(r) for r in reliability], float(threshold), max_erasures)


# --- Channel models (simulation / research) ----------------------------------


class SymbolErrorChannel:
    """i.i.d. symbol errors with probability ``p`` (deterministic per seed)."""

    __slots__ = ("_ch",)

    def __init__(self, p: float) -> None:
        self._ch = _native.SymbolErrorChannel(float(p))

    def corrupt(self, data: BytesLike, seed: int) -> bytes:
        return self._ch.corrupt(_as_bytes(data), seed)


class BurstErrorChannel:
    """Bursts start with ``p_start`` and continue with ``p_continue``."""

    __slots__ = ("_ch",)

    def __init__(self, p_start: float, p_continue: float) -> None:
        self._ch = _native.BurstErrorChannel(float(p_start), float(p_continue))

    @property
    def mean_burst_length(self) -> float:
        return self._ch.mean_burst_length

    def corrupt(self, data: BytesLike, seed: int) -> bytes:
        return self._ch.corrupt(_as_bytes(data), seed)


class ErasureChannel:
    """Each symbol erased with probability ``p``; returns (word, erasure indices)."""

    __slots__ = ("_ch",)

    def __init__(self, p: float) -> None:
        self._ch = _native.ErasureChannel(float(p))

    def corrupt(self, data: BytesLike, seed: int) -> Tuple[bytes, List[int]]:
        return self._ch.corrupt(_as_bytes(data), seed)
