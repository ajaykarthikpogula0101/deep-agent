"""Reading the visitor's message before retrieval: small talk, greetings in front of a question, and follow-ups.

A vector search cannot answer "hello" or "tell me more": the first has nothing to find, the second finds a random
entry. So
  * pure small talk (a greeting, "how r u", thanks, goodbye, "ok", "who are you", "what can you do") gets a natural reply
    the model writes with the conversation in view, without retrieval or a refusal; with the model down, one of several
    fixed replies the visitor has not seen yet (smalltalk_kind / smalltalk_messages / smalltalk_reply);
  * a greeting in front of a question is dropped before searching ("hi, who is Deep?" searches "who is Deep?");
  * a follow-up that leans on the conversation ("tell me more", "what about his second company?") is rewritten into a
    standalone search query with one short model call, falling back to the previous question plus this one.
"""
from __future__ import annotations

import logging
import random
import re

from app.config import settings

log = logging.getLogger("understand")

_GREETING = r"(hi+|hey+|hello+|hell?o+ there|helo+|hiya|howdy|yo+|sup|wass?up|greetings|good (morning|afternoon|evening|day)|morning|evening|namaste|namaskar|hola|bonjour|hallo|ciao)"
_THANKS = r"(thanks?( you)?( so much| a lot| very much| again)?|thank you|thx|ty|cheers|much appreciated|appreciate it|great,? thanks?)"
_BYE = r"(bye+|goodbye|good bye|bye bye|see you( later| soon)?|see ya|cya|take care|good night|gn|that'?s all|that is all|nothing else|i'?m done)"
_ACK = r"(ok+|okay|okie|k+|cool|nice|great|awesome|perfect|got it|i see|alright|all right|sounds good|makes sense|fine|sure|yes|yeah|yep|yup|no|nope|nah|hmm+|interesting|wow|lol|haha+|ah|oh|right)"
_HOW_ARE_YOU = (r"(how are you( doing)?|how('?s| is) it going|how do you do|how('?s| is) (your|ur) day( going)?|how have you been|"
                r"what'?s up|whats up|wh?at'?s good|hru|you good|all good)")
_IDENTITY = (r"(who are you|what are you|who am i (talking|speaking) (to|with)|am i (talking|speaking|chatting) (to|with) (deep|a bot|a human|a person|a real person|ai|an ai)|are you (a |an )?(bot|ai|human|robot|real person|person|real|deep)|"
             r"is this (a |an )?(bot|ai|human|real person|deep)|(what'?s )?your name|what is your name)")
_CAPABILITIES = r"(what can you do|what do you do|how can you help( me)?|what can i ask( you)?|help( me)?|what is this|what'?s this|how does this work)"

_END = r"[\s!.?,:;)(\-—–~*^_'\"🙂😊👋🙏👍😀😃😄]*"
_KINDS = [
    ("greeting", re.compile(rf"^{_GREETING}( (there|deep|team|all|everyone|bot|again))?{_END}$", re.I)),
    ("how_are_you", re.compile(rf"^({_GREETING}[\s,!.]*)?{_HOW_ARE_YOU}( today)?{_END}$", re.I)),
    ("thanks", re.compile(rf"^({_ACK}[\s,!.]*)?{_THANKS}( deep| bot)?{_END}$", re.I)),
    ("bye", re.compile(rf"^({_ACK}[\s,!.]*)?({_THANKS}[\s,!.]*)?{_BYE}{_END}$", re.I)),
    ("identity", re.compile(rf"^({_GREETING}[\s,!.]*)?{_IDENTITY}{_END}$", re.I)),
    ("capabilities", re.compile(rf"^({_GREETING}[\s,!.]*)?{_CAPABILITIES}{_END}$", re.I)),
    ("ack", re.compile(rf"^{_ACK}([\s,!.]+{_ACK})*{_END}$", re.I)),
]
_LEADING_GREETING = re.compile(rf"^{_GREETING}( (there|deep|team|all|everyone))?[\s,!.:;\-—–]+(?=\S)", re.I)

# chat shorthand, so "how r u" and "thnx" read like "how are you" and "thanks"
_SHORTHAND = [(r"\br\b", "are"), (r"\bu\b", "you"), (r"\bur\b", "your"), (r"\b(thnx|thanx|thnks|tnx)\b", "thanks"),
              (r"\b(pls|plz)\b", "please"), (r"\bwat\b", "what"), (r"\bim\b", "i'm")]


def normalise(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip().lower())
    for rx, repl in _SHORTHAND:
        t = re.sub(rx, repl, t)
    return t


