"""Frustration detection: notice when a visitor is getting annoyed, and do something about it before they leave.

Rules only (no model call, nothing added to the reply time). assess() scores the visitor's new message against the
conversation so far:

  says so          "this isn't helping", "you don't understand", "that's wrong", "useless", "I already asked" ...   3
  sounds annoyed   "frustrating", "annoyed", "ugh", "seriously?" (may be about their own problem, so weaker)        2
  asks again       the same question as an earlier one (word overlap), after it was answered or refused            2
  bot fell short   two of the last four answers refused or failed: 2; one: 1
  rated down       a thumbs-down earlier in this chat                                                                 1
  shouting         "!!" / "??" runs, or mostly CAPITALS                                                              1
  curt "no"        "no", "nope", "not that", "wrong" on their own                                                    1

FRUSTRATED_AT (3) or more is frustrated. Then (app/chat.py):
  * the model is told (FRUSTRATION_NOTE): one short, sincere acknowledgement, then the most direct answer it can give;
  * the widget gets {"type": "frustration", "reasons": [...]} once per chat and shows "Sorry this has been
    frustrating. Deep can take it from here" with Email Deep and Book a call (not after a hand-over was already sent);
  * the event is logged (events.kind 'frustration'): the console flags the chat and counts it, and the Email Deep email
    (app/escalate.py) tells Deep how the visitor felt and why.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from app.db import conn, log_event

log = logging.getLogger("mood")

FRUSTRATED_AT = 3

_SAYS = re.compile(
    r"\b(not (very )?(helpful|helping|useful|what i (asked|meant|wanted|want|need(ed)?))|"
    r"(this|that|you|it)('?re|'?s| are| is)? (useless|pointless|stupid|dumb|terrible|rubbish|garbage|hopeless|not helping|not working)|"
    r"useless|pointless|waste of (my )?time|wasting my time|"
    r"you (don'?t|do not|didn'?t|did not|never) (understand|get it|listen|read|answer)|"
    r"(already|just) (told|asked|said)|i (just )?(said|asked) (this|that|you)|"
    r"are you (even )?(listening|reading|real)|that'?s (wrong|not (it|right|true|what i))|wrong answer|"
    r"makes no sense|(does|did)n'?t (help|answer|work)|(still )?no answer|answer (my|the) (damn |bloody )?question|"
    r"(this|that|it|you)('?s|'?re| is| are) (so |really |very |getting |just )?(frustrating|annoying|irritating|ridiculous|painful)|"
    r"give up|forget it|never ?mind)", re.I)
# feelings that may be about their own business problem ("annoyed by bounced emails"): weaker on their own
_FEEL = re.compile(r"\b(frustrat\w*|annoy\w*|irritat\w*|ridiculous|fed up|wtf|ffs|smh|ugh+|come on|seriously\?)", re.I)
_CURT = re.compile(r"^\s*(no+|nope|nah|not that|not this|wrong|incorrect|that'?s not it|no that'?s wrong)[.!?]*\s*$", re.I)
_FELL_SHORT = ("refused", "error", "stopped")
_STOP = set("a an the is are was were do does did can could would should i you he she it we they me my your to of in on for "
            "and or but with about what which who how when where why there this that these those please tell me know any "
            "them not have has had get got just still again yes no ok okay really".split())

FRUSTRATION_NOTE = ("\nThe visitor seems frustrated ({why}). Begin with one short, sincere sentence that acknowledges it (no "
                    "grovelling, no exclamation marks, don't repeat the apology later), then answer as directly and briefly "
                    "as the sources allow. If the sources don't answer it, say so plainly in one sentence; the interface "
                    "offers to email Deep.")

REASON_TEXT = {"says_so": "said it isn't helping", "sounds_annoyed": "sounded annoyed", "asked_again": "asked the same thing again",
               "fell_short": "the assistant couldn't answer", "rated_down": "rated an answer not helpful",
               "shouting": "wrote in capitals or with !!", "curt": "replied with a curt no"}


def _stem(w: str) -> str:
    """Plural and simple endings off: clinics -> clinic, numbers -> number, listed -> list."""
    for end in ("ies", "es", "s", "ing", "ed"):
        if len(w) > len(end) + 3 and w.endswith(end):
            return w[: -len(end)] + ("y" if end == "ies" else "")
    return w


def _words(text: str) -> set[str]:
    return {_stem(w) for w in re.findall(r"[a-z0-9]+", (text or "").lower()) if w not in _STOP and len(w) > 1}


def _same_word(a: str, b: str) -> bool:
    """clinic = clinics, vet = veterinary, intl = international: one is the other's start (3+ letters)."""
    return a == b or (min(len(a), len(b)) >= 3 and (a.startswith(b) or b.startswith(a)))


