//! Python bindings for AUDP-ECM.
//!
//! Security model:
//! - No `unsafe` in this crate; all memory handling is PyO3 + safe Rust.
//! - Every exposed class is `frozen` (immutable after construction), so
//!   objects are safe to share between threads, and the GIL is released
//!   during encode/decode.
//! - All parameters are validated here *before* calling core functions that
//!   would assert, so no Rust panic is reachable from valid-typed Python input.
//! - Input sizes are bounded (`MAX_INPUT_BYTES`, `MAX_DEPTH`) to prevent
//!   memory-exhaustion denial of service.

#![forbid(unsafe_code)]

use ecm_kernels::{
    k_burst_capacity, k_crc16, k_crc16_append, k_crc16_verify, k_deinterleave_codewords,
    k_gf_inv, k_gf_mul, k_gf_pow, k_interleave_codewords, k_interleave_depth_for_burst,
    k_mark_erasures, k_mark_erasures_bounded, k_pipeline_protect_burst, k_pipeline_recover_burst,
    k_rs_decode, k_rs_decode_euclidean_erasures, k_rs_encode, k_rs_syndromes, Bch, EcError,
    ReedSolomon, RsConfig,
};
use ecm_probabilistic::{BurstChannel, ErasureChannel, SymbolErrorChannel};
use pyo3::create_exception;
use pyo3::exceptions::{PyException, PyValueError};
use pyo3::prelude::*;
use pyo3::types::PyBytes;

/// Upper bound on any single byte/element input (16 MiB).
const MAX_INPUT_BYTES: usize = 16 * 1024 * 1024;
/// Upper bound on burst interleave depth (matches the C ABI).
const MAX_DEPTH: usize = 4096;

create_exception!(_native, EcmError, PyException, "Base class for AUDP-ECM errors.");
create_exception!(_native, ConfigError, EcmError, "Invalid code parameters.");
create_exception!(_native, InputLengthError, EcmError, "Input has the wrong length or is too large.");
create_exception!(_native, ErasureIndexError, EcmError, "Erasure index out of range.");
create_exception!(_native, DecodeError, EcmError, "Too many errors, or the result failed verification.");

fn to_py(e: EcError) -> PyErr {
    match e {
        EcError::InvalidConfig => ConfigError::new_err("invalid code configuration"),
        EcError::InvalidInputLength => InputLengthError::new_err("input length does not match the code"),
        EcError::InvalidErasureIndex => ErasureIndexError::new_err("erasure index out of range"),
        EcError::DecodingFailed => DecodeError::new_err("decoding failed: errors exceed capability or verification failed"),
        EcError::InternalError => EcmError::new_err("internal error"),
    }
}

fn core_err(e: EcError) -> PyErr {
    to_py(e)
}

fn check_len(len: usize, what: &str) -> PyResult<()> {
    if len > MAX_INPUT_BYTES {
        return Err(InputLengthError::new_err(format!(
            "{what} too large ({len} > {MAX_INPUT_BYTES})"
        )));
    }
    Ok(())
}

fn check_prob(p: f64, name: &str, upper_inclusive: bool) -> PyResult<()> {
    let ok = p.is_finite() && p >= 0.0 && if upper_inclusive { p <= 1.0 } else { p < 1.0 };
    if !ok {
        let range = if upper_inclusive { "[0, 1]" } else { "[0, 1)" };
        return Err(PyValueError::new_err(format!("{name} must be in {range}, got {p}")));
    }
    Ok(())
}

fn check_depth(depth: usize) -> PyResult<()> {
    if depth == 0 || depth > MAX_DEPTH {
        return Err(ConfigError::new_err(format!("depth must be in 1..={MAX_DEPTH}, got {depth}")));
    }
    Ok(())
}

fn new_rs(n: usize, k: usize) -> PyResult<ReedSolomon> {
    RsConfig::new(n, k)
        .and_then(ReedSolomon::new)
        .map_err(|_| ConfigError::new_err(format!("invalid RS({n}, {k}): need 0 < k < n <= 255")))
}

// ---------------------------------------------------------------------------
// GF(256) and CRC
// ---------------------------------------------------------------------------

/// Multiply in GF(256) (irreducible 0x11D).
#[pyfunction]
fn gf_mul(a: u8, b: u8) -> u8 {
    k_gf_mul(a, b)
}

