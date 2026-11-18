"""Stage 7B.2: only when KYR_CANDIDATE_EMBED is set, replace langchain_ollama.OllamaEmbeddings (the one place the server and the probes obtain
an embedder locally) with the bge-small candidate. Added to PYTHONPATH by the candidate runners only; production code is unchanged.
The server's index profile still prepends nomic's task prefixes ("search_document: ", "search_query: "); this adapter strips them and
applies the candidate's own convention instead. Models load lazily so unrelated subprocesses stay light."""
import os

if os.environ.get("KYR_CANDIDATE_EMBED"):
    import sys
    sys.path.insert(0, os.environ["KYR_CANDIDATE_DIR"])
    import langchain_ollama

    class CandidateEmbeddings:
        _model = None

        def __init__(self, model="nomic-embed-text", **kw):
            self.model = "bge-small-en-v1.5(candidate)"

        @classmethod
        def _m(cls):
            if cls._model is None:
                import bge_candidate
                cls._model = bge_candidate.Bge(query_instruction=os.environ["KYR_CANDIDATE_EMBED"] == "bge_small_instr")
            return cls._model

        def embed_documents(self, texts):
            return self._m().docs([t.removeprefix("search_document: ") for t in texts]).tolist()

        def embed_query(self, text):
            return self._m().queries([text.removeprefix("search_query: ")])[0].tolist()

    langchain_ollama.OllamaEmbeddings = CandidateEmbeddings
