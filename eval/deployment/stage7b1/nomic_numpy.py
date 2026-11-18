"""Pure-numpy CPU inference of nomic-embed-text-v1.5 straight from the F16 GGUF weights (mmap, zero-copy; one matrix is upcast to
float32 at a time). Imports numpy + tokenizers only (no torch, no onnxruntime). Stage 7B.1 feasibility study; not used by production code.
Same maths as nomic_runtime.NomicTorch, which agrees with Ollama to cosine >= 0.9999996 on the reference set."""
import numpy as np
from tokenizers import Tokenizer

from gguf_reader import Gguf


def _ln(x, w, b, eps):
    mu = x.mean(-1, keepdims=True)
    var = ((x - mu) ** 2).mean(-1, keepdims=True)
    return (x - mu) / np.sqrt(var + eps) * w + b


class NomicNumpy:
    def __init__(self, gguf_path, tokenizer_path):
        g = self.g = Gguf(gguf_path)
        m = g.meta
        self.L, self.H, self.D = int(m["nomic-bert.block_count"]), int(m["nomic-bert.attention.head_count"]), int(m["nomic-bert.embedding_length"])
        self.eps, self.base = float(m["nomic-bert.attention.layer_norm_epsilon"]), float(m["nomic-bert.rope.freq_base"])
        self.tok = Tokenizer.from_file(tokenizer_path)
        self.emb = g.raw("token_embd.weight")
        self.tt = g.raw("token_types.weight")[0].astype(np.float32)
        self.enw, self.enb = g.raw("token_embd_norm.weight").astype(np.float32), g.raw("token_embd_norm.bias").astype(np.float32)
        self.blocks = []
        for i in range(self.L):
            b = f"blk.{i}."
            self.blocks.append({k: g.raw(b + v) for k, v in dict(qkv="attn_qkv.weight", o="attn_output.weight", up="ffn_up.weight", gate="ffn_gate.weight",
                                                                 down="ffn_down.weight").items()})
            self.blocks[-1].update({k: g.raw(b + v).astype(np.float32) for k, v in dict(n1w="attn_output_norm.weight", n1b="attn_output_norm.bias",
                                                                                         n2w="layer_output_norm.weight", n2b="layer_output_norm.bias").items()})

    def _rope(self, x, cos, sin):
        h = x.shape[-1] // 2
        return x * cos + np.concatenate((-x[..., h:], x[..., :h]), axis=-1) * sin

    def embed(self, texts):
        encs = self.tok.encode_batch(list(texts))
        B, T = len(encs), max(len(e.ids) for e in encs)
        ids = np.zeros((B, T), dtype=np.int64)
        mask = np.zeros((B, T), dtype=np.float32)
        for i, e in enumerate(encs):
            ids[i, :len(e.ids)] = e.ids
            mask[i, :len(e.ids)] = 1
        x = _ln(self.emb[ids].astype(np.float32) + self.tt, self.enw, self.enb, self.eps)
        ang = np.outer(np.arange(T, dtype=np.float32), 1.0 / (self.base ** (np.arange(0, 64, 2, dtype=np.float32) / 64.0)))
        cos, sin = np.tile(np.cos(ang), (1, 2)).astype(np.float32), np.tile(np.sin(ang), (1, 2)).astype(np.float32)
        neg = ((1.0 - mask)[:, None, None, :] * -1e9).astype(np.float32)
        mm = lambda a, w: a @ w.astype(np.float32).T
        for b in self.blocks:
            q, k, v = (a.reshape(B, T, self.H, 64).transpose(0, 2, 1, 3) for a in np.split(mm(x, b["qkv"]), 3, axis=-1))
            q, k = self._rope(q, cos, sin), self._rope(k, cos, sin)
            s = q @ k.transpose(0, 1, 3, 2) / 8.0 + neg
            s = np.exp(s - s.max(-1, keepdims=True))
            att = (s / s.sum(-1, keepdims=True)) @ v
            x = _ln(x + mm(att.transpose(0, 2, 1, 3).reshape(B, T, self.D), b["o"]), b["n1w"], b["n1b"], self.eps)
            h = mm(x, b["up"])
            gt = mm(x, b["gate"])
            x = _ln(x + mm(h * (gt / (1.0 + np.exp(-gt))), b["down"]), b["n2w"], b["n2b"], self.eps)
        pooled = (x * mask[..., None]).sum(1) / mask.sum(1)[:, None]
        return pooled / np.linalg.norm(pooled, axis=1, keepdims=True)
