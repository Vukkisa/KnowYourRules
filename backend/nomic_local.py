"""nomic-embed-text-v1.5 inside the server process: the SAME weights the index was built with, on CPU, with numpy only.

Why this exists: the index vectors live in the nomic-embed-text-v1.5 space. A query must be embedded by that exact model or retrieval
silently degrades. On a free host without Ollama, the only way to keep the index is to run the model in the process. Stage 7B.1 /
7B.2 measured this engine against Ollama: cosine >= 0.9999993 on 108 queries and on chunks stored in the real index, identical top-1
retrieval on 108/108 questions. This module is that engine made fit for production use:

  * the model file is identified before it is parsed: SHA-256 against the pin (mandatory in a cloud deployment), then the GGUF
    metadata (architecture, name, layers, width, heads, pooling, vocabulary size) against what nomic-embed-text-v1.5 is. Anything else
    is refused with a fixed message; nothing is substituted.
  * the model loads ONCE per process (the weights are memory-mapped, so a second worker would map the same pages but duplicate every
    activation: the deployment is one worker). `embed` is serialised by a lock: one text batch at a time bounds peak memory.
  * no network, no torch, no onnxruntime; numpy and tokenizers (already installed by chromadb).
  * the text is embedded exactly as given. The task prefix ("search_query: " / "search_document: ") is added by the caller
    (backend/rag_profiles.py), because it is part of the index's space; text without one is refused here, like the hosted adapter does.

Error messages never contain file paths.
"""
from __future__ import annotations

import hashlib
import mmap
import os
import struct
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

# SHA-256 of the F16 GGUF that Ollama serves as `nomic-embed-text:latest` (what built the index; measured in Stage 7B.1/7B.2).
KNOWN_MODEL_SHA256 = "970aa74c0a90ef7482477cf803618e776e173c007bf957f635f1015bfcfef0e6"
TASK_PREFIXES = ("search_query: ", "search_document: ")
MAX_TOKENS = 512            # queries are short; a bound keeps attention memory (heads x T x T) small however long the input is
_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_DTYPES = {0: np.float32, 1: np.float16}


class ModelError(RuntimeError):
    """The model file is missing, not the expected model, or unreadable. The message is fixed text (no paths)."""


@dataclass(frozen=True)
class ModelSpec:
    name: str = "nomic-embed-text-v1.5"
    arch: str = "nomic-bert"
    layers: int = 12
    width: int = 768
    heads: int = 12
    pooling: int = 1            # mean pooling
    vocab: int = 30522


NOMIC_SPEC = ModelSpec()


def file_sha256(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 22), b""):
            h.update(block)
    return h.hexdigest()


def buffer_sha256(buffer) -> str:
    """SHA-256 of a bytes-like object (e.g. an anonymous mmap) without copying it."""
    h = hashlib.sha256()
    view = memoryview(buffer).cast("B")
    for start in range(0, len(view), 1 << 22):
        h.update(view[start:start + (1 << 22)])
    return h.hexdigest()


# The model downloaded into memory by backend/vercel_runtime.py (a deployment with no writable room for the 262 MiB file). The runtime
# stores the verified buffer here once; EMBEDDING_MODEL_SOURCE=memory makes the provider build its engine from it. Nothing else sets it.
_MEMORY_MODEL = None


def set_memory_model(buffer) -> None:
    global _MEMORY_MODEL
    _MEMORY_MODEL = buffer


def get_memory_model():
    return _MEMORY_MODEL


