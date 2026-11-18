"""OCI pilot Stage 1: minimal, in-process API protection for the public question endpoint.

Four independent guards (the fourth, SessionStore, bounds the in-memory conversations: expiry, then refusal at capacity, never eviction), all in this one dependency-free module (stdlib only, no Redis, no external service):

  * RateLimiter        sliding-window request limit per client address (monotonic clock, bounded memory, thread-safe).
  * ProtectionMiddleware  pure-ASGI: per-client rate limit (429 + Retry-After) and request-body cap (413) for the protected
                       routes only. The body is read in bounded chunks and never buffered beyond the cap.
  * ConcurrencyLimiter non-blocking permits for the expensive question work (503 + Retry-After when none is free).

What this is NOT: the limits live in the memory of ONE process. With N workers each worker keeps its own counters, so the
effective limits are N times larger and a client is not tracked across workers or restarts. They are not distributed limits.
Production therefore runs exactly one worker (see deploy/render.yaml, `--workers 1`).

Client identity is the TCP peer address. X-Forwarded-For is read ONLY when the peer is inside TG_TRUSTED_PROXIES (an explicit
allow-list of the deployment's own reverse proxies); otherwise the header is ignored, so a client cannot choose its own bucket.
No client-supplied header is ever an identity or an authentication signal.

Configuration is read once. An invalid value is never trusted: that setting falls back to its conservative default and the
problem is recorded (names only, never values) for logs and /status.
"""
import hashlib
import ipaddress
import logging
import math
import os
import threading
import time
from collections import OrderedDict, deque
from collections.abc import MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass, field

log = logging.getLogger(__name__)

# ---- defaults and accepted ranges (a value outside the range is invalid and replaced by the default) -----------------------
DEFAULT_RATE_REQUESTS = 10          # per client per window
DEFAULT_RATE_WINDOW_SECONDS = 60
DEFAULT_MAX_CLIENTS = 10_000        # tracked client entries; bounds memory
DEFAULT_MAX_REQUEST_BYTES = 8192    # a question is a short sentence; 8 KiB leaves room for non-ASCII text and JSON escaping
DEFAULT_MAX_CONCURRENT = 2
DEFAULT_MAX_SESSIONS = 500          # live conversations; a new one beyond this is refused, never swapped in for an existing one
DEFAULT_SESSION_TTL_SECONDS = 1800  # idle time after which a conversation is forgotten
MAX_SESSION_ID_LENGTH = 128         # the frontend sends a 36-character UUID
RANGES = {
    "TG_RATE_LIMIT_REQUESTS": (1, 1000),
    "TG_RATE_LIMIT_WINDOW_SECONDS": (1, 3600),
    "TG_RATE_LIMIT_MAX_CLIENTS": (100, 1_000_000),
    "TG_MAX_REQUEST_BYTES": (256, 1_048_576),
    "TG_MAX_CONCURRENT_QUESTIONS": (1, 32),
    "TG_SESSION_MAX": (1, 100_000),
    "TG_SESSION_TTL_SECONDS": (60, 86_400),
}
DEFAULTS = {
    "TG_RATE_LIMIT_REQUESTS": DEFAULT_RATE_REQUESTS,
    "TG_RATE_LIMIT_WINDOW_SECONDS": DEFAULT_RATE_WINDOW_SECONDS,
    "TG_RATE_LIMIT_MAX_CLIENTS": DEFAULT_MAX_CLIENTS,
    "TG_MAX_REQUEST_BYTES": DEFAULT_MAX_REQUEST_BYTES,
    "TG_MAX_CONCURRENT_QUESTIONS": DEFAULT_MAX_CONCURRENT,
    "TG_SESSION_MAX": DEFAULT_MAX_SESSIONS,
    "TG_SESSION_TTL_SECONDS": DEFAULT_SESSION_TTL_SECONDS,
}
BUSY_RETRY_AFTER_SECONDS = 5
GENERIC_BUSY = "The service is busy answering other questions. Please try again in a few seconds."
GENERIC_RATE = "Too many requests. Please wait a moment and try again."
GENERIC_TOO_LARGE = "The request is too large."
GENERIC_SESSIONS_FULL = "The service is at its limit of active conversations. Please try again in a few minutes."
GENERIC_BAD_REQUEST = "Invalid request."
GENERIC_ERROR = "The service is temporarily unavailable. Please try again in a minute."