/// Multiplicative inverse in GF(256). Raises ValueError for 0.
#[pyfunction]
fn gf_inv(a: u8) -> PyResult<u8> {
    k_gf_inv(a).ok_or_else(|| PyValueError::new_err("0 has no inverse in GF(256)"))
}

/// a**e in GF(256).
#[pyfunction]
fn gf_pow(a: u8, e: u32) -> u8 {
    k_gf_pow(a, e)
}

/// CRC-16/CCITT-FALSE (poly 0x1021, init 0xFFFF). Detection only, not authentication.
#[pyfunction]
fn crc16(data: &[u8]) -> PyResult<u16> {
    check_len(data.len(), "data")?;
    Ok(k_crc16(data))
}

/// Return data + big-endian CRC-16.
#[pyfunction]
fn append_crc16<'py>(py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    check_len(data.len(), "data")?;
    Ok(PyBytes::new(py, &k_crc16_append(data)))
}

/// Verify and strip a trailing CRC-16. Raises DecodeError on mismatch.
#[pyfunction]
fn verify_crc16<'py>(py: Python<'py>, frame: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
    check_len(frame.len(), "frame")?;
    match k_crc16_verify(frame) {
        Ok(body) => Ok(PyBytes::new(py, body)),
        Err(ecm_core::EcError::InvalidInputLength) => {
            Err(InputLengthError::new_err("frame shorter than 2 bytes"))
        }
        Err(_) => Err(DecodeError::new_err("CRC mismatch")),
    }
}

// ---------------------------------------------------------------------------
// Reed–Solomon
// ---------------------------------------------------------------------------

/// Result of a successful Reed–Solomon decode.
#[pyclass(frozen, name = "DecodeResult", module = "audp_ecm._native", get_all)]
struct PyDecodeResult {
    /// Recovered data (k bytes).
    data: Py<PyBytes>,
    /// Unknown symbol errors corrected.
    corrected_symbols: usize,
    /// Distinct erasures supplied.
    erasures: usize,
    /// True when the corrected word is a valid codeword.
    verified: bool,
}

#[pymethods]
impl PyDecodeResult {
    fn __repr__(&self, py: Python<'_>) -> String {
        format!(
            "DecodeResult(len(data)={}, corrected_symbols={}, erasures={}, verified={})",
            self.data.bind(py).as_bytes().len(),
            self.corrected_symbols,
            self.erasures,
            self.verified
        )
    }
}

fn decode_result(py: Python<'_>, r: ecm_kernels::DecodeResult) -> PyResult<PyDecodeResult> {
    if !r.correction_verified {
        return Err(DecodeError::new_err("decoded word failed verification"));
    }
    Ok(PyDecodeResult {
        data: PyBytes::new(py, &r.corrected_data).unbind(),
        corrected_symbols: r.corrected_symbols,
        erasures: r.detected_erasures,
        verified: r.correction_verified,
    })
}

/// Systematic Reed–Solomon code RS(n, k) over GF(256).
///
/// Corrects e unknown symbol errors and s known erasures when 2e + s <= n - k.
/// Instances are immutable and thread-safe.
#[pyclass(frozen, name = "ReedSolomon", module = "audp_ecm._native")]
struct PyReedSolomon {
    rs: ReedSolomon,
}

#[pymethods]
impl PyReedSolomon {
    #[new]
    fn py_new(n: usize, k: usize) -> PyResult<Self> {
        Ok(Self { rs: new_rs(n, k)? })
    }

    /// Codeword length.
    #[getter]
    fn n(&self) -> usize {
        self.rs.config().n
    }

    /// Data length.
    #[getter]
    fn k(&self) -> usize {
        self.rs.config().k
    }

    /// Error-correction capability t = (n - k) // 2.
    #[getter]
    fn t(&self) -> usize {
        self.rs.config().error_correction_capability()
    }

