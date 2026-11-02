"""Compare side by side: two or three of Deep's companies (or their products) in one table, from their own pages.

detect(query)          -> {"subjects": [...], "aspect": str | None} when the visitor asks to compare ("compare LakeB2B and
                          SPAN", "Ampliz vs Lake B2B", "difference between X and Y", "which is better, X or Y?"); None otherwise.
                          Known names (the companies with a page on deependhq.com and the company websites switched on in
                          Console → Knowledge, with their aliases) are matched first; otherwise the words around "vs" /
                          "and" after the cue are taken as they are ("intent data vs technographics").
balanced_hits(...)     -> the passages for each side searched on their own and interleaved, so a table is never one company's
                          pages against nothing; the normal search for the whole question still runs first (app/chat.py).
COMPARE_NOTE           -> the model writes one or two sentences and an answer card with a Table (one column per subject,
                          rows only for aspects the sources cover, "-" for a side the sources don't say), no "better" verdict
                          unless the sources say so. Answer cards (app/ui_cards.py) are what draws the table.
options()              -> for the widget's Compare picker (GET /compare/options): the companies that can be compared right
                          now (switched-off websites are left out) and the aspects to compare on.

Switch: COMPARE_ENABLED (on). Rules only for spotting a comparison; no extra model call.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.config import settings

log = logging.getLogger("compare")

MAX_SUBJECTS = 3
PER_SIDE = 3
ASPECTS = ["Services", "Data & coverage", "Industries served", "Who it's for", "How to get started"]

_CUE = re.compile(r"\b(compare|comparing|comparison|vs\.?|versus|difference(s)? between|differ(s|ence)? from|"
                  r"how (is|does) .{2,40} (differ|different)|better(,| than)|which (one )?(is|should i|would you) (better|pick|choose|go with))\b", re.I)
_ALIASES = {"lake b2b": ["lakeb2b", "lake b2b", "lake-b2b"], "span global services": ["span global services", "spanglobalservices", "span global", "span"],
            "ip momentum": ["ip momentum", "ipmomentum"], "recruit champ": ["recruit champ", "recruitchamp"],
            "champions accelerator": ["champions accelerator"], "champions infometrics": ["champions infometrics", "infometrics"],
            "champions club": ["champions club"], "champ.fit": ["champ.fit", "champfit", "champ fit"], "health.fit": ["health.fit", "healthfit"],
            "infratech": ["infratech", "infra tech"], "cirralogix": ["cirralogix"], "ampliz": ["ampliz"]}
_ASPECT_WORDS = {"Services": r"services?|offer(s|ings?)?|products?|solutions?", "Data & coverage": r"data|coverage|records|contacts|database",
                 "Industries served": r"industr(y|ies)|sectors?|verticals?", "Who it's for": r"who (is it|it's|its) for|customers|audience|clients",
                 "How to get started": r"get(ting)? started|onboarding|how to (start|buy)", "Pricing": r"pric(e|es|ing)|cost"}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9.]+", " ", (s or "").lower()).strip()


def _known() -> list[dict[str, Any]]:
    """[{"name", "aliases"}]: companies on deependhq.com (when it is on) and the company websites switched on."""
    from app import knowledge
    from app.rag.retrieve import company_names

    names: list[str] = []
    try:
        if knowledge.own_enabled():
            names += company_names()
        names += [t.get("name") or t["slug"] for t in knowledge.active_sites()]
    except Exception as e:
        log.warning("compare names failed: %s", e)
    out: dict[str, dict[str, Any]] = {}   # one entry per company: "Lake B2B" (its deependhq.com page) = "LakeB2B" (its website)
    for n in names:
        squashed = _norm(n).replace(" ", "")
        canon = next((k for k, al in _ALIASES.items() if squashed in {a.replace(" ", "").replace("-", "") for a in al}), _norm(n))
        if canon not in out:
            out[canon] = {"name": n, "aliases": sorted(set(_ALIASES.get(canon, []) + [_norm(n)]), key=len, reverse=True)}
    return list(out.values())


def options() -> dict[str, Any]:
    return {"enabled": settings.compare_enabled, "companies": [k["name"] for k in _known()], "aspects": ASPECTS}


def _aspect(query: str) -> str | None:
    for name, rx in _ASPECT_WORDS.items():
        if re.search(r"\b(" + rx + r")\b", query, re.I):
            return name
    return None


def _free_subjects(query: str) -> list[str]:
    """"compare X and Y", "X vs Y", "difference between X and Y": the words on each side, as typed."""
    q = re.sub(r"[?!]+", " ", query).strip()
    q = re.sub(r"^.*?\bwhich (one )?(is|should i|would you) (better|pick|choose|go with)\b[:,]?\s*", "", q, flags=re.I)
    d = re.search(r"(?:how (?:is|does)\s+)?(.+?)\s+(?:differ(?:s|ent)?|compare)\s+(?:from|to|with)\s+(.+)", q, re.I)
    if d:
        q = f"{d.group(1)} vs {d.group(2)}"
    m = re.search(r"(?:compare|comparing|difference(?:s)? between|comparison (?:of|between))\s+(.+)", q, re.I)
    body = m.group(1) if m else q
    body = re.split(r"\b(?:side by side|in terms of|for|on|regarding|when it comes to)\b|[:;]", body, maxsplit=1, flags=re.I)[0]
    parts = [p.strip(" ,.-") for p in re.split(r"\s+(?:vs\.?|versus|and|or|with|to)\s+|,", body, flags=re.I) if p.strip(" ,.-")]
    parts = [re.sub(r"^(the|a|an|between|which is better,?)\s+", "", p, flags=re.I) for p in parts]
    parts = [p for p in parts if 2 <= len(p) <= 60 and len(p.split()) <= 6]
    return parts[:MAX_SUBJECTS] if len(parts) >= 2 else []


def detect(query: str) -> dict[str, Any] | None:
    if not settings.compare_enabled or not query or not _CUE.search(query):
        return None
    low = " " + _norm(query) + " "
    found: list[tuple[int, str]] = []
    for k in _known():
        for a in k["aliases"]:
            i = low.find(" " + a + " ")
            if i >= 0:
                found.append((i, k["name"]))
                break
    found.sort()
    subjects = list(dict.fromkeys(n for _, n in found))[:MAX_SUBJECTS]
    if len(subjects) < 2:
        subjects = _free_subjects(query)
    if len(subjects) < 2:
        return None
    rest = query
    for s in subjects:   # "intent data vs technographics" is not about the "Data" aspect
        rest = re.sub(re.escape(s), " ", rest, flags=re.I)
    return {"subjects": subjects, "aspect": _aspect(rest)}


def balanced_hits(c: dict[str, Any], search, embed, today=None) -> list:
    """The best PER_SIDE passages for each subject (searched as "<subject> <aspect>"), interleaved. `search` and `embed` are
    app.rag.retrieve.search and the embedder (passed in so the chat's patched versions are used)."""
    sides = []
    for s in c["subjects"]:
        q = f"{s} {c.get('aspect') or 'services and offerings'}"
        try:
            hits = search(q, vec=embed(q), today=today)
        except Exception as e:
            log.warning("compare search for %s failed: %s", s, e)
            hits = []
        name = _norm(s)
        own = [h for h in hits if name.split(" ")[0] in _norm(f"{h.title} {h.url} {(h.metadata or {}).get('site') or ''} {h.text[:300]}")]
        sides.append((own or hits)[:PER_SIDE])
    out, seen = [], set()
    for i in range(PER_SIDE):
        for side in sides:
            if i < len(side) and side[i].text not in seen:
                seen.add(side[i].text)
                out.append(side[i])
    return out


def note(c: dict[str, Any]) -> str:
    subj = " and ".join(c["subjects"]) if len(c["subjects"]) == 2 else ", ".join(c["subjects"][:-1]) + " and " + c["subjects"][-1]
    on = f" on {c['aspect'].lower()}" if c.get("aspect") else ""
    return (f"\nCOMPARISON: the visitor wants {subj} compared side by side{on}. Write one or two short sentences, then the answer "
            f"card with a Table whose first column is the aspect and then one column per subject in this order: "
            f"{', '.join(c['subjects'])}. Use only rows the sources cover for at least one side (what they offer, data or coverage, "
            "industries, who it's for, how to get started); a side the sources don't cover gets a dash (-). Do not say which is "
            "better unless a source says so; if the visitor asked which to choose, say it depends on their need and offer a call "
            "with Deep. Cite the sources in the prose as usual. Pricing is never in the table: say Deep can give exact options.")