# Fallback replies, used when the model is unavailable. Several per kind, and never one the visitor already saw,
# so a second "hello" never gets a word-for-word repeat.
SMALLTALK_REPLIES = {
    "greeting": [
        "Hi there! What would you like to know about Deep or what he's building?",
        "Hey! I can tell you about Deep's work, his companies, or set up a call with him. What brings you here?",
        "Hello! Curious about something Deep's building, or looking to book a call?",
        "Hi! Ask me anything about Deep, his daily build log or the Champions Group companies.",
    ],
    "greeting_again": [
        "Hey again! What would you like to dig into?",
        "Hi again. Anything specific on your mind?",
        "Still here! What can I help you find?",
    ],
    "how_are_you": [
        "I'm doing well, thanks for asking! How about you?",
        "All good here, thanks! What's on your mind?",
        "Doing great, thanks. How can I help?",
        "Pretty good, thank you! What would you like to know?",
    ],
    "thanks": [
        "You're welcome!",
        "Anytime! Let me know if anything else comes up.",
        "Happy to help. Anything else you're curious about?",
        "Glad that helped!",
    ],
    "bye": [
        "Take care! Come back anytime.",
        "Thanks for stopping by. Have a good one!",
        "Bye for now! If you ever want to talk to Deep directly, you can book a call right here.",
    ],
    "identity": [
        "I'm the AI assistant on deependhq.com, Deep's build-in-public site. I answer from what's published here, and I can book you a call with him.",
        "I'm an AI assistant for Sreedeep Surapaneni (Deep). I know what's on his site: his daily log, his companies and his tools. I can also set up a call with him.",
        "Not Deep himself, I'm his site's AI assistant. Ask me about his work or the Champions Group companies, or I can book you a call with him.",
    ],
    "capabilities": [
        "I can answer questions about what Deep is building, his daily build-in-public log, the twelve Champions Group companies and the tools he uses, and I can book you a call with him. Try \"What is Deep working on?\"",
        "Ask me about Deep's work, the companies he runs (Lake B2B, Ampliz, Champions Accelerator and more), or what he shipped recently. I can also book a call with him for you.",
    ],
    "ack": [
        "Anything else you'd like to know?",
        "Sure. What else can I help with?",
        "Got it. Anything else on your mind?",
    ],
}

SMALLTALK_PROMPT = (
    "You are the friendly AI assistant on deependhq.com, the build-in-public site of Sreedeep Surapaneni (\"Deep\"), Group "
    "CMO at Champions Group and CEO of Champions Accelerator. You can answer questions about what Deep is building, his "
    "daily log, the twelve Champions Group companies (Lake B2B, Ampliz, Champions Accelerator and others) and the tools he "
    "uses, and you can book the visitor a call with Deep in this chat.\n"
    "The visitor's last message is small talk (a greeting, how are you, thanks, goodbye, ok, or asking who you are or what "
    "you can do). Reply the way a warm, natural person would in a chat, like ChatGPT or Claude do:\n"
    "- Usually one sentence, at most two. Match their tone and energy; casual if they are casual.\n"
    "- Respond to what they actually said (answer 'how are you' briefly and kindly; acknowledge thanks; say goodbye to a goodbye).\n"
    "- Never repeat or closely paraphrase anything you already said in this conversation. If they greet you again, "
    "acknowledge it lightly ('Hey again!').\n"
    "- Do not list everything you can do. Mention at most one thing, or simply ask what they'd like to know. Only when they "
    "ask who you are or what you can do, explain briefly.\n"
    "- Do not state any facts about Deep beyond the ones above, and never invent anything. No markdown, no citations, at most one emoji."
)


def smalltalk_kind(text: str) -> str | None:
    """'greeting', 'thanks', 'bye', 'ack', 'how_are_you', 'identity' or 'capabilities' when the WHOLE message is small talk."""
    t = normalise(text)
    if not t or len(t) > 80:
        return None
    for kind, rx in _KINDS:
        if rx.match(t):
            return kind
    return None


# the assistant's last sentence is a yes/no offer when it STARTS like one ("Want me to book it?", "Shall I check Friday?");
# "What would you like to know?" is an open question
_OFFER = re.compile(r"(^|[.!?\]]\s+)(\w+,\s*)?(want me to|want to|would you like|shall i|should i|do you want|can i|may i|"
                    r"are you interested|interested in|ready to|does that|is that|sounds? good|would that|how about|okay to|ok to)\b"
                    r"[^.!?]*\?\s*$", re.I)


def answers_a_question(kind: str | None, history: list[dict]) -> bool:
    """'yes', 'ok', 'no' right after the assistant offered something ("Want me to book it?") are answers, not small talk.
    An open "What would you like to know?" is not an offer: "ok" or "thanks" after it is still small talk."""
    if kind not in ("ack", "thanks", "bye"):
        return False
    for m in reversed(history or []):
        if isinstance(m, dict) and m.get("role") == "assistant" and isinstance(m.get("content"), str):
            return bool(_OFFER.search(m["content"].strip()[-200:]))
    return False


def _said(history: list[dict]) -> set[str]:
    return {m["content"].strip() for m in (history or []) if isinstance(m, dict) and m.get("role") == "assistant"
            and isinstance(m.get("content"), str)}


def smalltalk_reply(kind: str, history: list[dict] | None = None, pick=random.choice) -> str:
    """A fallback reply for this kind that the visitor has not seen yet in this conversation."""
    said = _said(history or [])
    if kind == "greeting" and said:
        kind = "greeting_again"
    options = SMALLTALK_REPLIES.get(kind) or SMALLTALK_REPLIES["greeting"]
    fresh = [o for o in options if o not in said] or options
    return pick(fresh)


def smalltalk_messages(message: str, history: list[dict], note: str = "") -> list[dict]:
    """The model call for a small-talk turn: the prompt, the last few turns (so it never repeats itself), the message."""
    turns = [{"role": m["role"], "content": m["content"][:600]} for m in (history or [])[-8:]
             if isinstance(m, dict) and m.get("role") in ("user", "assistant") and isinstance(m.get("content"), str)]
    return [{"role": "system", "content": SMALLTALK_PROMPT + note}, *turns, {"role": "user", "content": message[:300]}]


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
