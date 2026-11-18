"""Stage 7C: liveness vs readiness. The fake-backed server of tests/test_server.py importing with a local-directory snapshot (the R2 stand-in),
production configuration, no network, no model. `/health` = the process is up. `/ready` = the corpus was restored and verified AND every
integrity check passes; any failure keeps it false and the service answers "unavailable". Real R2 and a real index are not involved."""
import json
import shutil
import unittest
from pathlib import Path
from unittest import mock

import chromadb

import test_cloud_readiness as tcr
import test_index_snapshot as tis
import test_source_status as tss
from backend import embedding_provider as ep
from backend import index_snapshot as snap
from backend import source_status as ss

PROD = {"TG_ENVIRONMENT": "production", "TG_LEGACY_DEV_ANSWERS": "", "TG_GROUNDED_ANSWERS": "1", "TG_CORS_ORIGINS": "https://someone.github.io"}
Q = "How do I apply for a learner's licence?"
ALL_OK = {"snapshot_restore", "snapshot_pinned", "index_present", "lifecycle_registry_and_audit", "source_status_registry", "embedding", "configuration"}


class RealMetaChroma:
    """Stands in for langchain_chroma.Chroma but reads the metadata of the REAL restored (tiny) collection, so index and registry agree like
    they do in production. Search is not needed here."""

    def __init__(self, **kw):
        self._col = chromadb.PersistentClient(path=kw["persist_directory"]).get_collection(kw["collection_name"])

    def get(self, include=None):
        g = self._col.get(include=["metadatas"])
        return {"ids": g["ids"], "metadatas": g["metadatas"]}

    def similarity_search_with_score(self, query, k=4, filter=None):
        return []


class ReadinessCase(tcr.ServerCase, tis.Fixture):
    def server(self, **env):
        with mock.patch.object(tcr.ts, "FakeChroma", RealMetaChroma):
            return super().server(**env)

    def prod_env(self, pin=True, status=True, **extra):
        env = {"TG_SNAPSHOT_STORE": "local", "TG_SNAPSHOT_LOCAL_DIR": str(self.tmp / "store"), "TG_SNAPSHOT_PREFIX": "",
               "TG_SNAPSHOT_WORK_DIR": str(self.tmp / "srvwork"), "TG_DB_DIR": None, "TG_LIFECYCLE_DIR": None,
               "TG_SNAPSHOT_STARTUP_TIMEOUT_SECONDS": "5", "TG_SNAPSHOT_RETRY_BASE_SECONDS": "0.1", "TG_SNAPSHOT_RETRY_MAX_DELAY_SECONDS": "1", **PROD}
        if pin is True:
            try:
                v = snap.parse_pointer(self.store.get_bytes("active.json"))
                env["TG_SNAPSHOT_PIN_SHA256"] = v["manifest_sha256"]
            except snap.StoreError:
                env["TG_SNAPSHOT_PIN_SHA256"] = "ab" * 32
        elif pin:
            env["TG_SNAPSHOT_PIN_SHA256"] = pin
        if status is True:
            env["TG_SOURCE_STATUS_FILE"] = str(self.status_file())
        env.update(extra)
        return env

    def status_file(self):
        """A valid status registry for the tiny index (one entry per indexed document)."""
        col = chromadb.PersistentClient(path=str(self.db)).get_collection(snap.COLLECTION)
        entries, seen = [], set()
        for m in col.get(include=["metadatas"])["metadatas"]:
            if m["sha256"] not in seen:
                seen.add(m["sha256"])
                f = m.get("source_file") or f"{m['sha256'][:8]}.pdf"
                entries.append(tss.entry(m["sha256"], f, manifest_id=m.get("manifest_id") or f))
        p = self.tmp / "source-status.json"
        p.write_text(json.dumps(tss.registry(*entries)))
        return p

    def publish_ok(self, **kw):
        return self.publish(family=ep.INDEX_FAMILY, **kw)

    def boot(self, **kw):
        srv, client = self.server(**self.prod_env(**kw))
        return srv, client

    def ready(self, client):
        r = client.get("/ready")
        return r.status_code, r.json()

    def failed(self, body):
        return {k for k, v in body["checks"].items() if v != "ok"}

    def chat(self, client):
        return client.post("/chat", json={"message": Q, "session_id": "s"}).json()