    /// Encode exactly k data bytes into an n-byte codeword (parity first).
    fn encode<'py>(&self, py: Python<'py>, data: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
        let rs: &ReedSolomon = &self.rs;
        let cw = py.detach(|| k_rs_encode(rs, data)).map_err(core_err)?;
        Ok(PyBytes::new(py, &cw))
    }

    /// Decode n received bytes (Berlekamp–Massey). `erasures` are known-bad positions.
    #[pyo3(signature = (received, erasures = Vec::new()))]
    fn decode(&self, py: Python<'_>, received: &[u8], erasures: Vec<usize>) -> PyResult<PyDecodeResult> {
        if erasures.len() > self.rs.config().n {
            return Err(InputLengthError::new_err("more erasures than symbols"));
        }
        let rs: &ReedSolomon = &self.rs;
        let r = py.detach(|| k_rs_decode(rs, received, &erasures)).map_err(core_err)?;
        decode_result(py, r)
    }

    /// Decode using the Euclidean key-equation solver (same contract as `decode`).
    #[pyo3(signature = (received, erasures = Vec::new()))]
    fn decode_euclidean(&self, py: Python<'_>, received: &[u8], erasures: Vec<usize>) -> PyResult<PyDecodeResult> {
        if erasures.len() > self.rs.config().n {
            return Err(InputLengthError::new_err("more erasures than symbols"));
        }
        let rs: &ReedSolomon = &self.rs;
        let r = py
            .detach(|| k_rs_decode_euclidean_erasures(rs, received, &erasures))
            .map_err(core_err)?;
        decode_result(py, r)
    }

    /// The n - k syndromes of a received word (all zero ⇔ codeword).
    fn syndromes<'py>(&self, py: Python<'py>, received: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
        let s = k_rs_syndromes(&self.rs, received).map_err(core_err)?;
        let bytes: Vec<u8> = s.iter().map(|g| g.0).collect();
        Ok(PyBytes::new(py, &bytes))
    }

    /// True if `word` is a valid codeword.
    fn is_codeword(&self, word: &[u8]) -> PyResult<bool> {
        let s = k_rs_syndromes(&self.rs, word).map_err(core_err)?;
        Ok(s.iter().all(|g| g.0 == 0))
    }

    fn __repr__(&self) -> String {
        format!("ReedSolomon(n={}, k={})", self.n(), self.k())
    }
}

// ---------------------------------------------------------------------------
// Burst pipeline
// ---------------------------------------------------------------------------

/// Burst-resilient codec: len ‖ payload ‖ CRC-16 over `depth` RS(n, k)
/// codewords interleaved across codewords. Any contiguous burst of up to
/// depth·t symbols is corrected and `recover` returns the exact payload.
#[pyclass(frozen, module = "audp_ecm._native")]
struct BurstCodec {
    rs: ReedSolomon,
    depth: usize,
}

#[pymethods]
impl BurstCodec {
    #[new]
    fn py_new(n: usize, k: usize, depth: usize) -> PyResult<Self> {
        check_depth(depth)?;
        Ok(Self { rs: new_rs(n, k)?, depth })
    }

    /// Smallest depth that survives a `burst_len`-symbol burst and fits `payload_len` bytes.
    #[staticmethod]
    fn depth_for(n: usize, k: usize, payload_len: usize, burst_len: usize) -> PyResult<usize> {
        let rs = new_rs(n, k)?;
        let t = rs.config().error_correction_capability();
        let mut depth = k_interleave_depth_for_burst(burst_len, t)
            .ok_or_else(|| ConfigError::new_err("code has t = 0"))?;
        while k_burst_capacity(&rs, depth) < payload_len {
            depth += 1;
            if depth > MAX_DEPTH {
                return Err(InputLengthError::new_err("payload too large for any allowed depth"));
            }
        }
        if depth > MAX_DEPTH {
            return Err(ConfigError::new_err("burst too long for any allowed depth"));
        }
        Ok(depth)
    }

    #[getter]
    fn depth(&self) -> usize {
        self.depth
    }

    /// Maximum payload bytes.
    #[getter]
    fn capacity(&self) -> usize {
        k_burst_capacity(&self.rs, self.depth).min(u16::MAX as usize)
    }

    /// Transmitted length n·depth.
    #[getter]
    fn encoded_len(&self) -> usize {
        self.rs.config().n * self.depth
    }

    /// Longest contiguous burst guaranteed correctable (depth·t).
    #[getter]
    fn burst_tolerance(&self) -> usize {
        self.depth * self.rs.config().error_correction_capability()
    }

