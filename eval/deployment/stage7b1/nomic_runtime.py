"""Independent re-implementation of nomic-embed-text-v1.5 (arch `nomic-bert`) from the exact GGUF weights Ollama holds locally.

Purpose: Stage 7B.1 feasibility study. Can the SAME weights run on CPU in the cloud backend and agree with Ollama?
Nothing here is imported by the production code. Weights are read from Ollama's blob (no download).

Architecture (from the GGUF metadata, verified numerically against Ollama in compare_ollama.py):
  tokens -> word embedding + token-type-0 embedding -> LayerNorm
  12 x [ x = LN(x + Wo . attn(rope(q), rope(k), v)) ; x = LN(x + down(up(x) * silu(gate(x)))) ]   (post-norm, no biases, SwiGLU)
  rotary embeddings (NeoX / rotate-half layout, base 1000, full head dim), bidirectional attention, no position table
  mean pooling over all tokens (CLS and SEP included), then L2 normalisation (Ollama /api/embed does this).
"""
import numpy as np
import torch
import torch.nn.functional as F
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

from gguf_reader import Gguf, ollama_blob


def build_tokenizer(g: Gguf, max_len=2048) -> Tokenizer:
    # llama.cpp stores BERT pieces as: word-initial -> "\u2581piece", continuation -> "piece" (no "##"); specials stay "[...]".
    # Convert back to the original WordPiece convention.
    vocab = {}
    for i, t in enumerate(g.meta["tokenizer.ggml.tokens"]):
        if t.startswith("\u2581"):
            t = t[1:]
        elif not (t.startswith("[") and t.endswith("]")):
            t = "##" + t
        vocab.setdefault(t, i)
    tok = Tokenizer(models.WordPiece(vocab, unk_token="[UNK]", max_input_chars_per_word=100))
    tok.normalizer = normalizers.BertNormalizer(clean_text=True, handle_chinese_chars=True, strip_accents=None, lowercase=True)
    tok.pre_tokenizer = pre_tokenizers.BertPreTokenizer()
    tok.post_processor = processors.TemplateProcessing(single="[CLS] $A [SEP]", special_tokens=[("[CLS]", vocab["[CLS]"]), ("[SEP]", vocab["[SEP]"])])
    tok.enable_truncation(max_length=max_len)
    return tok


class NomicTorch(torch.nn.Module):
    """Reference implementation. dtype float32 unless told otherwise."""

    def __init__(self, g: Gguf, dtype=torch.float32):
        super().__init__()
        m = g.meta
        self.L = int(m["nomic-bert.block_count"])
        self.H = int(m["nomic-bert.attention.head_count"])
        self.D = int(m["nomic-bert.embedding_length"])
        self.eps = float(m["nomic-bert.attention.layer_norm_epsilon"])
        self.base = float(m["nomic-bert.rope.freq_base"])
        t = lambda n: torch.from_numpy(g.tensor(n)).to(dtype)
        self.p = {"emb": t("token_embd.weight"), "tt": t("token_types.weight")[0], "enw": t("token_embd_norm.weight"), "enb": t("token_embd_norm.bias")}
        self.blocks = []
        for i in range(self.L):
            b = f"blk.{i}."
            self.blocks.append({k: t(b + v) for k, v in dict(qkv="attn_qkv.weight", o="attn_output.weight", up="ffn_up.weight", gate="ffn_gate.weight",
                                                             down="ffn_down.weight", n1w="attn_output_norm.weight", n1b="attn_output_norm.bias",
                                                             n2w="layer_output_norm.weight", n2b="layer_output_norm.bias").items()})
        self.dtype = dtype

    def _rope(self, x):                           # x: [B, H, T, d]
        d = x.shape[-1]
        pos = torch.arange(x.shape[2], dtype=torch.float32)
        inv = 1.0 / (self.base ** (torch.arange(0, d, 2, dtype=torch.float32) / d))
        ang = torch.outer(pos, inv)               # [T, d/2]
        cos, sin = torch.cos(ang).repeat(1, 2).to(x.dtype), torch.sin(ang).repeat(1, 2).to(x.dtype)
        x1, x2 = x[..., : d // 2], x[..., d // 2:]
        return x * cos + torch.cat((-x2, x1), dim=-1) * sin

    @torch.no_grad()
    def hidden(self, ids, mask):                  # ids/mask: [B, T] -> [B, T, D]
        p = self.p
        x = F.embedding(ids, p["emb"]) + p["tt"]
        x = F.layer_norm(x, (self.D,), p["enw"], p["enb"], self.eps)
        B, T, _ = x.shape
        neg = torch.zeros(B, 1, 1, T, dtype=x.dtype).masked_fill(mask[:, None, None, :] == 0, torch.finfo(x.dtype).min)
        for b in self.blocks:
            qkv = x @ b["qkv"].T
            q, k, v = (a.view(B, T, self.H, -1).transpose(1, 2) for a in qkv.split(self.D, dim=-1))
            q, k = self._rope(q), self._rope(k)
            a = F.scaled_dot_product_attention(q, k, v, attn_mask=neg)
            a = a.transpose(1, 2).reshape(B, T, self.D) @ b["o"].T
            x = F.layer_norm(x + a, (self.D,), b["n1w"], b["n1b"], self.eps)
            h = (x @ b["up"].T) * F.silu(x @ b["gate"].T)
            x = F.layer_norm(x + h @ b["down"].T, (self.D,), b["n2w"], b["n2b"], self.eps)
        return x

    @torch.no_grad()
    def pooled(self, ids, mask):
        h = self.hidden(ids, mask).float()
        m = mask[..., None].float()
        return (h * m).sum(1) / m.sum(1)


def encode_batch(tok: Tokenizer, texts):
    encs = tok.encode_batch(list(texts))
    T = max(len(e.ids) for e in encs)
    ids = torch.zeros(len(encs), T, dtype=torch.long)
    mask = torch.zeros(len(encs), T, dtype=torch.long)
    for i, e in enumerate(encs):
        ids[i, : len(e.ids)] = torch.tensor(e.ids)
        mask[i, : len(e.ids)] = 1
    return ids, mask, [len(e.ids) for e in encs]


def embed(model: NomicTorch, tok: Tokenizer, texts, batch=16, normalise=True, layer_norm_recipe=False):
    """Returns float32 [N, 768]. layer_norm_recipe=True applies the sentence-transformers recipe published for v1.5
    (F.layer_norm before truncation/normalisation); the default matches llama.cpp / Ollama (no extra layer norm)."""
    out = []
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    for s in range(0, len(texts), batch):
        idx = order[s:s + batch]
        ids, mask, _ = encode_batch(tok, [texts[i] for i in idx])
        v = model.pooled(ids, mask)
        if layer_norm_recipe:
            v = F.layer_norm(v, (v.shape[-1],))
        if normalise:
            v = F.normalize(v, dim=-1)
        out.append((idx, v.numpy()))
    res = np.zeros((len(texts), out[0][1].shape[1]), dtype=np.float32)
    for idx, v in out:
        res[idx] = v
    return res


def load(max_len=2048):
    path, digest = ollama_blob()
    g = Gguf(path)
    return g, digest, build_tokenizer(g, max_len)
