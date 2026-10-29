"""Reproducible retrieval benchmark for KnowYourRules.

Runs on the synthetic corpus in eval/data (fictional law; see the notice in corpus_v1.json), so no real
or unapproved legal source is indexed. Nothing here touches the production Chroma index.

    python3 eval/rag_bench.py                    # full grid, writes eval/results/
    python3 eval/rag_bench.py --skip-rerank      # without the cross-encoder

The baseline reproduces the server: RecursiveCharacterTextSplitter(1000, 200), Ollama nomic-embed-text
with no task prefix, dense k=4 per filter (user's state, then Central), relevance gate at squared L2 <= 0.88.
"""

import argparse
import hashlib
import json
import math
import platform
import random
import re
import resource
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data"
RESULTS = HERE / "results"

BASELINE_MAX_DISTANCE = 0.88  # server.DEFAULT_MAX_DISTANCE (squared L2 on unit vectors)
RRF_K = 60
CANDIDATES = 20
KS = (1, 4, 8)


# ---------------------------------------------------------------- corpus and queries

def load_corpus(path):
    """One text per document (like UnstructuredPDFLoader mode="single"), with each provision's span."""
    corpus = json.loads(Path(path).read_text(encoding="utf-8"))
    docs = []
    for d in corpus["documents"]:
        text, spans = d["title"] + "\n\n", []
        for p in d["provisions"]:
            start = len(text)
            text += p["heading"] + "\n" + p["text"]
            spans.append((p["id"], start, len(text)))
            text += "\n\n"
        docs.append({"doc_id": d["doc_id"], "title": d["title"], "state": d["state"], "text": text.rstrip() + "\n",
                     "spans": spans, "headings": {p["id"]: p["heading"] for p in d["provisions"]}})
    return docs


def load_queries(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))["queries"]


def split_ids(queries):
    """Deterministic dev/test split: odd-numbered queries are dev, even-numbered are test."""
    dev = [q for q in queries if int(q["id"][1:]) % 2 == 1]
    test = [q for q in queries if int(q["id"][1:]) % 2 == 0]
    return dev, test


# ---------------------------------------------------------------- chunkers
# Every chunk records the character span of the source text it came from, so relevance is judged by
# overlap with the gold provision, independently of any header text a chunker adds.

def _chunk(doc, text, start, end):
    return {"doc_id": doc["doc_id"], "state": doc["state"], "text": text, "start": start, "end": end}


def chunk_fixed(docs, size=1000, overlap=200):
    from langchain_text_splitters import RecursiveCharacterTextSplitter
    splitter = RecursiveCharacterTextSplitter(chunk_size=size, chunk_overlap=overlap, add_start_index=True)
    out = []
    for d in docs:
        for piece in splitter.create_documents([d["text"]]):
            s = piece.metadata["start_index"]
            out.append(_chunk(d, piece.page_content, s, s + len(piece.page_content)))
    return out


SENTENCE_END = re.compile(r"(?<=[.!?])\s+|\n+")


def _sentences(text, base=0):
    """(sentence, start, end) triples; splits on sentence punctuation and on line breaks."""
    out, pos = [], 0
    for m in SENTENCE_END.finditer(text):
        if text[pos:m.start()].strip():
            out.append((text[pos:m.start()], base + pos, base + m.start()))
        pos = m.end()
    if text[pos:].strip():
        out.append((text[pos:].rstrip(), base + pos, base + len(text.rstrip())))
    return out


def chunk_sentences(docs, max_chars=600, overlap_sentences=1):
    out = []
    for d in docs:
        sents = _sentences(d["text"])
        i = 0
        while i < len(sents):
            j, length = i, 0
            while j < len(sents) and (j == i or length + len(sents[j][0]) <= max_chars):
                length += len(sents[j][0]) + 1
                j += 1
            s, e = sents[i][1], sents[j - 1][2]
            out.append(_chunk(d, d["text"][s:e], s, e))
            if j >= len(sents):
                break
            i = max(i + 1, j - overlap_sentences)
    return out


def _sections(doc):
    """(provision_id, start, end) for each provision; the document title is not a section."""
    return [(pid, s, e) for pid, s, e in doc["spans"]]