PROTECTED_ROUTES = frozenset({("POST", "/chat")})   # the only expensive endpoint; nothing else is rate-limited or size-capped


class ConfigError(ValueError):
    """An invalid protection setting. The message names the variable, never its value."""


@dataclass(frozen=True)
class ProtectionConfig:
    rate_requests: int = DEFAULT_RATE_REQUESTS
    rate_window_seconds: int = DEFAULT_RATE_WINDOW_SECONDS
    max_clients: int = DEFAULT_MAX_CLIENTS
    max_request_bytes: int = DEFAULT_MAX_REQUEST_BYTES
    max_concurrent: int = DEFAULT_MAX_CONCURRENT
    max_sessions: int = DEFAULT_MAX_SESSIONS
    session_ttl_seconds: int = DEFAULT_SESSION_TTL_SECONDS
    trusted_proxies: tuple = ()          # tuple of ip_network objects; empty = trust no forwarding header at all
    client_ip_source: str = ""           # "" = the TCP peer (default); "vercel" = see CLIENT_IP_SOURCES
    problems: tuple = field(default_factory=tuple)   # names only, safe to log and to show in /status

    def public(self) -> dict:
        """Non-secret view for /status: limits and counts only, never the proxy addresses."""
        return {"rate_limit_requests": self.rate_requests, "rate_limit_window_seconds": self.rate_window_seconds,
                "max_request_bytes": self.max_request_bytes, "max_concurrent_questions": self.max_concurrent,
                "max_sessions": self.max_sessions, "session_ttl_seconds": self.session_ttl_seconds,
                "trusted_proxies_configured": len(self.trusted_proxies), "client_ip_source": self.client_ip_source or "peer",
                "problems": list(self.problems)}


def _parse_int(name: str, raw: str) -> int:
    text = raw.strip()
    if not text.isascii() or not text.isdigit():       # rejects "", "-1", "1.5", "1e3" and non-ASCII digits
        raise ConfigError(f"{name} must be a whole number")
    value = int(text)
    low, high = RANGES[name]
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}")
    return value


def parse_trusted_proxies(raw: str) -> tuple:
    """Comma-separated IPs or CIDR networks. Wildcards, hostnames and empty entries are errors: no 'trust everything' form."""
    networks = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            if (raw or "").strip():
                raise ConfigError("TG_TRUSTED_PROXIES has an empty entry")
            continue
        try:
            network = ipaddress.ip_network(item, strict=False)
        except ValueError:
            raise ConfigError("TG_TRUSTED_PROXIES has an entry that is not an IP address or CIDR network") from None
        if network.prefixlen == 0:
            raise ConfigError("TG_TRUSTED_PROXIES must not trust every address (a /0 network)")
        networks.append(network)
    return tuple(networks)


