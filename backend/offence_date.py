"""Offence-date routing for versioned legal text.

The law that applies is the law on the offence date, not today's. This module only classifies dates and
filters chunks by validity metadata. It never decides what a chunk means and never adds permissions.

Bands (from the project's legal baseline, not legal advice):
  pre_2019_09_01            offence before 1 September 2019
  2019_09_01_to_2026_08_14  1 September 2019 to 14 August 2026 inclusive
  from_2026_08_15           15 August 2026 onward (Act 8 of 2026, S.O. 4100(E) commencement)

Chunks carry integer yyyymmdd `valid_from` and `valid_to` (open-ended = OPEN_ENDED). Chroma cannot compare
strings or filter nulls, hence integers and a sentinel. Both ends are inclusive. Chunks with no usable
validity metadata are never temporal evidence: route_documents() returns them separately as `unverified`
(kept for context, not dropped) and the caller must label them as such.
"""

from __future__ import annotations

import dataclasses
import datetime as dt
import re

BAND_PRE_2019 = "pre_2019_09_01"
BAND_2019_2026 = "2019_09_01_to_2026_08_14"
BAND_POST_2026 = "from_2026_08_15"
BAND_UNSPECIFIED = "unspecified"

AMENDMENT_ACT_2019_DATE = dt.date(2019, 9, 1)
ACT_8_2026_DATE = dt.date(2026, 8, 15)
OPEN_ENDED = 99991231

_ISO = re.compile(r"^(\d{4})-(\d{1,2})-(\d{1,2})$", re.ASCII)
_DMY = re.compile(r"^(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})$", re.ASCII)


class OffenceDateError(ValueError):
    pass


def parse_offence_date(value, today: dt.date | None = None) -> dt.date | None:
    """None for a missing value. Raises OffenceDateError for anything unparseable or in the future."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, dt.datetime):
        value = value.date()
    if isinstance(value, dt.date):
        d = value
    elif isinstance(value, str):
        s = value.strip()
        try:
            if (m := _ISO.match(s)):
                d = dt.date(int(m[1]), int(m[2]), int(m[3]))
            elif (m := _DMY.match(s)):
                d = dt.date(int(m[3]), int(m[2]), int(m[1]))
            else:
                raise OffenceDateError(f"unrecognised date {value!r}; use YYYY-MM-DD or DD-MM-YYYY")
        except OffenceDateError:
            raise
        except ValueError as exc:
            raise OffenceDateError(f"invalid calendar date {value!r}") from exc
    else:
        raise OffenceDateError(f"unsupported date type {type(value).__name__}")
    if d > (today or dt.date.today()):
        raise OffenceDateError("offence date is in the future")
    if d.year < 1989:
        raise OffenceDateError("offence date precedes the period this system covers")
    return d


def band_for(d: dt.date | None) -> str:
    if d is None:
        return BAND_UNSPECIFIED
    if d < AMENDMENT_ACT_2019_DATE:
        return BAND_PRE_2019
    if d < ACT_8_2026_DATE:
        return BAND_2019_2026
    return BAND_POST_2026


def date_int(d: dt.date) -> int:
    return d.year * 10000 + d.month * 100 + d.day


def chroma_where(d: dt.date) -> dict:
    """Metadata filter for chunks valid on `d`. Excludes unversioned chunks. Not used by /chat yet: it routes every
    candidate with route_documents(), which also sees (and refuses) unversioned chunks."""
    x = date_int(d)
    return {"$and": [{"valid_from": {"$lte": x}}, {"valid_to": {"$gte": x}}]}


def _valid_yyyymmdd(n: int) -> bool:
    try:
        dt.date(n // 10000, n // 100 % 100, n % 100)
        return True
    except ValueError:
        return n == OPEN_ENDED


def is_yyyymmdd(n) -> bool:
    """True for an int (not bool) that is a real calendar date as yyyymmdd, year 1900 or later. 99991231 qualifies."""
    return isinstance(n, int) and not isinstance(n, bool) and n >= 19000101 and _valid_yyyymmdd(n)


def _meta_int(metadata: dict, key: str):
    v = metadata.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


# Per-chunk temporal status. Only VALID is temporal evidence; every other status is unverified.
VALID = "valid"
NOT_VALID = "not_valid"
UNVERSIONED = "unversioned"          # no validity metadata at all
MALFORMED = "malformed_validity"     # metadata present but not a usable yyyymmdd range
DATE_NOT_GIVEN = "date_not_given"    # no offence date, so nothing can be checked
UNVERIFIED_STATUSES = frozenset({UNVERSIONED, MALFORMED, DATE_NOT_GIVEN})


def temporal_status(metadata: dict, d: dt.date | None) -> str:
    """Status of one chunk's validity range on offence date d (inclusive at both ends)."""
    if d is None:
        return DATE_NOT_GIVEN
    start, end = _meta_int(metadata, "valid_from"), _meta_int(metadata, "valid_to")
    if start is None and end is None:
        return UNVERSIONED
    if start is None or end is None or start > end or not _valid_yyyymmdd(start) or not _valid_yyyymmdd(end):
        return MALFORMED
    x = date_int(d)
    return VALID if start <= x <= end else NOT_VALID