class SuccessTests(ReadinessCase):
    def test_a_restored_verified_pinned_snapshot_is_live_and_ready_but_answers_only_what_the_lifecycle_serves(self):
        self.publish_ok()
        srv, client = self.boot()
        self.assertEqual(client.get("/health").status_code, 200)
        code, body = self.ready(client)
        self.assertEqual((code, body["ready"]), (200, True))
        self.assertEqual(set(body["checks"]), ALL_OK)
        self.assertEqual(self.failed(body), set())
        self.assertTrue(body["answering"])                                          # a servable lifecycle document exists; no signed approval is needed
        self.assertEqual(self.chat(client)["kind"], "unavailable")
        s = client.get("/status").json()
        self.assertEqual(s["readiness"], {k: "ok" for k in ALL_OK})
        self.assertEqual((s["snapshot"]["pinned"], s["snapshot"]["attempts"]), (True, 1))

    def test_the_ready_response_carries_no_secrets_paths_or_hashes(self):
        self.publish_ok()
        srv, client = self.boot(pin=True)
        text = client.get("/ready").text + client.get("/health").text
        for needle in (str(self.tmp), "kyr-snapshots", "srvwork", srv.SNAPSHOT.manifest["index"]["sha256"], snap.parse_pointer(self.store.get_bytes("active.json"))["manifest_sha256"]):
            self.assertNotIn(needle, text)
        self.assertEqual(set(client.get("/ready").json()), {"ready", "answering", "checks"})


class FailedRestoreNeverReadyTests(ReadinessCase):
    def assert_not_ready(self, srv, client, failed_at_least):
        self.assertEqual(client.get("/health").status_code, 200)                    # liveness is independent of the corpus
        self.assertEqual(client.get("/health").json(), {"status": "ok"})
        code, body = self.ready(client)
        self.assertEqual((code, body["ready"], body["answering"]), (503, False, False))
        self.assertTrue(failed_at_least <= self.failed(body), (failed_at_least, self.failed(body)))
        self.assertEqual(self.chat(client)["kind"], "unavailable")                  # no answer from the corpus
        self.assertIsNone(srv.vector_store)                                         # nothing was opened, nothing was created
        self.assertFalse(srv._UNAVAILABLE_DIR.exists())

    def test_store_unavailable(self):
        srv, client = self.server(**self.prod_env(pin=True, TG_SNAPSHOT_STORE="r2", TG_SNAPSHOT_LOCAL_DIR=None, R2_ENDPOINT="http://127.0.0.1:9", R2_BUCKET="b",
                                                  R2_ACCESS_KEY_ID="id", R2_SECRET_ACCESS_KEY="secret", EMBEDDING_PROVIDER="openai_compatible",
                                                  EMBEDDING_MODEL="nomic-ai/nomic-embed-text-v1.5", EMBEDDING_API_URL="https://emb.example/v1", EMBEDDING_API_KEY="k"))
        self.assertEqual(srv.SNAPSHOT.state, "store_unavailable")
        self.assertTrue(srv.SNAPSHOT.timed_out)
        self.assert_not_ready(srv, client, {"snapshot_restore", "index_present", "lifecycle_registry_and_audit"})

    def test_missing_manifest(self):
        srv, client = self.boot(pin=True)
        self.assertEqual(srv.SNAPSHOT.state, "manifest_missing")
        self.assert_not_ready(srv, client, {"snapshot_restore", "snapshot_pinned", "index_present", "lifecycle_registry_and_audit"})

    def test_checksum_mismatch(self):
        m = self.publish_ok()
        (self.tmp / "store" / m["index"]["archive"]).write_bytes(b"corrupt")
        srv, client = self.boot()
        self.assertEqual(srv.SNAPSHOT.state, "checksum_mismatch")
        self.assert_not_ready(srv, client, {"snapshot_restore", "index_present"})

    def test_missing_index(self):
        m = self.publish_ok()
        (self.tmp / "store" / m["index"]["archive"]).unlink()
        srv, client = self.boot()
        self.assertEqual(srv.SNAPSHOT.state, "snapshot_missing")
        self.assert_not_ready(srv, client, {"snapshot_restore", "index_present"})

    def test_missing_registry(self):
        m = self.publish_ok()
        (self.tmp / "store" / m["lifecycle"]["archive"]).unlink()
        srv, client = self.boot()
        self.assertEqual(srv.SNAPSHOT.state, "snapshot_missing")
        self.assert_not_ready(srv, client, {"snapshot_restore", "lifecycle_registry_and_audit"})

    def test_registry_and_index_mismatch(self):
        self.publish_ok()
        self.rewrite(lambda m: m["index"].update(chunk_count=m["index"]["chunk_count"] + 1))
        v = snap.parse_pointer(self.store.get_bytes("active.json"))
        srv, client = self.boot(pin=v["manifest_sha256"])                           # the operator "reviewed" this forged manifest: the content checks still refuse it
        self.assertEqual(srv.SNAPSHOT.state, "index_invalid")
        self.assert_not_ready(srv, client, {"snapshot_restore", "index_present"})

    def test_a_manifest_naming_a_different_registry_is_refused(self):
        self.publish_ok()
        self.rewrite(lambda m: m["lifecycle"].update(registry_sha256="0" * 64))
        v = snap.parse_pointer(self.store.get_bytes("active.json"))
        srv, client = self.boot(pin=v["manifest_sha256"])
        self.assertEqual(srv.SNAPSHOT.state, "lifecycle_invalid")
        self.assert_not_ready(srv, client, {"snapshot_restore", "lifecycle_registry_and_audit"})

    def test_wrong_pin_and_missing_pin(self):
        self.publish_ok()
        srv, client = self.boot(pin="0" * 64)
        self.assertEqual(srv.SNAPSHOT.state, "pin_mismatch")
        self.assert_not_ready(srv, client, {"snapshot_restore", "snapshot_pinned"})
        srv, client = self.boot(pin=False)
        self.assertEqual(srv.SNAPSHOT.state, "pin_required")
        self.assert_not_ready(srv, client, {"snapshot_restore", "snapshot_pinned"})

    def test_interrupted_restore_leaves_nothing_usable_and_the_next_start_recovers(self):
        m = self.publish_ok()
        work = self.tmp / "srvwork" / "archives" / m["version"]
        work.mkdir(parents=True)
        (work / "index.tar.gz.part").write_bytes(b"half")
        (work / "index.tar.gz").write_bytes(b"cut off")
        srv, client = self.boot()
        self.assertEqual(self.ready(client)[0], 200)                                # the stale partial files were never trusted: re-downloaded and verified

    def test_recovery_after_a_failed_start_is_a_fresh_verified_restore(self):
        srv, client = self.boot(pin=True)                                           # nothing published yet
        self.assertEqual(self.ready(client)[0], 503)
        self.publish_ok()
        srv2, client2 = self.boot()                                                 # the next start (Render restarts a failing instance)
        self.assertEqual(self.ready(client2), (200, {"ready": True, "answering": True, "checks": {k: "ok" for k in ALL_OK}}))