def config_from_env(environ=None) -> ProtectionConfig:
    """Read every setting; each invalid one is replaced by its default (trusted proxies: by none) and recorded as a problem."""
    env = os.environ if environ is None else environ
    values, problems = {}, []
    for name in RANGES:
        raw = env.get(name)
        if raw is None or raw.strip() == "":
            values[name] = DEFAULTS[name]
            continue
        try:
            values[name] = _parse_int(name, raw)
        except ConfigError as error:
            values[name] = DEFAULTS[name]
            problems.append(str(error))
    try:
        proxies = parse_trusted_proxies(env.get("TG_TRUSTED_PROXIES", ""))
    except ConfigError as error:
        proxies = ()
        problems.append(str(error))
    source = (env.get("TG_CLIENT_IP_SOURCE") or "").strip().lower()
    if source and source not in CLIENT_IP_SOURCES:
        problems.append("TG_CLIENT_IP_SOURCE is not a recognised value")
        source = ""
    elif source == "vercel" and not (env.get("VERCEL") or "").strip():
        # Without the platform in front, X-Forwarded-For is whatever the caller sent. Never honour it then.
        problems.append("TG_CLIENT_IP_SOURCE=vercel is only valid on Vercel (the VERCEL variable is not set)")
        source = ""
    for problem in problems:
        log.error("API protection configuration: %s (the safe default is used instead)", problem)
    return ProtectionConfig(rate_requests=values["TG_RATE_LIMIT_REQUESTS"], rate_window_seconds=values["TG_RATE_LIMIT_WINDOW_SECONDS"],
                            max_clients=values["TG_RATE_LIMIT_MAX_CLIENTS"], max_request_bytes=values["TG_MAX_REQUEST_BYTES"],
                            max_concurrent=values["TG_MAX_CONCURRENT_QUESTIONS"], max_sessions=values["TG_SESSION_MAX"],
                            session_ttl_seconds=values["TG_SESSION_TTL_SECONDS"], trusted_proxies=proxies,
                            client_ip_source=source, problems=tuple(problems))


# ---- client identity -------------------------------------------------------------------------------------------------------
def _parse_ip(text: str):
    try:
        address = ipaddress.ip_address(text.strip())
    except ValueError:
        return None
    if isinstance(address, ipaddress.IPv6Address) and address.ipv4_mapped:
        return address.ipv4_mapped
    return address


def client_key(address) -> str:
    """The bucket for an address. IPv6 clients are bucketed by /64 (one household/host controls a whole /64, so rotating the
    low bits must not buy a fresh quota). A peer that is not an IP (a Unix socket, a test client) is used as-is."""
    if address is None:
        return "unknown"
    if isinstance(address, ipaddress.IPv6Address):
        return str(ipaddress.ip_network((address, 64), strict=False))
    return str(address)


CLIENT_IP_SOURCES = ("vercel",)
UNIDENTIFIED_CLIENT = "unidentified-client"


def resolve_vercel_client(header_values) -> str:
    """Client bucket key behind Vercel's edge, where the TCP peer is the platform and not the visitor.

    Vercel documents that it overwrites X-Forwarded-For with the client's public IP and does not forward an external value
    (https://vercel.com/docs/headers/request-headers). So exactly one header holding exactly one valid IP is accepted. Anything
    else (absent, repeated, a list, unparseable) puts the request in ONE shared bucket: the limit then gets stricter for everyone,
    it never lets a caller choose its own bucket. TG_TRUSTED_PROXIES plays no part in this mode."""
    if len(header_values) != 1:
        return UNIDENTIFIED_CLIENT
    ip = _parse_ip(header_values[0].decode("latin-1").strip())
    return client_key(ip) if ip is not None else UNIDENTIFIED_CLIENT


def resolve_client(peer: str | None, forwarded_for: str | None, trusted: tuple) -> str:
    """The client bucket key. X-Forwarded-For is considered only if the TCP peer is a configured trusted proxy.

    Entries are read right to left (each proxy appends the address it saw): trusted hops are skipped and the first untrusted
    address is the client. Anything unparseable stops the walk and the peer itself is used, so a forged or malformed header
    can only ever make a client share the proxy's bucket, never escape its own."""
    peer_ip = _parse_ip(peer) if peer else None
    if peer_ip is None:
        return peer or "unknown"
    if not trusted or not forwarded_for or not any(peer_ip in network for network in trusted):
        return client_key(peer_ip)
    hops = [part for part in forwarded_for.split(",")]
    for part in reversed(hops):
        hop = _parse_ip(part)
        if hop is None:
            return client_key(peer_ip)
        if not any(hop in network for network in trusted):
            return client_key(hop)
    return client_key(_parse_ip(hops[0]) or peer_ip)    # every hop is a trusted proxy: the leftmost is the origin


