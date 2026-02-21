from __future__ import annotations

import re


def naive_link_candidates(
    note_text: str, corpus: list[dict], max_suggestions: int = 5
) -> list[dict]:
    """Very lightweight link suggestions by keyword overlap.
    corpus items: {'id':..., 'title':..., 'body':...}
    Returns: [{'to': id, 'reason': 'overlap: term1, term2', 'type':'related'}]
    """
    tokens = set(w.lower() for w in re.findall(r"[A-Za-z]{4,}", note_text))
    scored = []
    for it in corpus:
        other = set(w.lower() for w in re.findall(r"[A-Za-z]{4,}", it.get("body", "")))
        overlap = tokens & other
        if overlap:
            scored.append((len(overlap), it["id"], ", ".join(list(overlap)[:3])))
    scored.sort(reverse=True)
    out = []
    for score, nid, terms in scored[:max_suggestions]:
        out.append({"to": nid, "reason": f"overlap: {terms}", "type": "related"})
    return out