class LiveIntegrityTests(ReadinessCase):
    def test_a_corrupted_lifecycle_audit_chain_turns_readiness_off_and_stops_answers(self):
        self.publish_ok()
        srv, client = self.boot()
        self.assertEqual(self.ready(client)[0], 200)
        audit = srv.LIFECYCLE.path.parent / "audit.jsonl"
        self.assertTrue(audit.is_file())
        audit.write_text(audit.read_text() + '{"tampered": true}\n')
        code, body = self.ready(client)
        self.assertEqual(code, 503)
        self.assertEqual(self.failed(body), {"lifecycle_registry_and_audit"})
        self.assertEqual(self.chat(client)["kind"], "unavailable")
        self.assertEqual(client.get("/health").status_code, 200)

    def test_a_registry_that_disappears_or_becomes_unreadable_turns_readiness_off(self):
        self.publish_ok()
        srv, client = self.boot()
        reg = srv.LIFECYCLE.path
        keep = reg.read_text()
        reg.write_text("not json")
        code, body = self.ready(client)
        self.assertEqual((code, "lifecycle_registry_and_audit" in self.failed(body)), (503, True))
        reg.unlink()
        code, body = self.ready(client)
        self.assertEqual((code, "lifecycle_registry_and_audit" in self.failed(body)), (503, True))
        self.assertEqual(self.chat(client)["kind"], "unavailable")
        reg.write_text(keep)                                                        # restoring the exact file restores readiness: no latch, no guess
        self.assertEqual(self.ready(client)[0], 200)

    def test_an_invalid_source_status_registry_turns_readiness_off(self):
        self.publish_ok()
        srv, client = self.boot(status=False, TG_SOURCE_STATUS_FILE=str(self.tmp / "absent-status.json"))
        code, body = self.ready(client)
        self.assertEqual((code, self.failed(body)), (503, {"source_status_registry"}))
        s = client.get("/status").json()
        self.assertEqual(s["source_status"]["blocking"], ["absent_status_registry"])


