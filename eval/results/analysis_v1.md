# Analysis of run_v1.json 

Configurations ranked by **dev** MRR; metrics below are on the held-out **test** split (32 answerable test queries). Δ = test MRR minus baseline, with a paired-bootstrap 95% CI.

| rank | config | dev MRR | test MRR | Δ MRR [95% CI] | test recall@4 | test nDCG@4 | AUROC (test) | gate: test false-refusal / correct-refusal | latency ms |
|---|---|---|---|---|---|---|---|---|---|
| 1 | chunker=structure | embedder=nomic+prefix | retrieval=dense | rerank=none | 0.984 | 0.872 | +0.055 [-0.034, +0.148] | 0.969 | 0.885 | 0.898 | 0.56 / 1.00 | 47 |
| 2 | chunker=sentence-600 | embedder=nomic+prefix | retrieval=dense | rerank=none | 0.969 | 0.851 | +0.033 [-0.076, +0.144] | 0.906 | 0.825 | 0.883 | 0.69 / 1.00 | 47 |
| 3 | chunker=fixed-500/100 | embedder=nomic+prefix | retrieval=dense | rerank=none | 0.964 | 0.870 | +0.052 [-0.062, +0.164] | 0.906 | 0.846 | 0.906 | 0.59 / 1.00 | 49 |
| 4 | chunker=structure | embedder=nomic (baseline) | retrieval=dense | rerank=none | 0.958 | 0.857 | +0.039 [-0.029, +0.112] | 0.969 | 0.880 | 0.898 | 0.53 / 1.00 | 37 |
| 5 | chunker=provision-contextual | embedder=nomic+prefix | retrieval=dense | rerank=bge-reranker-base@20 | 0.958 | 0.872 | +0.054 [-0.035, +0.141] | 0.938 | 0.883 | 0.938 | 0.16 / 1.00 | 1919 |
| 6 | chunker=provision-contextual | embedder=nomic+prefix | retrieval=rrf(dense+bm25) | rerank=bge-reranker-base@20 | 0.958 | 0.872 | +0.054 [-0.035, +0.141] | 0.938 | 0.883 | 0.938 | 0.16 / 1.00 | 1763 |
| 7 | chunker=provision-contextual | embedder=bge-small-en-v1.5 | retrieval=dense | rerank=bge-reranker-base@20 | 0.958 | 0.871 | +0.053 [-0.037, +0.141] | 0.938 | 0.883 | 0.938 | 0.16 / 1.00 | 2608 |
| 8 | chunker=provision-contextual | embedder=bge-small-en-v1.5 | retrieval=rrf(dense+bm25) | rerank=bge-reranker-base@20 | 0.958 | 0.872 | +0.054 [-0.036, +0.141] | 0.938 | 0.883 | 0.938 | 0.16 / 1.00 | 2104 |
| 9 | chunker=structure | embedder=nomic+prefix | retrieval=dense | rerank=bge-reranker-base@20 | 0.958 | 0.896 | +0.078 [-0.013, +0.172] | 0.938 | 0.903 | 0.945 | 0.34 / 1.00 | 2406 |
| 10 | chunker=structure | embedder=nomic+prefix | retrieval=rrf(dense+bm25) | rerank=bge-reranker-base@20 | 0.958 | 0.897 | +0.079 [-0.011, +0.172] | 0.938 | 0.903 | 0.945 | 0.34 / 1.00 | 1912 |
| 11 | chunker=structure | embedder=bge-small-en-v1.5 | retrieval=dense | rerank=bge-reranker-base@20 | 0.958 | 0.896 | +0.078 [-0.013, +0.172] | 0.938 | 0.903 | 0.945 | 0.34 / 1.00 | 1692 |
| 12 | chunker=structure | embedder=bge-small-en-v1.5 | retrieval=rrf(dense+bm25) | rerank=bge-reranker-base@20 | 0.958 | 0.897 | +0.080 [-0.011, +0.173] | 0.938 | 0.903 | 0.945 | 0.34 / 1.00 | 2185 |
| base | chunker=fixed-1000/200 (baseline) | embedder=nomic (baseline) | retrieval=dense | rerank=none | 0.917 | 0.818 | +0.000 [+0.000, +0.000] | 0.922 | 0.834 | 0.867 | 0.31 / 1.00 | 37 |

## MRR by query type (all answerable queries, dev+test)

| type | n | cfg0 | cfg1 | cfg2 | cfg3 | cfg4 |
|---|---|---|---|---|---|---|
| hindi | 2 | 0.33 | 0.62 | 0.28 | 0.54 | 0.25 |
| hinglish | 3 | 0.56 | 0.83 | 1.00 | 0.67 | 0.58 |
| keyword | 8 | 1.00 | 1.00 | 1.00 | 1.00 | 1.00 |
| paraphrase | 30 | 0.90 | 0.91 | 0.92 | 0.94 | 0.91 |
| section-ref | 2 | 1.00 | 1.00 | 0.50 | 0.50 | 1.00 |
| state-specific | 19 | 0.85 | 0.97 | 0.95 | 0.97 | 0.97 |