class Gguf:
    """Read-only GGUF v2/v3 parser (F16/F32 tensors). Counts and lengths are bounded by the file size.
    `source` is a file path (memory-mapped read-only, closed by `close`) or a bytes-like buffer (owned by the caller, never closed here)."""

    def __init__(self, source):
        self._f = None
        if isinstance(source, (str, os.PathLike)):
            try:
                self._f = open(source, "rb")
                self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
            except (OSError, ValueError):
                raise ModelError("the model file cannot be opened") from None
        else:
            try:
                memoryview(source)
                self._mm = source
            except TypeError:
                raise ModelError("the model buffer cannot be read") from None
        self._size, self._p = len(self._mm), 0
        try:
            if self._mm[:4] != b"GGUF":
                raise ModelError("the model file is not a GGUF file")
            self._p = 4
            self.version = self._u("<I")
            if self.version not in (2, 3):
                raise ModelError("unsupported GGUF version")
            n_tensors, n_kv = self._u("<Q"), self._u("<Q")
            if n_tensors > 10_000 or n_kv > 10_000:
                raise ModelError("the model file header is implausible")
            self.meta = {}
            for _ in range(n_kv):
                key = self._str()
                self.meta[key] = self._value(self._u("<I"))
            self.tensors = {}
            for _ in range(n_tensors):
                name = self._str()
                nd = self._u("<I")
                if nd > 4:
                    raise ModelError("the model file header is implausible")
                dims = tuple(self._u("<Q") for _ in range(nd))
                ttype, off = self._u("<I"), self._u("<Q")
                self.tensors[name] = (dims, ttype, off)
            align = int(self.meta.get("general.alignment", 32))
            self._data0 = (self._p + align - 1) // align * align
        except ModelError:
            self.close()
            raise
        except (struct.error, UnicodeDecodeError, ValueError, OverflowError):
            self.close()
            raise ModelError("the model file is malformed") from None

    def close(self):
        if self._f is None:                    # a caller-owned buffer: the caller releases it
            return
        try:
            self._mm.close()
            self._f.close()
        except Exception:  # noqa: BLE001
            pass

    def _u(self, fmt):
        n = struct.calcsize(fmt)
        if self._p + n > self._size:
            raise ModelError("the model file is truncated")
        v = struct.unpack_from(fmt, self._mm, self._p)[0]
        self._p += n
        return v

    def _str(self):
        n = self._u("<Q")
        if n > (1 << 24) or self._p + n > self._size:
            raise ModelError("the model file is malformed")
        s = bytes(self._mm[self._p:self._p + n]).decode("utf-8")
        self._p += n
        return s

    def _value(self, t, depth=0):
        if t in _SCALARS:
            return self._u(_SCALARS[t])
        if t == 8:
            return self._str()
        if t == 9 and depth == 0:
            et, n = self._u("<I"), self._u("<Q")
            if n > 5_000_000:
                raise ModelError("the model file is malformed")
            return [self._value(et, 1) for _ in range(n)]
        raise ModelError("unsupported value in the model file")

    def raw(self, name):
        """Zero-copy view of a tensor in its stored dtype, shaped like torch weights ([out, in]). Pages load lazily."""
        if name not in self.tensors:
            raise ModelError("the model file lacks a tensor this model needs")
        dims, ttype, off = self.tensors[name]
        if ttype not in _DTYPES:
            raise ModelError("the model file stores a tensor type this engine does not read")
        count = int(np.prod(dims, dtype=np.int64))
        itemsize = np.dtype(_DTYPES[ttype]).itemsize
        if self._data0 + off + count * itemsize > self._size:
            raise ModelError("the model file is truncated")
        return np.frombuffer(self._mm, dtype=_DTYPES[ttype], count=count, offset=self._data0 + off).reshape(tuple(reversed(dims)))


