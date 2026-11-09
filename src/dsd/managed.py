"""Managed blocks: regions of user files that dsd owns, delimited by marker comments.

Everything outside the markers is left byte-for-byte untouched.
"""

from __future__ import annotations


def upsert_block(text: str, start: str, end: str, body: str) -> str:
    """Insert or replace the region between `start` and `end` markers with `body`."""
    block = f"{start}\n{body.rstrip()}\n{end}"
    s = text.find(start)
    e = text.find(end, s + len(start)) if s != -1 else -1
    if s != -1 and e != -1:
        return text[:s] + block + text[e + len(end):]
    if not text:
        return block + "\n"
    sep = "" if text.endswith("\n\n") else ("\n" if text.endswith("\n") else "\n\n")
    return text + sep + block + "\n"


def read_block(text: str, start: str, end: str) -> str | None:
    s = text.find(start)
    if s == -1:
        return None
    e = text.find(end, s + len(start))
    if e == -1:
        return None
    return text[s + len(start):e].strip("\n")