def _split_long(text, max_chars, overlap=100):
    """Split an over-long section at sentence boundaries; returns (offset, piece) pairs."""
    if len(text) <= max_chars:
        return [(0, text)]
    pieces, sents, i = [], _sentences(text), 0
    while i < len(sents):
        j, length = i, 0
        while j < len(sents) and (j == i or length + len(sents[j][0]) <= max_chars):
            length += len(sents[j][0]) + 1
            j += 1
        s, e = sents[i][1], sents[j - 1][2]
        pieces.append((s, text[s:e]))
        if j >= len(sents):
            break
        back = j - 1 if overlap and j - 1 > i else j
        i = back
    return pieces


def chunk_structure(docs, max_chars=1000, contextual=False):
    """One chunk per Section/Rule; long sections are split at sentence boundaries.

    contextual=True is the provision-aware variant: every chunk (including continuation pieces) is
    prefixed with the document title and the provision heading, so a sub-chunk keeps its citation.
    """
    out = []
    for d in docs:
        for pid, s, e in _sections(d):
            body = d["text"][s:e]
            for off, piece in _split_long(body, max_chars):
                text = piece
                if contextual:
                    heading = d["headings"][pid]
                    text = f"{d['title']} - {heading}\n" + (piece if off == 0 else f"{heading} (continued)\n{piece}")
                out.append(_chunk(d, text, s + off, s + off + len(piece)))
    return out


CHUNKERS = {
    "fixed-1000/200 (baseline)": lambda docs: chunk_fixed(docs, 1000, 200),
    "fixed-500/100": lambda docs: chunk_fixed(docs, 500, 100),
    "sentence-600": lambda docs: chunk_sentences(docs, 600, 1),
    "structure": lambda docs: chunk_structure(docs, 1000, contextual=False),
    "provision-contextual": lambda docs: chunk_structure(docs, 1000, contextual=True),
}


# ---------------------------------------------------------------- relevance mapping

def provisions_hit(chunk, docs_by_id):
    """Provision ids that this chunk substantially covers (>= min(100 chars, 30% of the provision))."""
    hits = set()
    for pid, s, e in docs_by_id[chunk["doc_id"]]["spans"]:
        overlap = min(chunk["end"], e) - max(chunk["start"], s)
        if overlap >= min(100, 0.3 * (e - s)):
            hits.add(pid)
    return hits


# ---------------------------------------------------------------- lexical retrieval

TOKEN = re.compile(r"\w+", re.UNICODE)


def tokenize(text):
    return TOKEN.findall(text.lower())


class BM25:
    """Okapi BM25 (k1=1.5, b=0.75) with the non-negative idf log(1 + (N - df + 0.5) / (df + 0.5))."""

    def __init__(self, texts, k1=1.5, b=0.75):
        self.k1, self.b = k1, b
        self.docs = [tokenize(t) for t in texts]
        self.lengths = [len(d) for d in self.docs]
        self.avgdl = (sum(self.lengths) / len(self.lengths)) if self.docs else 0.0
        df = {}
        for d in self.docs:
            for term in set(d):
                df[term] = df.get(term, 0) + 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5)) for t, c in df.items()}
        self.tf = [{} for _ in self.docs]
        for i, d in enumerate(self.docs):
            for term in d:
                self.tf[i][term] = self.tf[i].get(term, 0) + 1

    def scores(self, query):
        q = tokenize(query)
        out = []
        for i in range(len(self.docs)):
            s = 0.0
            for term in q:
                f = self.tf[i].get(term)
                if f:
                    denom = f + self.k1 * (1 - self.b + self.b * self.lengths[i] / (self.avgdl or 1))
                    s += self.idf[term] * f * (self.k1 + 1) / denom
            out.append(s)
        return out


# ---------------------------------------------------------------- fusion

def rrf(rankings, k=RRF_K):
    """Reciprocal Rank Fusion over lists of item ids (best first). Returns ids by fused score."""
    scores = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores, key=lambda i: (-scores[i], i)), scores


def minmax(values):
    lo, hi = min(values), max(values)
    return [0.0 if hi == lo else (v - lo) / (hi - lo) for v in values]


# ---------------------------------------------------------------- metrics