def identity_problems(g: Gguf, spec: ModelSpec = NOMIC_SPEC) -> list:
    """Everything the GGUF metadata says about the model, compared with the model this index needs. Empty list = identical."""
    m, p = g.meta, spec.arch
    want = {"general.architecture": spec.arch, "general.name": spec.name, f"{p}.block_count": spec.layers, f"{p}.embedding_length": spec.width,
            f"{p}.attention.head_count": spec.heads, f"{p}.pooling_type": spec.pooling}
    out = [f"{k} is {m.get(k)!r}, expected {v!r}" for k, v in want.items() if m.get(k) != v]
    toks = m.get("tokenizer.ggml.tokens")
    if not isinstance(toks, list) or len(toks) != spec.vocab:
        out.append(f"vocabulary size is {len(toks) if isinstance(toks, list) else None}, expected {spec.vocab}")
    for k in (f"{p}.attention.layer_norm_epsilon", f"{p}.rope.freq_base"):
        if not isinstance(m.get(k), (int, float)):
            out.append(f"{k} is missing")
    return out


def build_tokenizer(g: Gguf, max_len: int = MAX_TOKENS):
    """BERT WordPiece from the GGUF vocabulary. llama.cpp stores word-initial pieces as "▁piece" and continuations without "##"."""
    from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors
    vocab = {}
    for i, t in enumerate(g.meta["tokenizer.ggml.tokens"]):
        if t.startswith("▁"):
            t = t[1:]
        elif not (t.startswith("[") and t.endswith("]")):
            t = "##" + t
        vocab.setdefault(t, i)
    if "[CLS]" not in vocab or "[SEP]" not in vocab or "[UNK]" not in vocab:
        raise ModelError("the vocabulary lacks the BERT special tokens")
    tok = Tokenizer(models.WordPiece(vocab, unk_token="[UNK]", max_input_chars_per_word=100))
    tok.normalizer = normalizers.BertNormalizer(clean_text=True, handle_chinese_chars=True, strip_accents=None, lowercase=True)
    tok.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tok.post_processor = processors.TemplateProcessing(single="[CLS] $A [SEP]", special_tokens=[("[CLS]", vocab["[CLS]"]), ("[SEP]", vocab["[SEP]"])])
    tok.enable_truncation(max_length=max_len)
    return tok


def _ln(x, w, b, eps):
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