- cfg0: chunker=fixed-1000/200 (baseline) | embedder=nomic (baseline) | retrieval=dense | rerank=none
- cfg1: chunker=structure | embedder=nomic+prefix | retrieval=dense | rerank=none
- cfg2: chunker=sentence-600 | embedder=nomic+prefix | retrieval=dense | rerank=none
- cfg3: chunker=fixed-500/100 | embedder=nomic+prefix | retrieval=dense | rerank=none
- cfg4: chunker=structure | embedder=nomic (baseline) | retrieval=dense | rerank=none

## Failures of the top dev configuration on test (MRR < 1)

- q06 (paraphrase, Southmark): "I moved here with my car from another state, how long before I need new number plates?" gold=['A-4'] mrr=0.50 (baseline 1.00)
- q10 (state-specific, Northland): "What is the speed limit for cars inside the city?" gold=['N-1'] mrr=0.50 (baseline 0.50)
- q22 (paraphrase, Northland): "Can my licence be suspended for not wearing a helmet?" gold=['A-10'] mrr=0.33 (baseline 0.50)
- q26 (paraphrase, Northland): "Can a drunk driving case be settled by paying a compounding fee?" gold=['A-11'] mrr=0.50 (baseline 1.00)
- q32 (paraphrase, Northland): "Will the hospital force me to give my name if I bring in an accident victim?" gold=['A-14'] mrr=0.33 (baseline 0.50)
- q60 (hinglish, Northland): "bina helmet ke bike chalane par kitna jurmana lagta hai?" gold=['A-10', 'N-2'] mrr=0.50 (baseline 0.17)
- q64 (hindi, Northland): "दुर्घटना होने पर ड्राइवर को पुलिस को कब सूचना देनी होती है?" gold=['A-12'] mrr=0.25 (baseline 0.33)

## Environment

```json
{
 "python": "3.11.2",
 "platform": "macOS-27.2-arm64-arm-64bit",
 "packages": {
  "langchain-text-splitters": "0.3.11",
  "langchain-ollama": "0.3.10",
  "transformers": "5.17.0",
  "torch": "2.13.0",
  "numpy": "1.26.4"
 },
 "git_commit": "4b09a03e6ca0bfc01a3b2064d5179b69a83ac139",
 "hf_revisions": {
  "BAAI/bge-small-en-v1.5": "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a",
  "BAAI/bge-reranker-base": "2cfc18c9415c912f9d8155881c133215df768a70"
 },
 "dataset_sha256": {
  "corpus_v1.json": "0c6872c2821c05e9b1e5ab233cc6e86adbecd4a2e6bc95333c50bcf5d6872f85",
  "queries_v1.json": "c5a7d7f618ffc9ed222b4fc8ad7ac10c3759bae4cf2acb9c88774c84f6f6c4b1"
 }
}
```

Timings: {"reranker_load_s": 9.58, "index_s[nomic (baseline)][fixed-1000/200 (baseline)]": 2.16, "index_s[nomic (baseline)][fixed-500/100]": 3.19, "index_s[nomic (baseline)][sentence-600]": 2.25, "index_s[nomic (baseline)][structure]": 2.32, "index_s[nomic (baseline)][provision-contextual]": 2.16, "embedder_load_s[nomic (baseline)]": 0.15, "raw_norm_range[nomic (baseline)]": [0.9999994865798919, 1.0000006956692629], "index_s[nomic+prefix][fixed-1000/200 (baseline)]": 1.97, "index_s[nomic+prefix][fixed-500/100]": 4.34, "index_s[nomic+prefix][sentence-600]": 6.1, "index_s[nomic+prefix][structure]": 3.44, "index_s[nomic+prefix][provision-contextual]": 2.49, "embedder_load_s[nomic+prefix]": 0.02, "raw_norm_range[nomic+prefix]": [0.9999995229665862, 1.00000060652862], "index_s[bge-small-en-v1.5][fixed-1000/200 (baseline)]": 0.64, "index_s[bge-small-en-v1.5][fixed-500/100]": 1.26, "index_s[bge-small-en-v1.5][sentence-600]": 0.68, "index_s[bge-small-en-v1.5][structure]": 0.8, "index_s[bge-small-en-v1.5][provision-contextual]": 1.46, "embedder_load_s[bge-small-en-v1.5]": 0.7, "total_s": 1764.86, "peak_rss_mb": 830.8}
