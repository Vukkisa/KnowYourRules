# KnowYourRules

A RAG-backed chatbot for looking up Indian traffic rules and regulations, grounded strictly
in official government documents. It never answers from general knowledge — if a rule isn't
in the indexed corpus, it says so instead of guessing.

> **Scope: Telangana only.** KnowYourRules currently supports **Telangana (TG)** only: Telangana's own rules,
> orders and taxation, plus a few selected Central provisions (see Current coverage) kept clearly labelled as Central.
> Other states are not covered and get a "not covered" answer. Earlier work on Gujarat was abandoned and is
> archived in `archive/abandoned-gujarat/` (main checkout); it is not part of the project.

## Approach

```
Gov. websites → Downloaded PDFs → Text extraction → Chunking → Embeddings → Chroma
                                                                                 │
Chat UI ← Groq LLM (strict prompt) ← Retrieved chunks ─────────────────────────┘
```

The bot asks for your state if it doesn't know it (rules vary by state), retrieves the most
relevant chunks — your state's rules plus the nationwide Central rules — and answers using
*only* that text, citing the source. Follow-up questions are resolved using recent
conversation history before retrieval runs.

## The process

1. **Gather sources** — India's traffic regulations are split across Central, state, union
   territory, city/district, and judicial bodies, with no single index. A research pass
   produced **126 verified official government document sources** across this hierarchy.
   → [`research/india_traffic_document_links.xlsx`](research/india_traffic_document_links.xlsx)

2. **Extract documents** — [`scripts/extract_documents.py`](scripts/extract_documents.py)
   downloads every reachable document from those sources, tracking full provenance (URL,
   SHA-256, timestamp) in a manifest, and resumes safely if interrupted.
   → downloads go to `data/raw/` (created on first run; not in the repo)

3. **Triage for OCR cost** — OCR on scanned PDFs measured at ~9–40 sec/page; the full corpus
   would take 50+ hours. Rather than eat that cost blindly, documents were filtered to real
   Acts/Rules (not routine notices) and split by **text-native** (instant to extract) vs.
   **scanned** (needs OCR). This produced **84 text-native files** usable immediately.

4. **Build the RAG pipeline** — [`notebooks/rag_pipeline.ipynb`](notebooks/rag_pipeline.ipynb),
   built and validated phase by phase: document loading, chunking
   (`RecursiveCharacterTextSplitter`), embedding (Ollama), vector storage (Chroma), and
   strict-grounded retrieval + generation (Groq). A multi-language OCR + translation path
   was also built and validated for scanned documents (any Indian language → English) but
   isn't in the production index yet, given time constraints.

5. **Narrow to a production scope** — embedding all 84 files would take ~70 minutes; given a
   hard deadline, scope was narrowed to **24 curated files**: Central Motor Vehicles Act/Rules
   plus six other states (an earlier multi-state phase, since replaced by the Telangana-only scope). This step
   also caught a real bug — two files had been downloaded via other states' pages and were
   mistagged with that state's name, even though their content is the nationwide Central Act.
   Every chunk now carries a verified `state` metadata field used to filter retrieval.

6. **Backend** — [`backend/server.py`](backend/server.py) (FastAPI) wraps the RAG chain with
   what production needs: asks for and remembers your location, filters retrieval by state
   (falling back to Central rules + an honest "not covered" note if your state isn't
   indexed), and keeps short conversation history so follow-ups resolve correctly.

7. **Frontend** — [`frontend/index.html`](frontend/index.html): a single-page chat UI served
   directly by the backend, with markdown-rendered answers and a session that resets cleanly
   on reload.

## Tech stack

| Layer | Choice |
|---|---|
| LLM | Groq (`openai/gpt-oss-120b`) |
| Embeddings | Ollama `nomic-embed-text` (local) |
| Framework | LangChain (loaders, splitters, prompts, LCEL chains) |
| Vector store | Chroma (persisted locally) |
| PDF/OCR | `unstructured` (`fast` for text-native, `hi_res` + Tesseract for scanned) |
| Backend | FastAPI |
| Frontend | Vanilla HTML/CSS/JS + `marked.js` |

## Project structure

