# Retrieval optimisation: results and chosen configuration

Branch `comp-rag-optimization`. Benchmark details are in [README.md](README.md). The full tables are in `results/run_v1.md` and `results/analysis_v1.md`.

**All numbers come from the fictional synthetic corpus** (36 provisions, 72 queries). They show the direction of an effect, not proof. Nothing has been measured on the real legal corpus, which is not available and partly awaits legal approval.

## Results (held-out test split, 32 answerable queries)

| Configuration | MRR | Recall@4 | ΔMRR vs production [95% CI] | Latency per query |
|---|---|---|---|---|
| Production: fixed 1000/200, nomic (no prefix), dense | 0.818 | 0.922 | — | ~37 ms |
| **Chosen: section chunks, nomic + task prefixes, dense** | **0.872** | **0.969** | +0.055 [−0.034, +0.148] | ~32–47 ms |
| Section chunks + bge-reranker-base over the top 20 | 0.896–0.897 | 0.938 | +0.078 to +0.080 [−0.013, +0.173] | 1,700–2,600 ms |
| Section chunks, bge-small-en-v1.5, dense | 0.855 | 0.938 | +0.037 [−0.077, +0.145] | ~28 ms |
| BM25 / hybrid / RRF over section chunks | ≤ 0.85 | — | no gain over dense | — |

On the dev split, used for choosing the configuration, the chosen setup scored 0.984 against the baseline's 0.917.

**Why this configuration was chosen:**
- It had the best dev MRR of the configurations that need no new model, no new dependency and no extra latency.
- It held up on test.
- It gave the largest gain on state-specific questions, where MRR rose from 0.85 to 0.97 across all queries.

**Why not the reranker:** it scored highest, but it was about 50 times slower, needs a 1.1 GB model on an 8 GB machine, and its gain is not statistically significant.

**Why not hybrid or BM25:** neither helped once chunks follow section boundaries.

**Caveat:** no difference is statistically significant with 32 test queries.

## What was implemented

Implemented in `backend/rag_profiles.py`, `backend/build_index.py` and `backend/server.py`.

| Profile | Chunking | Embedding input | Default relevance gate |
|---|---|---|---|
| `baseline` (rollback) | `RecursiveCharacterTextSplitter(1000, 200)` | as is | squared L2 ≤ 0.88 |
| `structured` (new build default) | One chunk per Section, Rule or numbered provision. Long sections are split 1000/200; sections under 200 characters merge into the next. Documents with fewer than 3 headings fall back to fixed chunks. | `search_document:` / `search_query:` prefixes (nomic's documented task prefixes) | squared L2 ≤ **0.80**, provisional |

**How the profile is chosen and recorded:**
- `RAG_PROFILE` selects the profile at build time. An unknown value fails the build and leaves the live index unchanged.
- The build records the profile in the Chroma collection's metadata, and the staging check refuses a collection without that record.
- The server reads the record at startup and embeds queries to match. **An index built before this change has no record and is treated as `baseline`**, so the current production index keeps working exactly as before.
- `RAG_MAX_DISTANCE` still overrides the gate.

**Gate threshold.** Task prefixes compress distances. With the gate left at 0.88, correct refusals of unanswerable synthetic questions fell from 50% to 12.5%. At 0.80 the structured profile wrongly refuses 6% of answerable questions and correctly refuses 38% of unanswerable ones; the baseline at 0.88 does 9% and 50%. Neither separates answerable from unanswerable questions well, because the AUROC is about 0.87–0.90. **Recalibrate on an approved real corpus before relying on it.**

**Parity.** Running the real build and retrieval code on the synthetic corpus (`eval/verify_pipeline.py`, throwaway Chroma) reproduces the benchmark: baseline 0.917 / 0.818 and structured 0.969 / 0.872 (dev / test). Structured dev differs from the benchmark's 0.984 because the implementation merges a document's title line into its first section.

## Rollback

There are two ways back:
- **Rebuild with the old profile:** `RAG_PROFILE=baseline python backend/build_index.py`. The server picks the profile up from the index after a restart.
- **Keep the existing index:** an index built before this change already runs as `baseline`.

## Failure cases and limitations

- **Hindi and Hinglish questions are weak in every configuration** (MRR about 0.25–0.6 on 5 queries). No multilingual embedding model or reranker was tested: none was cached, and downloading one needs approval.
- **Remaining failures** of the chosen configuration on test:
  - questions whose answer sits in the penalty schedule rather than the substantive section, e.g. q22 "licence suspended for no helmet", which is answered in Section 10
  - q06 and q26, where a neighbouring section ranks first
- **Heading detection is unvalidated on real PDFs.** It is built for headings at the start of a line ("Section 12.", "Rule 5.", "184. …"). It has not been run on real extracted text, where `unstructured` may join lines. The fallback to fixed chunks limits the damage, but check chunk counts and sample chunks when the real corpus is rebuilt.
- **Answer correctness and citation support were not measured.** That needs the production LLM, and the Groq key was revoked, so this benchmark measures retrieval only.
- **Latency and memory figures** come from an M1 with 8 GB of RAM, measured in one process. Embedder order affects warm-up timings.
- **Live effect needs a rebuild.** The change takes effect only after the production index is rebuilt with the new profile, and that rebuild is blocked by the Gujarat legal-source sign-off.

## Reproduce

```bash
python3 -m unittest discover -s tests                       # 83 offline tests
python3 eval/rag_bench.py --tag v1 && python3 eval/analyze.py eval/results/run_v1.json
python3 eval/verify_pipeline.py                             # needs Ollama + nomic-embed-text
```