# ---- rate limiter ----------------------------------------------------------------------------------------------------------
class RateLimiter:
    """Sliding-window limit: at most `limit` accepted requests per `window` seconds per key.

    * time.monotonic by default (never wall-clock: immune to clock changes); the clock is injectable for deterministic tests.
    * Each client keeps at most `limit` timestamps, and at most `max_clients` clients are tracked, so memory is bounded.
    * Expired entries are removed by a sweep at most once per window and whenever the table is full.
    * A rejected request is not recorded, so a client that backs off by Retry-After is admitted again.
    * When the table is full of live clients a NEW client is refused (fail closed: CPU is the scarce resource); clients already
      tracked keep working.
    * One lock guards every read and write, so concurrent requests cannot overshoot the limit."""

    def __init__(self, limit=DEFAULT_RATE_REQUESTS, window=DEFAULT_RATE_WINDOW_SECONDS, max_clients=DEFAULT_MAX_CLIENTS,
                 clock=time.monotonic):
        if limit < 1 or window <= 0 or max_clients < 1:
            raise ConfigError("rate limiter parameters must be positive")
        self.limit, self.window, self.max_clients, self._clock = limit, float(window), max_clients, clock
        self._hits: dict[str, deque] = {}
        self._lock = threading.Lock()
        self._last_sweep = clock()

    def _prune(self, key, now):
        hits = self._hits.get(key)
        if hits is None:
            return None
        cutoff = now - self.window
        while hits and hits[0] <= cutoff:
            hits.popleft()
        if not hits:
            del self._hits[key]
            return None
        return hits

    def _sweep_locked(self, now):
        for key in list(self._hits):
            self._prune(key, now)
        self._last_sweep = now

    def sweep(self):
        """Drop every expired entry now (also runs automatically)."""
        with self._lock:
            self._sweep_locked(self._clock())

    def tracked_clients(self) -> int:
        with self._lock:
            return len(self._hits)

    def check(self, key: str):
        """Record one request for `key`. Returns (True, 0) when allowed, else (False, whole seconds to wait, at least 1)."""
        with self._lock:
            now = self._clock()
            if now - self._last_sweep >= self.window:
                self._sweep_locked(now)
            hits = self._prune(key, now)
            if hits is None:
                if len(self._hits) >= self.max_clients:
                    self._sweep_locked(now)
                if len(self._hits) >= self.max_clients:
                    oldest = min(h[0] for h in self._hits.values())
                    return False, max(1, math.ceil(oldest + self.window - now))
                hits = self._hits[key] = deque()
            if len(hits) >= self.limit:
                return False, max(1, math.ceil(hits[0] + self.window - now))
            hits.append(now)
            return True, 0


# ---- concurrency limiter -----------------------------------------------------------------------------------------------------
class CapacityExceeded(Exception):
    """No permit is free. Carries no detail: the public message is fixed."""


class ConcurrencyLimiter:
    """At most `size` expensive requests in flight. Acquisition never waits (no queue, no blocked threads): when every permit is
    taken the caller is refused at once. The permit is a context manager, so it is released on success, on any exception and on
    BaseException such as cancellation. For a synchronous endpoint (FastAPI runs it in a worker thread) the permit follows the
    real work, not the client connection: a client that disconnects does not free the CPU, so it does not free the permit."""

    def __init__(self, size=DEFAULT_MAX_CONCURRENT):
        if size < 1:
            raise ConfigError("concurrency limit must be positive")
        self.size = size
        self._free = size
        self._lock = threading.Lock()

    @property
    def in_use(self) -> int:
        with self._lock:
            return self.size - self._free

    def try_acquire(self) -> bool:
        with self._lock:
            if self._free <= 0:
                return False
            self._free -= 1
            return True

    def release(self) -> None:
        with self._lock:
            if self._free < self.size:      # a double release can never create extra capacity
                self._free += 1

    @contextmanager
    def slot(self):
        if not self.try_acquire():
            raise CapacityExceeded()
        try:
            yield
        finally:
            self.release()


