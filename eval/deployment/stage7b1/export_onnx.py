"""Export the GGUF-weight nomic-embed-text-v1.5 re-implementation to ONNX (graph includes mean pooling + L2 normalisation),
then make an int8 dynamic-quantised variant. Output goes to a scratch directory (files are 150-550 MB; not kept in the repo).
usage: export_onnx.py OUT_DIR"""
import hashlib
import json
import sys
from pathlib import Path

import torch
import torch.nn.functional as F

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import nomic_runtime as nr  # noqa: E402

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
g, digest, tok = nr.load()
ref = nr.NomicTorch(g)


class Graph(torch.nn.Module):
    def __init__(self, r):
        super().__init__()
        P = torch.nn.Parameter
        self.D, self.H, self.eps, self.base = r.D, r.H, r.eps, r.base
        self.emb, self.tt, self.enw, self.enb = (P(r.p[k], requires_grad=False) for k in ("emb", "tt", "enw", "enb"))
        self.bl = torch.nn.ParameterList()
        self.keys = ["qkv", "o", "up", "gate", "down", "n1w", "n1b", "n2w", "n2b"]
        for b in r.blocks:
            for k in self.keys:
                self.bl.append(P(b[k], requires_grad=False))

    def rope(self, x, cos, sin):
        d = x.shape[-1] // 2
        return x * cos + torch.cat((-x[..., d:], x[..., :d]), dim=-1) * sin

    def forward(self, input_ids, attention_mask):
        B, T = input_ids.shape
        x = F.layer_norm(F.embedding(input_ids, self.emb) + self.tt, (self.D,), self.enw, self.enb, self.eps)
        pos = torch.arange(T, dtype=torch.float32)
        inv = 1.0 / (self.base ** (torch.arange(0, 64, 2, dtype=torch.float32) / 64.0))
        ang = pos[:, None] * inv[None, :]
        cos, sin = torch.cos(ang).repeat(1, 2), torch.sin(ang).repeat(1, 2)
        neg = (1.0 - attention_mask.to(torch.float32))[:, None, None, :] * -1e9
        for i in range(12):
            qkv_w, o_w, up_w, gate_w, down_w, n1w, n1b, n2w, n2b = (self.bl[i * 9 + j] for j in range(9))
            q, k, v = (a.view(B, T, self.H, 64).transpose(1, 2) for a in (x @ qkv_w.T).split(self.D, dim=-1))
            q, k = self.rope(q, cos, sin), self.rope(k, cos, sin)
            att = torch.softmax((q @ k.transpose(-1, -2)) / 8.0 + neg, dim=-1) @ v
            x = F.layer_norm(x + att.transpose(1, 2).reshape(B, T, self.D) @ o_w.T, (self.D,), n1w, n1b, self.eps)
            h = (x @ up_w.T) * F.silu(x @ gate_w.T)
            x = F.layer_norm(x + h @ down_w.T, (self.D,), n2w, n2b, self.eps)
        m = attention_mask.to(torch.float32)[..., None]
        pooled = (x * m).sum(1) / m.sum(1)
        return F.normalize(pooled, dim=-1)


gm = Graph(ref).eval()
ids = torch.tensor([[101, 7592, 2088, 102, 0], [101, 7592, 2088, 2088, 102]])
mask = torch.tensor([[1, 1, 1, 1, 0], [1, 1, 1, 1, 1]])
fp32 = out / "nomic_v1_5_fp32.onnx"
kw = dict(input_names=["input_ids", "attention_mask"], output_names=["embedding"], opset_version=17,
          dynamic_axes={"input_ids": {0: "b", 1: "t"}, "attention_mask": {0: "b", 1: "t"}, "embedding": {0: "b"}})
try:
    torch.onnx.export(gm, (ids, mask), str(fp32), dynamo=False, **kw)
except TypeError:
    torch.onnx.export(gm, (ids, mask), str(fp32), **kw)

from onnxruntime.quantization import QuantType, quantize_dynamic  # noqa: E402
int8 = out / "nomic_v1_5_int8.onnx"
quantize_dynamic(str(fp32), str(int8), weight_type=QuantType.QInt8)
info = {"gguf_blob": digest}
for p in (fp32, int8):
    info[p.name] = {"bytes": p.stat().st_size, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
(HERE / "onnx_export_info.json").write_text(json.dumps(info, indent=1))
print(json.dumps(info, indent=1))