def in_force_today(metadata: dict, today: dt.date | None = None) -> bool:
    """May this chunk be used as CURRENT law (no offence date given)? An unversioned chunk keeps today's behaviour. A
    versioned chunk must cover today, so an expired text and a text not yet in force are not served as current. A malformed
    range is refused: a data defect is never read as 'in force'."""
    return temporal_status(metadata, today or dt.date.today()) in (VALID, UNVERSIONED)


@dataclasses.dataclass(frozen=True)
class TemporalRouting:
    """Result of routing chunks by offence date.
    authoritative: chunks whose dated range covers the offence date. The only temporal evidence.
    unverified:    chunks kept for context but NOT evidence of the law on the offence date.
    dropped:       chunks whose dated range excludes the offence date.
    """
    authoritative: tuple
    unverified: tuple
    dropped: int
    offence_date_given: bool
    conflicts: int = 0   # provisions for which two different file versions both claim the date (neither is evidence)

    @property
    def notes(self) -> tuple:
        out = []
        if not self.offence_date_given:
            out.append(DATE_REQUIRED_NOTE)
        elif self.unverified:
            out.append(UNVERSIONED_NOTE)
            if self.conflicts:
                out.append(CONFLICT_NOTE)
            if not self.authoritative:
                out.append(NO_DATED_TEXT_NOTE)
        return tuple(out)

    @property
    def temporally_established(self) -> bool:
        """True only when an offence date was given and at least one chunk is dated to cover it."""
        return self.offence_date_given and bool(self.authoritative)


def route_documents(docs, d: dt.date | None) -> TemporalRouting:
    """Split chunks by temporal status. Unversioned, malformed and (with no date) all chunks go to `unverified`;
    callers must not present them as the law applicable on the offence date."""
    auth, unver, dropped = [], [], 0
    for doc in docs:
        status = temporal_status(getattr(doc, "metadata", None) or {}, d)
        if status == VALID:
            auth.append(doc)
        elif status == NOT_VALID:
            dropped += 1
        else:
            unver.append(doc)
    # Overlapping versions: if two different files of one source both claim this date for the same provision, the ranges
    # contradict each other and the text for that provision is not established. Neither version is used.
    versions: dict = {}
    for doc in auth:
        m = doc.metadata
        if m.get("manifest_id") and m.get("provision_id"):
            versions.setdefault((m["manifest_id"], m["provision_id"]), set()).add(m.get("sha256"))
    clash = {k for k, shas in versions.items() if len(shas) > 1}
    if clash:
        unver += [x for x in auth if (x.metadata.get("manifest_id"), x.metadata.get("provision_id")) in clash]
        auth = [x for x in auth if (x.metadata.get("manifest_id"), x.metadata.get("provision_id")) not in clash]
    return TemporalRouting(tuple(auth), tuple(unver), dropped, d is not None, len(clash))


DATE_REQUIRED_NOTE = (
    "The law that applies depends on the date of the offence. No offence date was given, so nothing here is "
    "verified as the law for a particular offence date."
)
UNVERSIONED_NOTE = (
    "Some of the text used here carries no usable validity dates. It has not been verified as the law on the "
    "offence date and is not temporal evidence."
)
CONFLICT_NOTE = (
    "Two versions of the same provision both claim to apply on the offence date, so neither is used as the law for that date."
)
NO_DATED_TEXT_NOTE = (
    "No text dated to cover the offence date was found, so the law on that date is not established here."
)
