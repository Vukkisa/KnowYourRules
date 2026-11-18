"""Test helper: write a TINY synthetic GGUF file in the nomic-bert layout (random F16 weights, 2 layers, width 16) so the engine's
parsing, identity checks and maths can be tested offline without the real 262 MB model. Not a model of anything."""
import struct
from pathlib import Path

import numpy as np

from backend.nomic_local import ModelSpec

TINY = ModelSpec(name="nomic-embed-text-v1.5", arch="nomic-bert", layers=2, width=16, heads=2, pooling=1, vocab=57)
FFN = 24


def tokens(vocab=57):
    toks = ["[PAD]", "[UNK]", "[CLS]", "[SEP]", "[MASK]"]
    toks += ["▁" + c for c in "abcdefghijklmnopqrstuvwxyz"] + list("abcdefghijklmnopqrstuvwxyz")
    assert len(toks) == vocab
    return toks


def _s(x: str) -> bytes:
    b = x.encode()
    return struct.pack("<Q", len(b)) + b


def _kv(key, value):
    out = _s(key)
    if isinstance(value, str):
        return out + struct.pack("<I", 8) + _s(value)
    if isinstance(value, float):
        return out + struct.pack("<If", 6, value)
    if isinstance(value, list):
        return out + struct.pack("<IIQ", 9, 8, len(value)) + b"".join(_s(v) for v in value)
    return out + struct.pack("<II", 4, value)


def write(path, spec=TINY, seed=0, **meta_overrides):
    rng = np.random.default_rng(seed)
    D, F, V = spec.width, FFN, spec.vocab
    t = {"token_embd.weight": (V, D), "token_types.weight": (2, D), "token_embd_norm.weight": (D,), "token_embd_norm.bias": (D,)}
    for i in range(spec.layers):
        b = f"blk.{i}."
        t.update({b + "attn_qkv.weight": (3 * D, D), b + "attn_output.weight": (D, D), b + "ffn_up.weight": (F, D), b + "ffn_gate.weight": (F, D),
                  b + "ffn_down.weight": (D, F), b + "attn_output_norm.weight": (D,), b + "attn_output_norm.bias": (D,),
                  b + "layer_output_norm.weight": (D,), b + "layer_output_norm.bias": (D,)})
    meta = {"general.architecture": spec.arch, "general.name": spec.name, f"{spec.arch}.block_count": spec.layers,
            f"{spec.arch}.embedding_length": spec.width, f"{spec.arch}.attention.head_count": spec.heads, f"{spec.arch}.pooling_type": spec.pooling,
            f"{spec.arch}.attention.layer_norm_epsilon": 1e-12, f"{spec.arch}.rope.freq_base": 1000.0, "tokenizer.ggml.tokens": tokens(V)}
    meta.update(meta_overrides)
    arrays, infos, off = [], b"", 0
    for name, shape in t.items():
        a = (rng.standard_normal(shape) * (1.0 if name.endswith("norm.weight") else 0.3)).astype(np.float16)
        if name.endswith("norm.weight"):
            a = (np.ones(shape) + rng.standard_normal(shape) * 0.05).astype(np.float16)
        data = a.tobytes()
        infos += _s(name) + struct.pack("<I", len(shape)) + b"".join(struct.pack("<Q", d) for d in reversed(shape)) + struct.pack("<IQ", 1, off)
        pad = (-len(data)) % 32
        arrays.append(data + b"\0" * pad)
        off += len(data) + pad
    head = b"GGUF" + struct.pack("<IQQ", 3, len(t), len(meta)) + b"".join(_kv(k, v) for k, v in meta.items()) + infos
    head += b"\0" * ((-len(head)) % 32)
    Path(path).write_bytes(head + b"".join(arrays))
    return Path(path)