def query_metrics(ranked_chunks, gold, pool_relevant_count, ks=KS):
    """ranked_chunks: list of sets of provision ids hit by each retrieved chunk (best first)."""
    gold = set(gold)
    rel = [bool(hits & gold) for hits in ranked_chunks]
    m = {}
    first = next((i for i, r in enumerate(rel) if r), None)
    m["mrr"] = 0.0 if first is None else 1.0 / (first + 1)
    for k in ks:
        top = ranked_chunks[:k]
        covered = set().union(*top) & gold if top else set()
        m[f"recall@{k}"] = len(covered) / len(gold)
        m[f"hit@{k}"] = 1.0 if covered else 0.0
        m[f"precision@{k}"] = sum(rel[:k]) / k
        dcg = sum(1.0 / math.log2(i + 2) for i, r in enumerate(rel[:k]) if r)
        ideal = sum(1.0 / math.log2(i + 2) for i in range(min(k, pool_relevant_count)))
        m[f"ndcg@{k}"] = dcg / ideal if ideal else 0.0
    return m


def auroc(pos_scores, neg_scores):
    """Probability a random answerable query scores above a random unanswerable one (ties count half)."""
    if not pos_scores or not neg_scores:
        return float("nan")
    wins = sum((p > n) + 0.5 * (p == n) for p in pos_scores for n in neg_scores)
    return wins / (len(pos_scores) * len(neg_scores))


def paired_bootstrap(a, b, n=2000, seed=0):
    """95% interval for mean(b - a) over paired per-query values."""
    rng = random.Random(seed)
    diffs = [y - x for x, y in zip(a, b)]
    means = sorted(statistics.fmean(rng.choice(diffs) for _ in diffs) for _ in range(n))
    return statistics.fmean(diffs), means[int(0.025 * n)], means[int(0.975 * n) - 1]


# ---------------------------------------------------------------- models (loaded lazily)

def _normalize(v):
    norm = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / norm for x in v]


class OllamaNomic:
    """The server's embedding client. prefix=True adds nomic's documented task prefixes."""

    def __init__(self, prefix=False):
        from langchain_ollama import OllamaEmbeddings
        self.model = OllamaEmbeddings(model="nomic-embed-text")
        self.prefix = prefix
        self.raw_norms = []

    def docs(self, texts):
        vecs = self.model.embed_documents([("search_document: " + t) if self.prefix else t for t in texts])
        self.raw_norms += [math.sqrt(sum(x * x for x in v)) for v in vecs]
        return [_normalize(v) for v in vecs]

    def query(self, text):
        return _normalize(self.model.embed_query(("search_query: " + text) if self.prefix else text))


class HFEmbedder:
    """BGE-style encoder from the local Hugging Face cache (CLS pooling, L2-normalised)."""

    def __init__(self, name, query_instruction="", device="cpu"):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch, self.device = torch, device
        self.tok = AutoTokenizer.from_pretrained(name, local_files_only=True)
        self.model = AutoModel.from_pretrained(name, local_files_only=True).to(device).eval()
        self.instruction = query_instruction

    def _encode(self, texts, batch=16):
        out = []
        with self.torch.no_grad():
            for i in range(0, len(texts), batch):
                enc = self.tok(texts[i:i + batch], padding=True, truncation=True, max_length=512, return_tensors="pt").to(self.device)
                cls = self.model(**enc).last_hidden_state[:, 0]
                out += self.torch.nn.functional.normalize(cls, dim=-1).cpu().tolist()
        return out

    def docs(self, texts):
        return self._encode(texts)

    def query(self, text):
        return self._encode([self.instruction + text])[0]


class CrossEncoder:
    def __init__(self, name, device="cpu"):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        self.torch, self.device = torch, device
        self.tok = AutoTokenizer.from_pretrained(name, local_files_only=True)
        self.model = AutoModelForSequenceClassification.from_pretrained(name, local_files_only=True).to(device).eval()

    def scores(self, query, texts, batch=16):
        out = []
        with self.torch.no_grad():
            for i in range(0, len(texts), batch):
                enc = self.tok([query] * len(texts[i:i + batch]), texts[i:i + batch], padding=True, truncation=True,
                               max_length=512, return_tensors="pt").to(self.device)
                out += self.model(**enc).logits.view(-1).float().cpu().tolist()
        return out


EMBEDDERS = {
    "nomic (baseline)": lambda: OllamaNomic(prefix=False),
    "nomic+prefix": lambda: OllamaNomic(prefix=True),
    "bge-small-en-v1.5": lambda: HFEmbedder("BAAI/bge-small-en-v1.5", "Represent this sentence for searching relevant passages: "),
}
RERANKER = "BAAI/bge-reranker-base"


