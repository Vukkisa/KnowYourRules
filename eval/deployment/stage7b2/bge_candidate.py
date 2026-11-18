"""Stage 7B.2 Path B: BAAI/bge-small-en-v1.5 (384-d, CLS pooling, L2-normalised), loaded from the LOCAL Hugging Face cache only
(HF_HUB_OFFLINE=1: this module cannot download anything). Nothing here talks to a hosted service.
Convention (model card): documents are embedded as-is; queries may carry the instruction below. Both conventions are evaluated."""
import glob
import os

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
import numpy as np  # noqa: E402
import torch  # noqa: E402
from transformers import AutoModel, AutoTokenizer  # noqa: E402

QUERY_INSTRUCTION = "Represent this sentence for searching relevant passages: "
PATH = glob.glob(os.path.expanduser("~/.cache/huggingface/hub/models--BAAI--bge-small-en-v1.5/snapshots/*"))[0]


class Bge:
    def __init__(self, query_instruction=True, max_len=512, batch=16):
        self.tok = AutoTokenizer.from_pretrained(PATH)
        self.model = AutoModel.from_pretrained(PATH).eval()
        self.qi, self.max_len, self.batch = query_instruction, max_len, batch
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))

    @torch.no_grad()
    def _enc(self, texts):
        out = []
        for i in range(0, len(texts), self.batch):
            t = self.tok(texts[i:i + self.batch], padding=True, truncation=True, max_length=self.max_len, return_tensors="pt")
            h = self.model(**t).last_hidden_state[:, 0]                      # CLS pooling
            out.append(torch.nn.functional.normalize(h, p=2, dim=1).numpy())
        return np.concatenate(out).astype(np.float32)

    def docs(self, texts):
        return self._enc(list(texts))

    def queries(self, texts):
        return self._enc([(QUERY_INSTRUCTION if self.qi else "") + t for t in texts])

    def truncated(self, texts):
        """How many of `texts` exceed the model's 512-token window (their tail is not embedded)."""
        return sum(len(self.tok(t, add_special_tokens=True)["input_ids"]) > self.max_len for t in texts)