```
├── backend/          # FastAPI server (server.py), indexing, retrieval, grounded answering, document
│                     #   lifecycle, release gates and offence-date routing, embedding providers
├── frontend/         # Chat UI (index.html, render.js)
├── tests/            # Offline unit tests (test_*.py), fixtures, and manual probe scripts (*_probe.py)
├── scripts/          # Page build, runtime/cloud checks, deployment manifest, document extraction
├── deploy/           # Deployment templates: Render, Vercel, OCI (Caddy, systemd), manifest
├── .github/          # CI workflow (GitHub Pages build)
├── legal/            # Runtime legal state: the document lifecycle registry (legal/lifecycle/), which says
│                     #   which source versions are approved and active
├── legal-status/     # Per-source text-status registry (source-status.json)
├── snapshot-store/   # Verified index snapshot bundled for hosted deployment
├── docs/             # approval-trust-model.md, legal-review/ (validity design, roadmap, worksheet,
│                     #   reconciliation report), legal-sources/ (source documents and manifests)
├── eval/             # Benchmarks and evidence: retrieval benchmark and review files, answer-quality
│                     #   and real-model evaluations, latency, deployment audits, legal-validation stages
├── research/         # Government source inventory (spreadsheets)
├── notebooks/        # Pipeline build and validation notebook
├── data/             # Created by scripts/extract_documents.py on first run
├── dev-output/       # Generated validity-coverage reports (only deployed-s11 kept)
├── pyproject.toml, vercel.json, .vercelignore
├── requirements.txt, requirements-cloud.txt, requirements-notebooks.txt, .env.example
└── chroma_telangana_staging_validity/   # Local staging index used by tests (not deployed; not in git)
```

Runtime paths (`legal/`, `legal-status/`, `snapshot-store/`, the `eval/` benchmark files) are read by
the code and by the tests; do not rename them without updating both.

## Setup

Python 3.11 or 3.12. There are three dependency files; install only the one you need.

| Use | Command |
|---|---|
| **Active application** (run the server, build the index, run the tests) | `pip install -r requirements.txt` |
| **Cloud deployment** (Render; Vercel installs the same pins from `pyproject.toml`) | `pip install -r requirements-cloud.txt` |
| **Notebook and research environment** (Jupyter, the notebooks, evaluation scripts; a superset of `requirements.txt`) | `pip install -r requirements-notebooks.txt` |

`requirements.txt` builds on `requirements-cloud.txt` (`-r`), so the server's pins are defined in one place. Never install
`requirements-notebooks.txt` on a server: it brings torch, transformers and the notebook stack.

```bash
python -m venv .venv
source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
ollama pull nomic-embed-text
```

Copy `.env.example` to `.env` and add your `GROQ_API_KEY`.

## Running it

```bash
# Build the Telangana index
python -m backend.build_telangana_index --manifest MANIFEST.json --corpus CORPUS_DIR --db-dir INDEX_DIR
# Activate documents in the lifecycle registry (records the approval basis verbatim; no signature or key is involved)
python -m backend.document_lifecycle --state-dir legal/lifecycle --db-dir INDEX_DIR bootstrap \
    --by "OPERATOR" --approval-basis "TEXT STATING WHO APPROVED WHAT, AND ON WHAT BASIS"
uvicorn backend.server:app --reload --port 8000
```

The earlier multi-state builder (`backend/build_index.py`) was retired and removed; it remains in git history.

Open http://localhost:8000.

## Current coverage

**Telangana first, with selected Central provisions kept apart.** The Telangana corpus is the Telangana Motor
Vehicles Rules (HTML), the Taxation Rules and Telangana Government Orders (PDF). Beside it, three **Central** sources
are indexed under their own `Central` tag and shown as Central in every citation: an extract of the Motor Vehicles Act,
1988 (sections 3-15, 39-41, 50, 56, 112, 128-130, 134 and 146, from the India Code consolidation as on 15-08-2026, with no
penalty sections), the Motor Vehicles (Driving) Regulations, 2017 (G.S.R. 634(E)) and their 2020 amendment (G.S.R. 586(E)).
They are in `docs/legal-sources/telangana-traffic/CENTRAL-manifest.json` and `source-documents/central/`, and are indexed
as the `telangana-traffic-rules` collection (685 chunks in the preview index). The Central Motor Vehicles Rules, 1989 are
**not** indexed: the only copy found is out of date, so forms, documents, fees and test details they prescribe are not
answered. Other states, including the earlier multi-state files, get an honest "not covered" answer.
Answers are served only from documents that are approved and active in the lifecycle registry
(see `docs/approval-trust-model.md`). All 23 source versions are active on an owner-attested, unauthenticated approval
basis. Their source verification status is unchanged (unverified; the Central sources are "official text, currency not
confirmed"), so answers carry a warning, and fine and penalty answers stay restricted.

## Acknowledgments

The LangChain/Groq/Ollama code patterns used here — embedding/chat model setup, prompt
templates, LCEL chain composition — follow the syntax and conventions taught in our
coursework on building RAG systems.