# ---------------------------------------------------------------- benchmark

def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def pool_for(chunks, state):
    return [i for i, c in enumerate(chunks) if c["state"] in (state, "Central")]


def run(args):
    docs = load_corpus(DATA / "corpus_v1.json")
    docs_by_id = {d["doc_id"]: d for d in docs}
    queries = load_queries(DATA / "queries_v1.json")
    dev_ids = {q["id"] for q in split_ids(queries)[0]}
    rows, per_query, timings = [], {}, {}

    reranker = None
    if not args.skip_rerank:
        t = time.perf_counter()
        reranker = CrossEncoder(RERANKER)
        timings["reranker_load_s"] = time.perf_counter() - t

    chunk_sets = {name: fn(docs) for name, fn in CHUNKERS.items()}
    hits_sets = {name: [provisions_hit(c, docs_by_id) for c in cs] for name, cs in chunk_sets.items()}

    def record(config, ranked_per_query, top_score, latency):
        """ranked_per_query: {qid: [chunk indices best-first]}; top_score: {qid: confidence (higher = surer)}."""
        cname = config["chunker"]
        chunks, hits = chunk_sets[cname], hits_sets[cname]
        pq = {}
        for q in queries:
            ranked = ranked_per_query[q["id"]]
            if q["gold"]:
                pool = pool_for(chunks, q["state"])
                pool_rel = sum(1 for i in pool if hits[i] & set(q["gold"]))
                m = query_metrics([hits[i] for i in ranked], q["gold"], pool_rel)
                m["context_chars@4"] = sum(len(chunks[i]["text"]) for i in ranked[:4])
            else:
                m = {}
            m["top_score"] = top_score[q["id"]]
            pq[q["id"]] = m
        key = " | ".join(f"{k}={v}" for k, v in config.items())
        per_query[key] = pq
        for split_name, keep in (("dev", lambda qid: qid in dev_ids), ("test", lambda qid: qid not in dev_ids), ("all", lambda qid: True)):
            ans = [q for q in queries if q["gold"] and keep(q["id"])]
            una = [q for q in queries if not q["gold"] and keep(q["id"])]
            row = dict(config, split=split_name, n_answerable=len(ans), n_unanswerable=len(una))
            for metric in ["mrr"] + [f"{m}@{k}" for m in ("recall", "hit", "precision", "ndcg") for k in KS] + ["context_chars@4"]:
                row[metric] = statistics.fmean(pq[q["id"]][metric] for q in ans)
            row["auroc_answerable"] = auroc([pq[q["id"]]["top_score"] for q in ans], [pq[q["id"]]["top_score"] for q in una])
            row["latency_ms_mean"] = latency[0]
            row["latency_ms_p95"] = latency[1]
            rows.append(row)

    def lat(samples):
        samples = sorted(samples)
        return (1000 * statistics.fmean(samples), 1000 * samples[min(len(samples) - 1, int(0.95 * len(samples)))])

    # BM25 is embedder-independent
    for cname, chunks in chunk_sets.items():
        ranked, top, times = {}, {}, []
        for q in queries:
            t = time.perf_counter()
            pool = pool_for(chunks, q["state"])
            bm = BM25([chunks[i]["text"] for i in pool])
            sc = bm.scores(q["query"])
            order = sorted(range(len(pool)), key=lambda j: -sc[j])[:CANDIDATES]
            times.append(time.perf_counter() - t)
            ranked[q["id"]] = [pool[j] for j in order]
            top[q["id"]] = sc[order[0]] if order else 0.0
        record({"chunker": cname, "embedder": "-", "retrieval": "bm25", "rerank": "none"}, ranked, top, lat(times))

    for ename, make in EMBEDDERS.items():
        t = time.perf_counter()
        emb = make()
        load_s = time.perf_counter() - t
        qvecs, qtimes = {}, {}
        for q in queries:
            t = time.perf_counter()
            qvecs[q["id"]] = emb.query(q["query"])
            qtimes[q["id"]] = time.perf_counter() - t
        for cname, chunks in chunk_sets.items():
            t = time.perf_counter()
            dvecs = emb.docs([c["text"] for c in chunks])
            timings[f"index_s[{ename}][{cname}]"] = time.perf_counter() - t
            timings[f"n_chunks[{cname}]"] = len(chunks)
            dense, bm25_rank, fused, hybrid, top = {}, {}, {}, {}, {"dense": {}, "rrf": {}, "hybrid": {}}
            t_dense, t_rrf, t_hyb = [], [], []
            for q in queries:
                pool = pool_for(chunks, q["state"])
                t = time.perf_counter()
                sims = [dot(qvecs[q["id"]], dvecs[i]) for i in pool]
                d_order = sorted(range(len(pool)), key=lambda j: -sims[j])
                dense[q["id"]] = [pool[j] for j in d_order[:CANDIDATES]]
                top["dense"][q["id"]] = sims[d_order[0]]  # cosine; squared L2 = 2 - 2*cos
                t_dense.append(qtimes[q["id"]] + time.perf_counter() - t)

                t = time.perf_counter()
                bm = BM25([chunks[i]["text"] for i in pool])
                bsc = bm.scores(q["query"])
                b_order = sorted(range(len(pool)), key=lambda j: -bsc[j])
                order, fs = rrf([[pool[j] for j in d_order[:50]], [pool[j] for j in b_order[:50]]])
                fused[q["id"]] = order[:CANDIDATES]
                top["rrf"][q["id"]] = fs[order[0]]
                t_rrf.append(qtimes[q["id"]] + time.perf_counter() - t + t_dense[-1] - qtimes[q["id"]])

                t = time.perf_counter()
                comb = [0.5 * a + 0.5 * b for a, b in zip(minmax(sims), minmax(bsc))]
                h_order = sorted(range(len(pool)), key=lambda j: -comb[j])
                hybrid[q["id"]] = [pool[j] for j in h_order[:CANDIDATES]]
                top["hybrid"][q["id"]] = sims[h_order[0]]
                t_hyb.append(t_dense[-1] + time.perf_counter() - t)
            base = {"chunker": cname, "embedder": ename, "rerank": "none"}
            record(dict(base, retrieval="dense"), dense, top["dense"], lat(t_dense))
            record(dict(base, retrieval="rrf(dense+bm25)"), fused, top["rrf"], lat(t_rrf))
            record(dict(base, retrieval="hybrid-0.5"), hybrid, top["hybrid"], lat(t_hyb))

            if ename == "nomic (baseline)" and cname == "fixed-1000/200 (baseline)":
                rows.extend(as_deployed(chunks, hits_sets[cname], dvecs, qvecs, queries, dev_ids))

            if reranker and ename != "nomic (baseline)" and cname in ("fixed-1000/200 (baseline)", "structure", "provision-contextual"):
                for first_stage, cand in (("dense", dense), ("rrf(dense+bm25)", fused)):
                    rr, rtop, rt = {}, {}, []
                    for q in queries:
                        t = time.perf_counter()
                        ids = cand[q["id"]]
                        sc = reranker.scores(q["query"], [chunks[i]["text"] for i in ids])
                        order = sorted(range(len(ids)), key=lambda j: -sc[j])
                        rr[q["id"]] = [ids[j] for j in order]
                        rtop[q["id"]] = sc[order[0]] if order else float("-inf")
                        rt.append(time.perf_counter() - t + qtimes[q["id"]])
                    record(dict(base, retrieval=first_stage, rerank="bge-reranker-base@20"), rr, rtop, lat(rt))
        timings[f"embedder_load_s[{ename}]"] = load_s
        if isinstance(emb, OllamaNomic) and emb.raw_norms:
            timings[f"raw_norm_range[{ename}]"] = [min(emb.raw_norms), max(emb.raw_norms)]

    return rows, per_query, timings