    fn protect<'py>(&self, py: Python<'py>, payload: &[u8]) -> PyResult<Bound<'py, PyBytes>> {
        if payload.len() > self.capacity() {
            return Err(InputLengthError::new_err(format!(
                "payload {} bytes exceeds capacity {}",
                payload.len(),
                self.capacity()
            )));
        }
        let (rs, depth) = (&self.rs, self.depth);
        let tx = py.detach(|| k_pipeline_protect_burst(rs, payload, depth)).map_err(core_err)?;
        Ok(PyBytes::new(py, &tx))
    }

    /// `erasures` index the transmitted stream.
    #[pyo3(signature = (received, erasures = Vec::new()))]
    fn recover<'py>(&self, py: Python<'py>, received: &[u8], erasures: Vec<usize>) -> PyResult<Bound<'py, PyBytes>> {
        if erasures.len() > self.encoded_len() {
            return Err(InputLengthError::new_err("more erasures than symbols"));
        }
        let (rs, depth) = (&self.rs, self.depth);
        let p = py
            .detach(|| k_pipeline_recover_burst(rs, received, depth, &erasures))
            .map_err(core_err)?;
        Ok(PyBytes::new(py, &p))
    }

    fn __repr__(&self) -> String {
        format!(
            "BurstCodec(n={}, k={}, depth={})",
            self.rs.config().n,
            self.rs.config().k,
            self.depth
        )
    }
}

/// Interleave equal-length codewords: symbol j of codeword i → j*depth + i.
#[pyfunction]
fn interleave_codewords<'py>(py: Python<'py>, codewords: Vec<Vec<u8>>) -> PyResult<Bound<'py, PyBytes>> {
    let total: usize = codewords.iter().map(Vec::len).sum();
    check_len(total, "codewords")?;
    let out = k_interleave_codewords(&codewords)
        .map_err(|_| InputLengthError::new_err("need >= 1 codeword, all of equal length"))?;
    Ok(PyBytes::new(py, &out))
}

/// Inverse of `interleave_codewords`.
#[pyfunction]
fn deinterleave_codewords<'py>(py: Python<'py>, data: &[u8], depth: usize) -> PyResult<Vec<Bound<'py, PyBytes>>> {
    check_len(data.len(), "data")?;
    let cws = k_deinterleave_codewords(data, depth)
        .map_err(|_| InputLengthError::new_err("depth must be > 0 and divide len(data)"))?;
    Ok(cws.iter().map(|c| PyBytes::new(py, c)).collect())
}

// ---------------------------------------------------------------------------
// BCH
// ---------------------------------------------------------------------------

/// Binary BCH code (bit-level), correcting up to t bit errors.
#[pyclass(frozen, module = "audp_ecm._native")]
struct BchCode {
    bch: Bch,
}

#[pymethods]
impl BchCode {
    #[new]
    fn py_new(n: usize, t: usize) -> PyResult<Self> {
        if n > 1 << 16 {
            return Err(ConfigError::new_err("BCH length too large"));
        }
        Bch::new(n, t).map(|bch| Self { bch }).map_err(core_err)
    }

    #[getter]
    fn n(&self) -> usize {
        self.bch.config().n
    }

    #[getter]
    fn k(&self) -> usize {
        self.bch.config().k
    }

    #[getter]
    fn t(&self) -> usize {
        self.bch.config().t
    }

    fn encode(&self, data_bits: Vec<bool>) -> PyResult<Vec<bool>> {
        self.bch.encode_bits(&data_bits).map_err(core_err)
    }

    fn decode(&self, received_bits: Vec<bool>) -> PyResult<Vec<bool>> {
        self.bch.decode_bits(&received_bits).map_err(core_err)
    }

    fn __repr__(&self) -> String {
        format!("BchCode(n={}, k={}, t={})", self.n(), self.k(), self.t())
    }
}

// ---------------------------------------------------------------------------
// Soft information and channel models (simulation / research)
// ---------------------------------------------------------------------------

/// Indices with reliability < threshold; optionally keep only the
/// `max_erasures` least reliable (use n - k to stay within the RS budget).
#[pyfunction]
#[pyo3(signature = (reliability, threshold, max_erasures = None))]
fn mark_erasures(reliability: Vec<f64>, threshold: f64, max_erasures: Option<usize>) -> PyResult<Vec<usize>> {
    check_len(reliability.len(), "reliability")?;
    if threshold.is_nan() {
        return Err(PyValueError::new_err("threshold must not be NaN"));
    }
    Ok(match max_erasures {
        Some(m) => k_mark_erasures_bounded(&reliability, threshold, m),
        None => k_mark_erasures(&reliability, threshold),
    })
}

/// i.i.d. symbol errors with probability p (deterministic for a given seed).
#[pyclass(frozen, name = "SymbolErrorChannel", module = "audp_ecm._native")]
struct PySymbolErrorChannel {
    inner: SymbolErrorChannel,
}