# ---- bounded conversation store ----------------------------------------------------------------------------------------------
class SessionCapacityExceeded(Exception):
    """Every session slot is held by a live (non-expired) conversation. `retry_after` is the whole seconds until the first slot
    can free up (the least recently used conversation reaching its idle limit). Carries no conversation data."""

    def __init__(self, retry_after: int = 1):
        super().__init__("session capacity reached")
        self.retry_after = max(1, int(retry_after))


class SessionStore(MutableMapping):
    """The server's in-memory conversations: bounded in count and in idle time (replaces an unbounded dict).

    Lifecycle, in this order, under one lock, on every access:
      1. Expire: a conversation idle for more than `ttl` seconds (monotonic clock) is deleted. Exactly `ttl` is still alive.
      2. Look up / create. A conversation found is returned and its idle timer restarts (valid activity refreshes it).
      3. Create only if a slot is free AFTER step 1. If every slot holds a live conversation the new one is REFUSED with
         SessionCapacityExceeded. A live conversation is never evicted, locked or not, so no existing conversation, history
         or penalty-lock flag is ever lost to make room for another.
    An expired conversation is gone for good: a later request with the same id starts a brand-new, empty conversation (and needs
    a free slot like any other new one). A request that still holds the old object when it expires may keep writing to it, but
    the store no longer references it, so nothing it writes can come back.

    Ordered by last use, so expiry only inspects the idle end: O(entries removed). Drop-in mapping (item access, setdefault, pop,
    clear). The lock guards the store's own structure; it never touches the contents of a conversation, so expiry and creation
    cannot corrupt one."""

    def __init__(self, max_sessions=DEFAULT_MAX_SESSIONS, ttl=DEFAULT_SESSION_TTL_SECONDS, clock=time.monotonic):
        if max_sessions < 1 or ttl <= 0:
            raise ConfigError("session store parameters must be positive")
        self.max_sessions, self.ttl, self._clock = max_sessions, float(ttl), clock
        self._data: OrderedDict = OrderedDict()      # key -> [last_used, session]
        self._lock = threading.Lock()

    def _expire_locked(self, now):
        while self._data:
            key = next(iter(self._data))
            if now - self._data[key][0] <= self.ttl:
                break
            del self._data[key]

    def _put_locked(self, key, value, now):
        if key in self._data:
            self._data[key][1] = value
            self._data[key][0] = now
        else:
            if len(self._data) >= self.max_sessions:     # expiry already ran: these are all live conversations
                oldest = self._data[next(iter(self._data))][0]
                raise SessionCapacityExceeded(math.ceil(oldest + self.ttl - now))
            self._data[key] = [now, value]
        self._data.move_to_end(key)

    def __getitem__(self, key):
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            entry = self._data[key]                  # KeyError when absent or expired
            entry[0] = now
            self._data.move_to_end(key)
            return entry[1]

    def __setitem__(self, key, value):
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            self._put_locked(key, value, now)

    def __delitem__(self, key):
        with self._lock:
            self._expire_locked(self._clock())
            del self._data[key]

    def setdefault(self, key, default=None):
        with self._lock:
            now = self._clock()
            self._expire_locked(now)
            if key in self._data:
                entry = self._data[key]
                entry[0] = now
                self._data.move_to_end(key)
                return entry[1]
            self._put_locked(key, default, now)
            return default

    def __contains__(self, key):
        with self._lock:
            self._expire_locked(self._clock())
            return key in self._data

    def __iter__(self):
        with self._lock:
            self._expire_locked(self._clock())
            return iter(list(self._data))

    def __len__(self):
        with self._lock:
            self._expire_locked(self._clock())
            return len(self._data)

    def clear(self):
        with self._lock:
            self._data.clear()


# ---- ASGI middleware -----------------------------------------------------------------------------------------------------------
class _Tooling:
    """Counters and throttled logging. Never logs a client address, a message or a body: only a short digest of the bucket."""

    def __init__(self):
        self.counts = {"rate_limited": 0, "too_large": 0, "bad_request": 0, "errors": 0}
        self._last_log: dict[str, float] = {}
        self._lock = threading.Lock()

    def note(self, kind: str, key: str = "") -> None:
        with self._lock:
            self.counts[kind] = self.counts.get(kind, 0) + 1
            now = time.monotonic()
            if now - self._last_log.get(kind, -1e9) < 60:
                return
            self._last_log[kind] = now
            count = self.counts[kind]
        digest = hashlib.sha256(key.encode()).hexdigest()[:8] if key else "-"
        log.warning("API protection: %s (client %s, %d so far)", kind, digest, count)