class NomicEngine:
    """Loads and verifies the model ONCE (in __init__); `embed` returns unit-length float32 vectors."""

    def __init__(self, model_path, expected_sha256: str | None = None, spec: ModelSpec = NOMIC_SPEC, max_tokens: int = MAX_TOKENS, *, buffer=None):
        """`model_path` names the GGUF file; or pass `buffer` (bytes-like, model_path None) to run from memory. The pin is checked the same
        way in both cases, before anything is parsed. The engine keeps a reference to the buffer for as long as it lives."""
        if buffer is not None:
            if model_path is not None:
                raise ModelError("give either a model file or a model buffer, not both")
            if expected_sha256 and buffer_sha256(buffer) != expected_sha256.lower():
                raise ModelError("the model file does not match the pinned SHA-256: it is not the model the index was built with")
            source = self._buffer = buffer
        else:
            path = Path(model_path)
            if not path.is_file():
                raise ModelError("the model file does not exist")
            if expected_sha256:
                if file_sha256(path) != expected_sha256.lower():
                    raise ModelError("the model file does not match the pinned SHA-256: it is not the model the index was built with")
            source, self._buffer = path, None
        self.sha256_verified = bool(expected_sha256)
        g = self.g = Gguf(source)
        try:
            problems = identity_problems(g, spec)
            if problems:
                raise ModelError("the model file is not " + spec.name + ": " + "; ".join(problems[:3]))
            m = g.meta
            self.L, self.H, self.D = spec.layers, spec.heads, spec.width
            self.hd = self.D // self.H
            self.eps, self.base = float(m[f"{spec.arch}.attention.layer_norm_epsilon"]), float(m[f"{spec.arch}.rope.freq_base"])
            self.tok = build_tokenizer(g, max_tokens)
            self.emb = g.raw("token_embd.weight")
            if self.emb.shape != (spec.vocab, spec.width):
                raise ModelError("the embedding table has the wrong shape")
            self.tt = g.raw("token_types.weight")[0].astype(np.float32)
            self.enw, self.enb = g.raw("token_embd_norm.weight").astype(np.float32), g.raw("token_embd_norm.bias").astype(np.float32)
            self.blocks = []
            for i in range(self.L):
                b = f"blk.{i}."
                blk = {k: g.raw(b + v) for k, v in dict(qkv="attn_qkv.weight", o="attn_output.weight", up="ffn_up.weight", gate="ffn_gate.weight",
                                                        down="ffn_down.weight").items()}
                blk.update({k: g.raw(b + v).astype(np.float32) for k, v in dict(n1w="attn_output_norm.weight", n1b="attn_output_norm.bias",
                                                                                 n2w="layer_output_norm.weight", n2b="layer_output_norm.bias").items()})
                if blk["qkv"].shape[1] != self.D or blk["qkv"].shape[0] != 3 * self.D:
                    raise ModelError("an attention tensor has the wrong shape")
                self.blocks.append(blk)
        except ModelError:
            g.close()
            raise
        except (KeyError, ValueError, TypeError, IndexError):
            g.close()
            raise ModelError("the model file is malformed") from None
        self.dimensions = self.D
        self._lock = threading.Lock()

    @staticmethod
    def _rope(x, cos, sin):
        h = x.shape[-1] // 2
        return x * cos + np.concatenate((-x[..., h:], x[..., :h]), axis=-1) * sin

    def embed(self, texts) -> np.ndarray:
        texts = list(texts)
        for t in texts:
            if not isinstance(t, str) or not t.startswith(TASK_PREFIXES):
                raise ModelError("text must start with a task prefix (search_query: / search_document: )")
        with self._lock:                       # one batch at a time: bounded peak memory, one model, one process
            return self._embed(texts)

    def _embed(self, texts):
        encs = self.tok.encode_batch(texts)
        B, T = len(encs), max(len(e.ids) for e in encs)
        ids = np.zeros((B, T), dtype=np.int64)
        mask = np.zeros((B, T), dtype=np.float32)
        for i, e in enumerate(encs):
            ids[i, :len(e.ids)] = e.ids
            mask[i, :len(e.ids)] = 1
        H, hd = self.H, self.hd
        x = _ln(self.emb[ids].astype(np.float32) + self.tt, self.enw, self.enb, self.eps)
        ang = np.outer(np.arange(T, dtype=np.float32), 1.0 / (self.base ** (np.arange(0, hd, 2, dtype=np.float32) / hd)))
        cos, sin = np.tile(np.cos(ang), (1, 2)).astype(np.float32), np.tile(np.sin(ang), (1, 2)).astype(np.float32)
        neg = ((1.0 - mask)[:, None, None, :] * -1e9).astype(np.float32)
        mm = lambda a, w: a @ w.astype(np.float32).T  # noqa: E731
        scale = float(np.sqrt(hd))
        for b in self.blocks:
            q, k, v = (a.reshape(B, T, H, hd).transpose(0, 2, 1, 3) for a in np.split(mm(x, b["qkv"]), 3, axis=-1))
            q, k = self._rope(q, cos, sin), self._rope(k, cos, sin)
            s = q @ k.transpose(0, 1, 3, 2) / scale + neg
            s = np.exp(s - s.max(-1, keepdims=True))
            att = (s / s.sum(-1, keepdims=True)) @ v
            x = _ln(x + mm(att.transpose(0, 2, 1, 3).reshape(B, T, self.D), b["o"]), b["n1w"], b["n1b"], self.eps)
            h = mm(x, b["up"])
            gt = mm(x, b["gate"])
            x = _ln(x + mm(h * (gt / (1.0 + np.exp(-gt))), b["down"]), b["n2w"], b["n2b"], self.eps)
        pooled = (x * mask[..., None]).sum(1) / mask.sum(1)[:, None]
        return (pooled / np.linalg.norm(pooled, axis=1, keepdims=True)).astype(np.float32)
