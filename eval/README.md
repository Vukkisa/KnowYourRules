# Retrieval benchmark

A reproducible, offline benchmark for the KnowYourRules retrieval pipeline. It compares chunking, embedding, retrieval and reranking options against the current production configuration.

## Data: synthetic and fictional on purpose

`data/corpus_v1.json` is a **fictional** legal corpus:
- the "Velora Road Traffic Act", the "Velora Central Motor Vehicle Rules", and rules for two fictional states, "Northland" and "Southmark"
- 36 provisions, with amounts in the invented unit VEL

It mimics the structure of the real sources: numbered sections and rules, sub-clauses, a penalty schedule, and near-duplicate state provisions that tempt cross-state confusion. **It is not law and must not be cited.** It exists so retrieval can be measured without indexing real legal texts that are not yet approved. The Gujarat sources are on hold pending counsel review.

`data/queries_v1.json` holds 72 queries with gold provision IDs:

| Type | Count |
|---|---|
| Paraphrase | 30 |
| State-specific | 19 |
| Keyword | 8 |
| Section reference | 2 |
| Hinglish | 3 |
| Hindi | 2 |
| Unanswerable | 8 |

Queries with odd IDs are the **dev** split, used to choose configurations; queries with even IDs are the **test** split, used to report results.

To extend the dataset, add provisions and queries in a new version (`corpus_v2.json`, `queries_v2.json`) and keep v1 unchanged, so results stay comparable. A benchmark on real sources should use only documents that have been approved for indexing.

## Protocol

- **Document text.** Each document's text is built the way `UnstructuredPDFLoader(mode="single")` returns it: one string per file. The benchmark does not exercise PDF extraction itself.
- **Search scope.** Candidates are restricted to the user's state plus `Central`, as `server.retrieve_for_state` does.
- **Relevance.** A chunk counts as relevant to a provision if it covers at least min(100 characters, 30%) of that provision's text. Header text that a chunker adds does not count.
- **Metrics:**
  - MRR, recall@k, hit@k, precision@k, nDCG@k for k = 1, 4, 8
  - context characters in the top 4
  - AUROC of the top score for answerable versus unanswerable queries
  - mean and p95 latency
  - index time and peak RSS
- **As-deployed baseline.** The benchmark also replays the server flow exactly: state top 4, then Central top 4, each filtered by the relevance gate at squared L2 ≤ 0.88.

## Configurations

| Axis | Options |
|---|---|
| Chunking | `fixed-1000/200` (production), `fixed-500/100`, `sentence-600`, `structure` (one chunk per section or rule), `provision-contextual` (`structure` plus a document-title and heading prefix on every chunk) |
| Embeddings | `nomic-embed-text` via Ollama exactly as the server calls it (no task prefix); the same model with nomic's `search_query:` / `search_document:` prefixes; `BAAI/bge-small-en-v1.5` |
| Retrieval | dense; BM25 (Okapi, k1 = 1.5, b = 0.75, implemented in plain Python); hybrid (min-max, 0.5/0.5); RRF (k = 60, top 50 from each) |
| Reranking | none; `BAAI/bge-reranker-base` over the top 20 |

No multilingual embedding or reranker models were tested. None were cached locally, and downloading them needs explicit approval.

## Reproduce

Requirements: Python 3.11, `langchain-text-splitters`, `langchain-ollama`, `transformers`, `torch`, and a running Ollama with `nomic-embed-text`. The Hugging Face models must already be in the local cache, because loading uses `local_files_only=True`. The exact versions, model revisions and dataset hashes are written into each results file.

```bash
python3 eval/rag_bench.py --tag v1            # full grid (about 15-25 min on an M1 CPU, with the reranker)
python3 eval/rag_bench.py --skip-rerank --tag v1-norerank   # about 1 min
python3 eval/analyze.py eval/results/run_v1.json > eval/results/analysis_v1.md
python3 -m unittest discover -s tests -p "test_rag_bench.py"
```

Nothing here reads or writes `chroma_langchain_db/` or calls an external API.