async def _send_json(send, status: int, detail: str, headers=()):
    body = ('{"detail":"%s"}' % detail).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            *[(k.encode(), v.encode()) for k, v in headers]]})
    await send({"type": "http.response.body", "body": body})


class ProtectionMiddleware:
    """Pure ASGI (no BaseHTTPMiddleware: it would buffer or wrap the stream). Protected routes only; every other path, method and
    scope type passes straight through untouched. Install it BEFORE the CORS middleware so CORS wraps it and the browser
    frontend can read a 429 or 413."""

    def __init__(self, app, config: ProtectionConfig, limiter: RateLimiter | None = None, routes=PROTECTED_ROUTES):
        self.app, self.config, self.routes = app, config, routes
        self.limiter = limiter or RateLimiter(config.rate_requests, config.rate_window_seconds, config.max_clients)
        self.tooling = _Tooling()

    def _client(self, scope) -> str:
        if self.config.client_ip_source == "vercel":
            return resolve_vercel_client([v for k, v in scope.get("headers", ()) if k == b"x-forwarded-for"])
        client = scope.get("client")
        peer = client[0] if client else None
        forwarded = None
        if self.config.trusted_proxies:
            values = [v.decode("latin-1") for k, v in scope.get("headers", ()) if k == b"x-forwarded-for"]
            forwarded = ", ".join(values) if values else None
        return resolve_client(peer, forwarded, self.config.trusted_proxies)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or (scope["method"], scope["path"]) not in self.routes:
            return await self.app(scope, receive, send)
        key = "unknown"
        try:
            key = self._client(scope)
            allowed, retry_after = self.limiter.check(key)
            if not allowed:
                self.tooling.note("rate_limited", key)
                return await _send_json(send, 429, GENERIC_RATE, [("Retry-After", str(retry_after))])
            body = await self._read_body(scope, receive, send, key)
            if body is None:
                return
        except Exception as error:      # the guard itself failed: refuse (closed) without leaking anything
            self.tooling.note("errors", key)
            log.error("API protection failure: %s", type(error).__name__)
            return await _send_json(send, 503, GENERIC_ERROR, [("Retry-After", str(BUSY_RETRY_AFTER_SECONDS))])
        chunks = [body]

        async def replay():
            if chunks:
                return {"type": "http.request", "body": chunks.pop(), "more_body": False}
            return await receive()      # after the body: disconnect events and nothing else

        await self.app(scope, replay, send)

    async def _read_body(self, scope, receive, send, key):
        """The whole body if it is within the cap, else None after a 413/400 has been sent. At most cap+1 bytes are ever held."""
        cap = self.config.max_request_bytes
        declared = [v for k, v in scope.get("headers", ()) if k == b"content-length"]
        if declared:
            text = declared[-1].decode("latin-1").strip()
            if len(declared) > 1 or not text.isascii() or not text.isdigit():
                self.tooling.note("bad_request", key)
                await _send_json(send, 400, GENERIC_BAD_REQUEST)
                return None
            if int(text) > cap:         # refuse before reading a single body byte
                self.tooling.note("too_large", key)
                await _send_json(send, 413, GENERIC_TOO_LARGE, [("Connection", "close")])
                return None
        received, parts = 0, []
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return None
            chunk = message.get("body", b"")
            received += len(chunk)
            if received > cap:          # chunked or understated Content-Length: stop reading at the first excess chunk
                self.tooling.note("too_large", key)
                await _send_json(send, 413, GENERIC_TOO_LARGE, [("Connection", "close")])
                return None
            parts.append(chunk)
            if not message.get("more_body", False):
                return b"".join(parts)
