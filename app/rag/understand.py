"""Reading the visitor's message before retrieval: small talk, greetings in front of a question, and follow-ups.

A vector search cannot answer "hello" or "tell me more": the first has nothing to find, the second finds a random
entry. So
  * pure small talk (a greeting, thanks, goodbye, "ok", "who are you", "what can you do") gets a fixed, friendly
    reply without retrieval or a refusal (smalltalk_kind / smalltalk_reply);
  * a greeting in front of a question is dropped before searching ("hi, who is Deep?" searches "who is Deep?");
  * a follow-up that leans on the conversation ("tell me more", "what about his second company?") is rewritten into a
    standalone search query with one short model call, falling back to the previous question plus this one.
"""
from __future__ import annotations

import logging
import re

from app.config import settings

log = logging.getLogger("understand")

_GREETING = r"(hi+|hey+|hello+|hell?o there|hiya|howdy|yo|sup|greetings|good (morning|afternoon|evening|day)|namaste|namaskar)"
_THANKS = r"(thanks?( you)?( so much| a lot| very much)?|thank u|thx|ty|cheers|much appreciated|appreciate it|great,? thanks?)"
_BYE = r"(bye+|goodbye|good bye|see you|see ya|cya|take care|good night|that'?s all|that is all|nothing else)"
_ACK = r"(ok+|okay|k|cool|nice|great|awesome|perfect|got it|i see|alright|all right|sounds good|makes sense|fine|sure|yes|yeah|yep|no|nope|hmm+|interesting|wow|lol|haha+)"
_HOW_ARE_YOU = r"(how are you( doing)?|how'?s it going|how do you do|what'?s up|whats up)"
_IDENTITY = r"(who are you|what are you|are you (a |an )?(bot|ai|human|robot|real person|person)|is this (a )?(bot|ai|human)|your name|what'?s your name)"
_CAPABILITIES = r"(what can you do|what do you do|how can you help( me)?|what can i ask( you)?|help|what is this|what'?s this|how does this work)"

_END = r"[\s!.?,:;)(\-—–~*^_'\"🙂😊👋🙏👍]*"
_KINDS = [
    ("greeting", re.compile(rf"^{_GREETING}( (there|deep|team|all|everyone|bot))?{_END}$", re.I)),
    ("how_are_you", re.compile(rf"^({_GREETING}[\s,!.]*)?{_HOW_ARE_YOU}( today)?{_END}$", re.I)),
    ("thanks", re.compile(rf"^({_ACK}[\s,!.]*)?{_THANKS}( deep| bot)?{_END}$", re.I)),
    ("bye", re.compile(rf"^({_THANKS}[\s,!.]*)?{_BYE}{_END}$", re.I)),
    ("identity", re.compile(rf"^({_GREETING}[\s,!.]*)?{_IDENTITY}{_END}$", re.I)),
    ("capabilities", re.compile(rf"^({_GREETING}[\s,!.]*)?{_CAPABILITIES}{_END}$", re.I)),
    ("ack", re.compile(rf"^{_ACK}([\s,!.]+{_ACK})*{_END}$", re.I)),
]
_LEADING_GREETING = re.compile(rf"^{_GREETING}( (there|deep|team|all|everyone))?[\s,!.:;\-—–]+(?=\S)", re.I)

_TOPICS = ("what Deep is building right now, the daily build-in-public log, the twelve Champions Group companies "
           "(Lake B2B, Ampliz, Champions Accelerator and the rest), and the tools he uses")
SMALLTALK_REPLIES = {
    "greeting": f"Hi! I'm Deep's assistant. I can tell you about {_TOPICS}, or book you a call with Deep. What would you like to know?",
    "how_are_you": f"Doing well, thanks for asking! I can tell you about {_TOPICS}, or book you a call with Deep. What's on your mind?",
    "thanks": "You're welcome! Anything else you'd like to know about Deep or his companies? I can also book you a call with him.",
    "bye": "Thanks for stopping by! If you'd like to talk to Deep, you can book a call any time right here.",
    "identity": (f"I'm the assistant on deependhq.com, Sreedeep Surapaneni's (Deep's) build-in-public site. I'm an AI, and I "
                 f"answer from what's published on the site: {_TOPICS}. I can also book you a call with Deep."),
    "capabilities": (f"I can answer questions about {_TOPICS}, using what's published on deependhq.com, and I can book you a "
                     "call with Deep right here in the chat. Try \"What is Deep working on?\" or \"Book a call with Deep\"."),
    "ack": "Anything else you'd like to know about Deep, his companies or the log? I can also book you a call with him.",
}

