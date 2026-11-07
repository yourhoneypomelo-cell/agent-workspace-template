"""Saved user messages: the ID each one keeps in its transcript heading, and which ones need no record.

Since 3.9 a message gets its ID when it is first saved, and the ID is written in its heading, so writing the
transcript again, after a change of redaction rules or from the host's own copy of the turn, keeps it. The ID covers
the transcript and the message number besides the text, so the same sentence in two sessions is reconciled in each.
A message saved by 3.8 or older has no ID in its heading; its ID is the hash of its text alone, as before, so the
reconcile rows written for it stay valid. The two kinds tell apart by length: 10 hex digits before 3.9, 12 since.
"""
from __future__ import annotations

import re

from .core import sha
from .schema import HEADING_NOTE

ENTRY_RE = re.compile(r'^## (\d+)\. (user|assistant)(' + HEADING_NOTE + r')\n\n(.*?)(?=^## \d+\. (?:user|assistant)'
                      + HEADING_NOTE + r'\n|\Z)', re.M | re.S)
ID_RE = re.compile(r' \[(m[0-9a-f]{10}(?:[0-9a-f]{2})?)\]$')
STAMP_RE = re.compile(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ')
# Messages that carry no requirement: continuation prompts, acknowledgements, thanks. Yes, no, 是, 对, 可以 and 行
# can answer a question, so since 3.9 they are reconciled like other messages; messages saved before keep the old rule.
ROUTINE = re.compile(r'^(?:(?:继续|继续吧|接着|好的?|好|ok(?:ay)?|嗯|谢谢|thanks?|continue|go on|next|'
                     r'完美丝滑接续任务|完美接续中断任务|继续中断任务|继续未完成任务)[。.!！,，\s]*)+$', re.I)
ROUTINE_BEFORE_39 = re.compile(r'^(?:(?:继续|继续吧|接着|好的?|好|行|可以|ok(?:ay)?|yes|no|是的?|对|嗯|谢谢|thanks?|continue|'
                               r'go on|next|完美丝滑接续任务|完美接续中断任务|继续中断任务|继续未完成任务)[。.!！,，\s]*)+$', re.I)
ROUTINE_MAX = 40
# A typed text this short may be part of any message, so it is matched to the host's copy only when equal.
CONTAINED_MIN = 8


def normal(text: str) -> str:
    return ' '.join(text.split())


def old_id(body: str) -> str:
    return 'm' + sha(normal(body).encode('utf-8'))[:10]


def new_id(rel: str, number: int, body: str) -> str:
    return 'm' + sha(f'{rel}\n{number}\n{normal(body)}'.encode('utf-8'))[:12]


def routine(mid: str, body: str) -> bool:
    rule = ROUTINE_BEFORE_39 if len(mid) == 11 else ROUTINE
    return len(body) <= ROUTINE_MAX and bool(rule.match(body))


def entries(text: str) -> list:
    """(number, role, stamp, ID, body) for each message of a transcript. Assistant messages have no ID."""
    found = []
    for match in ENTRY_RE.finditer(text):
        note, body = match.group(3), match.group(4).strip()
        stored, stamp = ID_RE.search(note), STAMP_RE.search(note)
        mid = (stored.group(1) if stored else old_id(body)) if match.group(2) == 'user' and body else None
        found.append((int(match.group(1)), match.group(2), stamp.group(0) if stamp else '', mid, body))
    return found


def carry(old_text: str, rel: str, users: list) -> list:
    """IDs for the user messages of a transcript written again, given in order as (number, body, stamp). A message
    saved before keeps its ID. It is found in order: by its text, by the host's time, or as the typed text the
    prompt hook saved, which the host's copy may extend. The others get new IDs."""
    old = [(stamp, mid, normal(body)) for _, _, stamp, mid, body in entries(old_text) if mid]
    ids, start = [], 0
    for number, body, stamp in users:
        text = normal(body)
        hit = next((i for i in range(start, len(old)) if old[i][2] == text or (stamp and old[i][0] == stamp) or (
            min(len(old[i][2]), len(text)) >= CONTAINED_MIN and (old[i][2] in text or text in old[i][2]))), None)
        if hit is None:
            ids.append(new_id(rel, number, body))
        else:
            ids.append(old[hit][1])
            start = hit + 1
    return ids