def similar(a: str, b: str) -> bool:
    """The same question again, in other words or the same ones: at least three content words each, and most of the
    longer one's words found in the other."""
    wa, wb = _words(a), _words(b)
    if len(wa) < 3 or len(wb) < 3:
        return False
    small, big = sorted((wa, wb), key=len)
    found = sum(1 for w in small if any(_same_word(w, x) for x in big))
    # "nurse lists for Texas" then "... for Florida" is a new question: a short one must match every word, a longer one
    # may differ in one
    return found / len(big) >= 0.6 and len(small) - found <= (0 if len(small) <= 4 else 1)


def _shouting(text: str) -> bool:
    if re.search(r"[!?]{2,}", text or ""):
        return True
    letters = [ch for ch in (text or "") if ch.isalpha()]
    return len(letters) >= 12 and sum(ch.isupper() for ch in letters) / len(letters) > 0.6


def assess(message: str, turns: list[dict[str, Any]]) -> dict[str, Any]:
    """`turns`: the conversation before this message, oldest first (role visitor|assistant|team, text, outcome, feedback).
    Returns {"score", "frustrated", "reasons": [keys], "why": "plain words"}. Pure; never raises."""
    reasons: dict[str, int] = {}
    text = (message or "").strip()
    if _SAYS.search(text):
        reasons["says_so"] = 3
    elif _FEEL.search(text):
        reasons["sounds_annoyed"] = 2
    earlier = [t["text"] for t in turns if t.get("role") == "visitor"]
    if any(similar(text, e) for e in earlier[-6:]):
        reasons["asked_again"] = 2
    answers = [t for t in turns if t.get("role") == "assistant"][-4:]
    short = sum(1 for t in answers if t.get("outcome") in _FELL_SHORT)
    if short:
        reasons["fell_short"] = 2 if short >= 2 else 1
    if any((t.get("feedback") or 0) < 0 for t in turns):
        reasons["rated_down"] = 1
    if _shouting(text):
        reasons["shouting"] = 1
    if answers and _CURT.match(text):
        reasons["curt"] = 1
    score = sum(reasons.values())
    keys = sorted(reasons, key=lambda k: -reasons[k])
    return {"score": score, "frustrated": score >= FRUSTRATED_AT, "reasons": keys,
            "why": "; ".join(REASON_TEXT[k] for k in keys)}


# ---------------------------------------------------------------- the conversation side (database)
def offered_before(session_id: str | None) -> bool:
    """The card was shown in this chat already, or the visitor already asked for a person: once is enough."""
    if not session_id:
        return False
    try:
        with conn() as c:
            return bool(c.execute("""SELECT 1 FROM events WHERE session_id = %s AND kind = 'frustration' AND detail->>'offered' = 'true'
                                     UNION ALL SELECT 1 FROM leads WHERE session_id = %s AND status = 'handover' LIMIT 1""",
                                  (session_id, session_id)).fetchone())
    except Exception as e:
        log.warning("frustration lookup failed: %s", e)
        return True   # unsure: don't show the card twice


def check(session_id: str | None, message: str) -> dict[str, Any] | None:
    """The chat's call: assess the new message against this session's earlier turns (the message itself is already
    stored by app/chat.respond, so it is left out). Logs and returns the result when frustrated, with "offer" telling
    the widget whether to show the card; None otherwise. Never raises."""
    if not session_id:
        return None
    try:
        from app.escalate import conversation

        turns = conversation(session_id, 14)
        if turns and turns[-1]["role"] == "visitor":   # this message, stored just before the reply starts
            turns = turns[:-1]
        m = assess(message, turns)
        if not m["frustrated"]:
            return None
        m["offer"] = not offered_before(session_id)
        log_event("frustration", session_id, {"score": m["score"], "reasons": m["reasons"], "why": m["why"],
                                              "offered": m["offer"], "message": (message or "")[:300]})
        return m
    except Exception as e:
        log.warning("frustration check failed: %s", e)
        return None


def last(session_id: str | None) -> dict[str, Any] | None:
    """The latest frustration in a chat, for Deep's email: {"why", "message"}."""
    if not session_id:
        return None
    try:
        with conn() as c:
            row = c.execute("SELECT detail FROM events WHERE session_id = %s AND kind = 'frustration' ORDER BY id DESC LIMIT 1",
                            (session_id,)).fetchone()
        return dict(row[0]) if row else None
    except Exception as e:
        log.warning("frustration read failed: %s", e)
        return None