def as_deployed(chunks, hits, dvecs, qvecs, queries, dev_ids):
    """The server's exact flow: state top-4 then Central top-4, each gated at squared L2 <= 0.88."""
    out = []
    pq = {}
    for q in queries:
        lists = []
        for st in ([q["state"]] if q["state"] != "Central" else []) + ["Central"]:
            pool = [i for i, c in enumerate(chunks) if c["state"] == st]
            sims = sorted(((dot(qvecs[q["id"]], dvecs[i]), i) for i in pool), reverse=True)[:4]
            lists += [i for s, i in sims if 2 - 2 * s <= BASELINE_MAX_DISTANCE]
        seen, ranked = set(), []
        for i in lists:
            if i not in seen:
                seen.add(i)
                ranked.append(i)
        pq[q["id"]] = ranked
    for split_name, keep in (("dev", lambda qid: qid in dev_ids), ("test", lambda qid: qid not in dev_ids), ("all", lambda qid: True)):
        ans = [q for q in queries if q["gold"] and keep(q["id"])]
        una = [q for q in queries if not q["gold"] and keep(q["id"])]
        recall = statistics.fmean(len(set().union(*[hits[i] for i in pq[q["id"]]]) & set(q["gold"])) / len(q["gold"]) if pq[q["id"]] else 0.0 for q in ans)
        out.append({"chunker": "fixed-1000/200 (baseline)", "embedder": "nomic (baseline)", "retrieval": "AS-DEPLOYED state4+central4, gate 0.88",
                    "rerank": "none", "split": split_name, "n_answerable": len(ans), "n_unanswerable": len(una),
                    "recall@all_passed": recall,
                    "false_refusal_rate": statistics.fmean(0.0 if pq[q["id"]] else 1.0 for q in ans),
                    "correct_refusal_rate": statistics.fmean(0.0 if pq[q["id"]] else 1.0 for q in una) if una else float("nan"),
                    "mean_chunks_passed": statistics.fmean(len(pq[q["id"]]) for q in ans)})
    return out


