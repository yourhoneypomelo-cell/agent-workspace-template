"""Retired rows a new row may repeat: an exact match, and the nearest ones for the agent to judge (U15)."""
from __future__ import annotations

import re
from pathlib import Path

from . import tables
from .schema import NONE


def _words(text: str) -> set:
    from .rows import _words as words
    return words(text)


RETIRE_AS = {'requirements': 'removed', 'features': 'removed', 'decisions': 'rejected'}


def _norm(text: str) -> str:
    return re.sub(r'[\W_]+', '', text.lower())


def retired_match(root: Path, t, text: str) -> list:
    """Retired rows of the same table with the same text, ignoring case, spaces and punctuation. Exact on purpose:
    looser similarity found 0 to 8.5 percent of reworded Chinese rows and gave false hints on templated rows."""
    if t.key not in ('requirements', 'features', 'decisions'):
        return []
    key = _norm(text)
    found = [(r['ID'], r['Status'], r.get('Reason', NONE)) for r in tables.rows(root, t)
             if r['Status'] in t.retired and _norm(r[t.summary]) == key]
    found += [(r['ID'], r['Status'], r['Reason']) for r in tables.closed_rows(root)
              if r['ID'][:1] == t.prefix and _norm(r['Summary']) == key]
    return found[:2] if len(key) >= 6 else []


def retired_nearest(root: Path, t, text: str, skip: set) -> list:
    """The three retired rows of the same table whose words overlap the new text most, best first. No threshold:
    the agent judges the meaning. A rewrite's original was among the three in 83 to 92 percent of 177 Chinese and
    87 to 97 percent of 450 English trials with 5 to 20 retired rows; a threshold found 0 to 27 percent."""
    if t.key not in ('requirements', 'features', 'decisions'):
        return []
    rows = [(r['ID'], r['Status'], r[t.summary], r.get('Reason', NONE)) for r in tables.rows(root, t) if r['Status'] in t.retired]
    rows += [(r['ID'], r['Status'], r['Summary'], r['Reason']) for r in tables.closed_rows(root) if r['ID'][:1] == t.prefix]
    mine = _words(text)
    scored = []
    for rid, status, summary, reason in rows:
        theirs = _words(summary)
        shared = mine & theirs
        if rid not in skip and shared:
            scored.append((len(shared) / len(mine | theirs), rid, status, summary, reason))
    return sorted(scored, reverse=True)[:3]
