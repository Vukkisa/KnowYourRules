"""Minimal read-only GGUF (v2/v3) parser, stdlib + numpy only. Used to read the exact nomic-embed-text weights that Ollama
already holds locally (no download, no package install). Supports F32/F16 tensors, which is all this model uses."""
import json
import mmap
import struct
from pathlib import Path

import numpy as np

_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i", 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}
_TENSOR_DTYPES = {0: np.float32, 1: np.float16}


class Gguf:
    def __init__(self, path):
        self.path = Path(path)
        self._f = open(self.path, "rb")
        self._mm = mmap.mmap(self._f.fileno(), 0, access=mmap.ACCESS_READ)
        self._p = 0
        if self._mm[:4] != b"GGUF":
            raise ValueError("not a GGUF file")
        self._p = 4
        self.version = self._u("<I")
        n_tensors = self._u("<Q")
        n_kv = self._u("<Q")
        self.meta = {}
        for _ in range(n_kv):
            key = self._str()
            self.meta[key] = self._value(self._u("<I"))
        self.tensors = {}
        for _ in range(n_tensors):
            name = self._str()
            nd = self._u("<I")
            dims = [self._u("<Q") for _ in range(nd)]
            ttype = self._u("<I")
            off = self._u("<Q")
            self.tensors[name] = (tuple(dims), ttype, off)
        align = int(self.meta.get("general.alignment", 32))
        self._data0 = (self._p + align - 1) // align * align

    def _u(self, fmt):
        n = struct.calcsize(fmt)
        v = struct.unpack_from(fmt, self._mm, self._p)[0]
        self._p += n
        return v

    def _str(self):
        n = self._u("<Q")
        s = bytes(self._mm[self._p:self._p + n]).decode("utf-8")
        self._p += n
        return s

    def _value(self, t):
        if t in _SCALARS:
            return self._u(_SCALARS[t])
        if t == 8:
            return self._str()
        if t == 9:
            et = self._u("<I")
            n = self._u("<Q")
            return [self._value(et) for _ in range(n)]
        raise ValueError(f"unsupported GGUF value type {t}")

    def tensor(self, name, dtype=np.float32):
        dims, ttype, off = self.tensors[name]
        if ttype not in _TENSOR_DTYPES:
            raise ValueError(f"{name}: unsupported tensor type {ttype}")
        src = _TENSOR_DTYPES[ttype]
        count = int(np.prod(dims))
        a = np.frombuffer(self._mm, dtype=src, count=count, offset=self._data0 + off)
        return a.reshape(tuple(reversed(dims))).astype(dtype)   # GGUF dims are fastest-first

    def raw(self, name):
        """Zero-copy view of a tensor in its stored dtype (F16/F32), shaped [..., in] like torch weights. Pages load lazily (mmap)."""
        dims, ttype, off = self.tensors[name]
        if ttype not in _TENSOR_DTYPES:
            raise ValueError(f"{name}: unsupported tensor type {ttype}")
        a = np.frombuffer(self._mm, dtype=_TENSOR_DTYPES[ttype], count=int(np.prod(dims)), offset=self._data0 + off)
        return a.reshape(tuple(reversed(dims)))

    def tensor_types(self):
        return sorted({t for _, t, _ in self.tensors.values()})


def ollama_blob(model="nomic-embed-text", tag="latest"):
    root = Path.home() / ".ollama" / "models"
    man = json.loads((root / "manifests/registry.ollama.ai/library" / model / tag).read_text())
    layer = next(l for l in man["layers"] if l["mediaType"].endswith("image.model"))
    return root / "blobs" / layer["digest"].replace(":", "-"), layer["digest"]


if __name__ == "__main__":
    path, digest = ollama_blob()
    g = Gguf(path)
    print("blob", digest, "version", g.version, "tensors", len(g.tensors), "tensor types", g.tensor_types())
    for k, v in g.meta.items():
        if k.startswith("tokenizer.ggml.") and isinstance(v, list):
            print(k, f"[{len(v)} items] first:", v[:5])
        else:
            print(k, v)
    for n in list(g.tensors)[:20]:
        print(n, g.tensors[n][0])
