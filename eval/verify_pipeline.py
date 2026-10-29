"""End-to-end parity check: build the synthetic corpus with the real backend/build_index.py into a
throwaway Chroma directory, query it the way backend/server.py does, and score it like rag_bench.

    python3 eval/verify_pipeline.py            # both profiles; needs Ollama with nomic-embed-text

Never opens chroma_langchain_db/. Expected: each profile's MRR matches rag_bench's dense result for the
same chunking + embedding (baseline: fixed-1000/200 + nomic; structured: structure + nomic+prefix).
"""

import io
import json
import os
import statistics
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "eval"))
os.environ.setdefault("ANONYMIZED_TELEMETRY", "False")

import chromadb  # noqa: E402
from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402
from langchain_ollama import OllamaEmbeddings  # noqa: E402

import backend.build_index as bi  # noqa: E402
from backend import rag_profiles as rp  # noqa: E402
import rag_bench as rb  # noqa: E402


def main():
    docs = rb.load_corpus(rb.DATA / "corpus_v1.json")
    by_id = {d["doc_id"]: d for d in docs}
    queries = rb.load_queries(rb.DATA / "queries_v1.json")
    dev_ids = {q["id"] for q in rb.split_ids(queries)[0]}
    results = {}
    with tempfile.TemporaryDirectory() as tmp:
        corpus = Path(tmp) / "corpus"
        (corpus / "state").mkdir(parents=True)
        files = []
        for d in docs:
            (corpus / "state" / f"{d['doc_id']}.txt").write_text(d["text"], encoding="utf-8")
            files.append((f"state/{d['doc_id']}.txt", d["state"]))

        class TextLoader:
            def __init__(self, path, **kwargs):
                self.path = path

            def load(self):
                return [Document(page_content=Path(self.path).read_text(encoding="utf-8"), metadata={"source": self.path})]

        for name in ("baseline", "structured"):
            db = Path(tmp) / f"db-{name}"
            out = io.StringIO()
            with redirect_stdout(out):
                rc = bi.main(corpus, db, files, loader_cls=TextLoader, profile=rp.get_profile(name))
            assert rc == 0, out.getvalue()
            client = chromadb.PersistentClient(path=str(db))
            emb = rp.ProfileEmbeddings(OllamaEmbeddings(model="nomic-embed-text"))
            store = Chroma(client=client, collection_name=bi.COLLECTION, embedding_function=emb)
            emb.profile = rp.profile_of_index(store)  # exactly what server.py does at startup
            assert emb.profile.name == name
            mrr = {"dev": [], "test": []}
            for q in queries:
                if not q["gold"]:
                    continue
                hits = store.similarity_search_with_score(q["query"], k=rb.CANDIDATES, filter={"state": {"$in": [q["state"], "Central"]}})
                rel = []
                for doc, _ in hits:
                    doc_id = Path(doc.metadata["source_file"]).stem
                    s = doc.metadata["start_index"]
                    rel.append(bool(rb.provisions_hit({"doc_id": doc_id, "start": s, "end": s + len(doc.page_content)}, by_id) & set(q["gold"])))
                first = next((i for i, r in enumerate(rel) if r), None)
                mrr["dev" if q["id"] in dev_ids else "test"].append(0.0 if first is None else 1 / (first + 1))
            results[name] = {k: round(statistics.fmean(v), 3) for k, v in mrr.items()}
            results[name]["n_chunks"] = client.get_collection(bi.COLLECTION).count()
    print(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
