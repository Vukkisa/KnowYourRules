"""Exact (brute-force) vector search over the stored chunk embeddings.

Drop-in replacement for `Chroma.similarity_search_with_score(question, k, filter)` for small corpora, where
Chroma's approximate HNSW index was shown to return results that differ from the true nearest neighbours and
vary between opens of identical index copies (eval/legal-validation/STAGE-15-REPORT.md).

Semantics kept identical to the collection's:
  * metric: squared L2, Chroma's default "l2" space (the Telangana collection sets no space), smaller = closer;
  * query embedding: the store's own embedding function (`embed_query`, which adds the profile's query prefix);
  * stored embeddings, documents, metadata and ids are read once from the collection, unchanged;
  * result: [(Document(page_content, metadata, id), distance)], ascending distance, at most k.

Determinism: distances are computed element-wise in float64 (no BLAS reduction-order effects), and ties are
broken explicitly by chunk id, so the same query on the same stored data always returns the same list.
Only equality filters ({"field": value, ...}) are supported; anything else raises ValueError so the caller can
fall back to Chroma rather than silently ignore a filter.
"""

import math

import numpy as np
from langchain_core.documents import Document

SUPPORTED_SPACES = ("l2",)


class ExactVectorIndex:
    def __init__(self, ids, embeddings, documents, metadatas, embedding_function, space="l2"):
        if space not in SUPPORTED_SPACES:
            raise ValueError(f"unsupported distance space {space!r}")
        if not (len(ids) == len(embeddings) == len(documents) == len(metadatas)):
            raise ValueError("ids, embeddings, documents and metadatas differ in length")
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk ids")
        matrix = np.asarray(embeddings, dtype=np.float64)
        if len(ids) and (matrix.ndim != 2 or not np.isfinite(matrix).all()):
            raise ValueError("stored embeddings are not a finite 2-D matrix")
        self.ids = list(ids)
        self.matrix = matrix
        self.documents = list(documents)
        self.metadatas = [dict(m or {}) for m in metadatas]
        self.embedding_function = embedding_function
        self.space = space

    @classmethod
    def from_store(cls, store):
        """Snapshot a LangChain Chroma store. Reads only; never writes to the collection."""
        collection = store._collection
        space = (collection.metadata or {}).get("hnsw:space", "l2")
        got = collection.get(include=["embeddings", "documents", "metadatas"])
        return cls(got["ids"], got["embeddings"], got["documents"], got["metadatas"],
                   store.embeddings, space=space)

    def __len__(self):
        return len(self.ids)

    def distances(self, query_embedding) -> np.ndarray:
        q = np.asarray(query_embedding, dtype=np.float64)
        if q.ndim != 1 or (len(self.ids) and q.shape[0] != self.matrix.shape[1]) or not np.isfinite(q).all():
            raise ValueError("query embedding has the wrong shape or is not finite")
        if not len(self.ids):
            return np.zeros(0)
        diff = self.matrix - q
        return (diff * diff).sum(axis=1)  # squared L2, Chroma's "l2"

    def _matches(self, meta, where) -> bool:
        return all(meta.get(k) == v for k, v in where.items())

    def search_by_vector(self, query_embedding, k: int, filter=None) -> list:
        if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
            return []
        where = filter or {}
        if not isinstance(where, dict) or any(k_.startswith("$") or isinstance(v, (dict, list)) for k_, v in where.items()):
            raise ValueError("only flat equality filters are supported")
        d = self.distances(query_embedding)
        candidates = [i for i in range(len(self.ids)) if self._matches(self.metadatas[i], where)]
        candidates.sort(key=lambda i: (float(d[i]), self.ids[i]))  # explicit, stable tie-break on chunk id
        return [(Document(page_content=self.documents[i], metadata=dict(self.metadatas[i]), id=self.ids[i]),
                 float(d[i])) for i in candidates[:k] if math.isfinite(float(d[i]))]

    def similarity_search_with_score(self, query: str, k: int = 4, filter=None) -> list:
        if not isinstance(query, str) or not query.strip():
            return []
        return self.search_by_vector(self.embedding_function.embed_query(query), k, filter)