class EmbeddingReadinessTests(ReadinessCase):
    def test_a_missing_or_misconfigured_embedding_provider_is_not_ready(self):
        self.publish_ok()
        srv, client = self.boot(EMBEDDING_PROVIDER="openai_compatible", EMBEDDING_API_URL="https://emb.example/v1", EMBEDDING_MODEL="nomic-ai/nomic-embed-text-v1.5")
        code, body = self.ready(client)                                             # no key
        self.assertEqual((code, self.failed(body)), (503, {"embedding"}))
        self.assertEqual(self.chat(client)["kind"], "unavailable")

    def test_an_unverified_hosted_provider_is_not_ready_until_it_passes_the_probe_check(self):
        self.publish_ok()
        srv, client = self.boot(EMBEDDING_PROVIDER="openai_compatible", EMBEDDING_API_URL="https://emb.example/v1", EMBEDDING_API_KEY="k",
                                EMBEDDING_MODEL="nomic-ai/nomic-embed-text-v1.5", EMBEDDING_MODEL_FAMILY=ep.INDEX_FAMILY)
        self.assertIn(srv.EMBEDDING.state, ("unverified", "unavailable"))           # the startup probe could not reach a provider
        self.assertEqual(self.failed(self.ready(client)[1]), {"embedding"})

    def test_an_incompatible_embedding_family_is_not_ready(self):
        self.publish(family="some-other-family")
        srv, client = self.boot()
        self.assertEqual(srv.EMBEDDING.state, "incompatible")
        self.assertEqual(self.failed(self.ready(client)[1]), {"embedding"})


class ConfigurationReadinessTests(ReadinessCase):
    def test_a_missing_cors_origin_is_visible_in_ready_and_status_and_no_origin_is_allowed(self):
        self.publish_ok()
        srv, client = self.boot(TG_CORS_ORIGINS=None)
        code, body = self.ready(client)
        self.assertEqual((code, self.failed(body)), (503, {"configuration"}))
        s = client.get("/status").json()
        self.assertTrue(s["cors"]["problems"])
        self.assertEqual(s["cors"]["origins_configured"], 0)
        r = client.get("/status", headers={"Origin": "https://someone.github.io"})
        self.assertNotIn("access-control-allow-origin", r.headers)

    def test_localhost_is_not_allowed_in_production_but_is_in_development(self):
        self.publish_ok()
        srv, client = self.boot(TG_CORS_ORIGINS="http://localhost:5173")
        self.assertEqual(self.failed(self.ready(client)[1]), {"configuration"})
        self.assertNotIn("access-control-allow-origin", client.get("/status", headers={"Origin": "http://localhost:5173"}).headers)
        srv, client = self.server(TG_ENVIRONMENT="development", TG_CORS_ORIGINS="http://localhost:5173")
        self.assertEqual(client.get("/status", headers={"Origin": "http://localhost:5173"}).headers["access-control-allow-origin"], "http://localhost:5173")

    def test_the_configured_pages_origin_is_allowed_exactly(self):
        self.publish_ok()
        srv, client = self.boot()
        ok = client.get("/status", headers={"Origin": "https://someone.github.io"})
        self.assertEqual(ok.headers["access-control-allow-origin"], "https://someone.github.io")
        for other in ("https://evil.example", "https://someone.github.io.evil.example", "http://someone.github.io"):
            self.assertNotIn("access-control-allow-origin", client.get("/status", headers={"Origin": other}).headers, other)
        pre = client.options("/chat", headers={"Origin": "https://someone.github.io", "Access-Control-Request-Method": "POST",
                                               "Access-Control-Request-Headers": "content-type"})
        self.assertEqual(pre.status_code, 200)
        self.assertNotIn("access-control-allow-credentials", pre.headers)


class DevelopmentIsUnchangedTests(ReadinessCase):
    def test_without_a_snapshot_nothing_in_development_requires_production_checks(self):
        srv, client = self.server()
        code, body = self.ready(client)
        self.assertEqual(self.failed(body) - {"index_present"}, set())              # the fake index may be absent; no snapshot/pin/lifecycle is demanded
        self.assertEqual(client.get("/health").json(), {"status": "ok"})


if __name__ == "__main__":
    unittest.main()