#[pymethods]
impl PySymbolErrorChannel {
    #[new]
    fn py_new(p: f64) -> PyResult<Self> {
        check_prob(p, "p", true)?;
        Ok(Self { inner: SymbolErrorChannel::new(p) })
    }

    #[getter]
    fn p(&self) -> f64 {
        self.inner.p
    }

    fn corrupt<'py>(&self, py: Python<'py>, data: &[u8], seed: u64) -> PyResult<Bound<'py, PyBytes>> {
        check_len(data.len(), "data")?;
        Ok(PyBytes::new(py, &self.inner.corrupt(data, seed)))
    }
}

/// Bursty channel: a burst starts with p_start, continues with p_continue.
#[pyclass(frozen, name = "BurstErrorChannel", module = "audp_ecm._native")]
struct BurstErrorChannel {
    inner: BurstChannel,
}

#[pymethods]
impl BurstErrorChannel {
    #[new]
    fn py_new(p_start: f64, p_continue: f64) -> PyResult<Self> {
        check_prob(p_start, "p_start", false)?;
        check_prob(p_continue, "p_continue", false)?;
        Ok(Self { inner: BurstChannel::new(p_start, p_continue) })
    }

    /// Mean burst length 1 / (1 - p_continue).
    #[getter]
    fn mean_burst_length(&self) -> f64 {
        1.0 / (1.0 - self.inner.p_continue)
    }

    fn corrupt<'py>(&self, py: Python<'py>, data: &[u8], seed: u64) -> PyResult<Bound<'py, PyBytes>> {
        check_len(data.len(), "data")?;
        Ok(PyBytes::new(py, &self.inner.corrupt(data, seed)))
    }
}

/// Each symbol erased with probability p; returns (word, erasure_indices).
#[pyclass(frozen, name = "ErasureChannel", module = "audp_ecm._native")]
struct ErasureChannelModel {
    inner: ErasureChannel,
}

#[pymethods]
impl ErasureChannelModel {
    #[new]
    fn py_new(p: f64) -> PyResult<Self> {
        check_prob(p, "p", true)?;
        Ok(Self { inner: ErasureChannel::new(p) })
    }

    fn corrupt<'py>(&self, py: Python<'py>, data: &[u8], seed: u64) -> PyResult<(Bound<'py, PyBytes>, Vec<usize>)> {
        check_len(data.len(), "data")?;
        let (w, e) = self.inner.corrupt(data, seed);
        Ok((PyBytes::new(py, &w), e))
    }
}

// ---------------------------------------------------------------------------
// Module
// ---------------------------------------------------------------------------

#[pymodule]
fn _native(m: &Bound<'_, PyModule>) -> PyResult<()> {
    let py = m.py();
    m.add("__version__", env!("CARGO_PKG_VERSION"))?;
    m.add("MAX_INPUT_BYTES", MAX_INPUT_BYTES)?;
    m.add("MAX_DEPTH", MAX_DEPTH)?;
    m.add("EcmError", py.get_type::<EcmError>())?;
    m.add("ConfigError", py.get_type::<ConfigError>())?;
    m.add("InputLengthError", py.get_type::<InputLengthError>())?;
    m.add("ErasureIndexError", py.get_type::<ErasureIndexError>())?;
    m.add("DecodeError", py.get_type::<DecodeError>())?;
    m.add_function(wrap_pyfunction!(gf_mul, m)?)?;
    m.add_function(wrap_pyfunction!(gf_inv, m)?)?;
    m.add_function(wrap_pyfunction!(gf_pow, m)?)?;
    m.add_function(wrap_pyfunction!(crc16, m)?)?;
    m.add_function(wrap_pyfunction!(append_crc16, m)?)?;
    m.add_function(wrap_pyfunction!(verify_crc16, m)?)?;
    m.add_function(wrap_pyfunction!(interleave_codewords, m)?)?;
    m.add_function(wrap_pyfunction!(deinterleave_codewords, m)?)?;
    m.add_function(wrap_pyfunction!(mark_erasures, m)?)?;
    m.add_class::<PyReedSolomon>()?;
    m.add_class::<PyDecodeResult>()?;
    m.add_class::<BurstCodec>()?;
    m.add_class::<BchCode>()?;
    m.add_class::<PySymbolErrorChannel>()?;
    m.add_class::<BurstErrorChannel>()?;
    m.add_class::<ErasureChannelModel>()?;
    Ok(())
}