# instructions for the model when a non-English visitor makes small talk (the fixed replies above are English)
SMALLTALK_PROMPT = (
    "You are the assistant on deependhq.com, the build-in-public site of Sreedeep Surapaneni (\"Deep\"), Group CMO at "
    "Champions Group and CEO of Champions Accelerator. The visitor is making small talk (a greeting, thanks, goodbye, or "
    "asking who you are or what you can do). Reply warmly in one or two short sentences, in the visitor's language. Say "
    f"you can tell them about {_TOPICS}, or book them a call with Deep. Do not state any other facts."
)


def smalltalk_kind(text: str) -> str | None:
    """'greeting', 'thanks', 'bye', 'ack', 'how_are_you', 'identity' or 'capabilities' when the WHOLE message is small talk."""
    t = re.sub(r"\s+", " ", (text or "").strip())
    if not t or len(t) > 80:
        return None
    for kind, rx in _KINDS:
        if rx.match(t):
            return kind
    return None


def answers_a_question(kind: str | None, history: list[dict]) -> bool:
    """'yes', 'ok', 'thanks' right after the assistant asked something are answers, not small talk."""
    if kind not in ("ack", "thanks", "bye"):
        return False
    for m in reversed(history or []):
        if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str):
            return "?" in m["content"].strip()[-200:]
    return False


def smalltalk_reply(kind: str) -> str:
    return SMALLTALK_REPLIES.get(kind, SMALLTALK_REPLIES["greeting"])


def strip_greeting(text: str) -> str:
    """'Hi Deep, who are you working with?' -> 'who are you working with?'. Unchanged when nothing follows."""
    t = (text or "").strip()
    out = _LEADING_GREETING.sub("", t, count=1).strip()
    return out or t


_FOLLOW_UP = re.compile(
    r"^(and|but|also|so|then|what about|how about|and what|why|why not|how so|really|tell me more|more|go on|continue|"
    r"elaborate|explain( more| that| it)?|example|examples|such as|like what|which (one|ones)|when was that|where was that)\b"
    r"|\b(tell me more|more (about|on|detail|details)|that one|this one|the first|the second|the last|the other|"
    r"those|these|it|its|it's|that|this|them|they|their|there)\b", re.I)


def _last_user(history: list[dict]) -> str:
    for m in reversed(history or []):
        if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str) and m["content"].strip():
            return m["content"].strip()
    return ""


def is_follow_up(message: str, history: list[dict]) -> bool:
    """A message that only makes sense with the conversation before it."""
    if not _last_user(history):
        return False
    t = (message or "").strip()
    words = t.split()
    return len(words) <= 3 or bool(_FOLLOW_UP.search(t))


def standalone_query(message: str, history: list[dict], client, model: str | None = None) -> str:
    """The follow-up rewritten as a self-contained search query (one short model call, temperature 0).
    On any failure, or an empty or overlong rewrite: the previous visitor question followed by this message."""
    prev = _last_user(history)
    fallback = f"{prev} {message}".strip()[:500]
    turns = [m for m in (history or [])[-6:] if isinstance(m, dict) and m.get("role") in ("user", "assistant")
             and isinstance(m.get("content"), str)]
    convo = "\n".join(f"{'Visitor' if m['role'] == 'user' else 'Assistant'}: {m['content'][:400]}" for m in turns)
    try:
        r = client.chat.completions.create(
            model=model or settings.chat_model, temperature=0, max_tokens=60,
            messages=[{"role": "system", "content": "Rewrite the visitor's last message as one standalone search query for "
                                                    "the website deependhq.com (Deep's build-in-public log and his companies). "
                                                    "Resolve pronouns and references using the conversation. 'He' means "
                                                    "Deep unless the conversation says otherwise. Output only the query."},
                      {"role": "user", "content": f"Conversation:\n{convo}\n\nLast message: {message[:400]}"}])
        out = (r.choices[0].message.content or "").strip().strip('"').strip()
        if 3 <= len(out) <= 300:
            return out
    except Exception as e:
        log.warning("follow-up rewrite failed: %s", e)
    return fallback