def environment():
    def sh(cmd):
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip()
        except Exception:
            return None
    import importlib.metadata as md
    versions = {}
    for pkg in ("langchain-text-splitters", "langchain-ollama", "transformers", "torch", "numpy"):
        try:
            versions[pkg] = md.version(pkg)
        except Exception:
            versions[pkg] = None
    return {
        "python": sys.version.split()[0], "platform": platform.platform(), "machine": platform.machine(),
        "packages": versions,
        "git_commit": sh(["git", "-C", str(HERE.parent), "rev-parse", "HEAD"]),
        "ollama_models": sh(["ollama", "list"]),
        "hf_revisions": {"BAAI/bge-small-en-v1.5": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
                         "BAAI/bge-reranker-base": "2cfc18c9415c912f9d8155881c133215df768a70"},
        "dataset_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(DATA.glob("*.json"))},
    }


def write_markdown(rows, path):
    cols = ["chunker", "embedder", "retrieval", "rerank", "mrr", "recall@4", "ndcg@4", "precision@4", "hit@1", "context_chars@4", "auroc_answerable", "latency_ms_mean"]
    lines = []
    for split in ("test", "dev", "all"):
        lines += [f"## Split: {split}", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in sorted((r for r in rows if r["split"] == split and "mrr" in r), key=lambda r: -r["mrr"]):
            lines.append("| " + " | ".join(f"{r[c]:.3f}" if isinstance(r[c], float) else str(r[c]) for c in cols) + " |")
        lines.append("")
    dep = [r for r in rows if "recall@all_passed" in r]
    if dep:
        lines += ["## As-deployed baseline (server flow with relevance gate)", "",
                  "| split | recall (chunks passed) | false refusal | correct refusal | mean chunks passed |", "|---|---|---|---|---|"]
        for r in dep:
            lines.append(f"| {r['split']} | {r['recall@all_passed']:.3f} | {r['false_refusal_rate']:.3f} | {r['correct_refusal_rate']:.3f} | {r['mean_chunks_passed']:.2f} |")
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--skip-rerank", action="store_true")
    ap.add_argument("--tag", default="v1")
    args = ap.parse_args(argv)
    RESULTS.mkdir(exist_ok=True)
    t0 = time.perf_counter()
    rows, per_query, timings = run(args)
    timings["total_s"] = time.perf_counter() - t0
    timings["peak_rss_mb"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1024 * 1024 if sys.platform == "darwin" else 1024)
    out = {"environment": environment(), "timings": timings, "rows": rows, "per_query": per_query}
    (RESULTS / f"run_{args.tag}.json").write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    write_markdown(rows, RESULTS / f"run_{args.tag}.md")
    print(f"wrote {RESULTS / f'run_{args.tag}.json'} and .md in {timings['total_s']:.0f}s; peak RSS {timings['peak_rss_mb']:.0f} MB")


if __name__ == "__main__":
    main()
