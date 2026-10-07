"""Answer in the visitor's language.

The knowledge base and the embedding model are English, so a question in another language would retrieve
nothing and be refused. Flow (MULTILINGUAL=true):
  1. detect(): cheap script / stop-word detection, no network. English or unknown -> nothing changes.
  2. translate_to_english(): one short chat-model call (temperature 0, ~300 tokens) used ONLY for retrieval,
     custom-answer matching and the booking-intent regexes; the visitor's original text still goes to the model.
  3. The system prompt gets a note naming the language; rule 11 makes the model answer in it while keeping the
     [id] citation markers and English page titles in the sources panel.
  4. Refusals (which bypass the model) come from a small table of translations, English otherwise.
A short follow-up with no clear language ("ana@acme.com") keeps the language of the visitor's earlier turns.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from app.config import settings
from app.rag import prompts

log = logging.getLogger("lang")

NAMES = {"es": "Spanish", "fr": "French", "de": "German", "pt": "Portuguese", "it": "Italian", "nl": "Dutch",
         "hi": "Hindi", "te": "Telugu", "ta": "Tamil", "bn": "Bengali", "ru": "Russian", "ar": "Arabic", "zh": "Chinese",
         "ja": "Japanese", "ko": "Korean", "th": "Thai", "el": "Greek", "he": "Hebrew", "tr": "Turkish", "pl": "Polish",
         "sv": "Swedish", "id": "Indonesian"}

_EN = {"the", "is", "are", "what", "how", "does", "do", "who", "which", "where", "when", "why", "can", "and", "of", "to",
       "in", "on", "for", "with", "about", "tell", "me", "book", "call", "you", "your", "this", "that", "it", "i", "a", "an",
       "please", "did", "was", "were", "has", "have", "from", "at", "by", "or", "not", "be", "will", "would", "could", "should"}
_STOP = {
    "es": {"qué", "que", "cómo", "como", "quién", "quien", "cuál", "cual", "dónde", "donde", "cuándo", "cuando", "por", "para",
           "el", "la", "los", "las", "un", "una", "es", "son", "está", "hace", "hacer", "puedo", "puede", "quiero", "con", "sobre",
           "del", "y", "de", "en", "me", "mi", "hola", "gracias", "reservar", "llamada", "empresa", "empresas", "trabaja", "tiene"},
    "fr": {"quoi", "que", "qu'est-ce", "comment", "qui", "quel", "quelle", "quels", "où", "quand", "pourquoi", "le", "la", "les",
           "un", "une", "des", "est", "sont", "fait", "faire", "peux", "peut", "je", "veux", "avec", "sur", "du", "et", "de",
           "en", "bonjour", "merci", "réserver", "appel", "entreprise", "entreprises", "travaille", "pour", "vous", "nous"},
    "de": {"was", "wie", "wer", "welche", "welcher", "wo", "wann", "warum", "der", "die", "das", "ein", "eine", "ist", "sind",
           "macht", "machen", "kann", "ich", "möchte", "mit", "über", "und", "von", "im", "hallo", "danke", "buchen", "anruf",
           "unternehmen", "arbeitet", "für", "sie", "wir", "nicht", "bitte", "gespräch", "termin"},
    "pt": {"o que", "que", "como", "quem", "qual", "quais", "onde", "quando", "porque", "por que", "o", "os", "as", "um", "uma",
           "é", "são", "está", "faz", "fazer", "posso", "pode", "quero", "com", "sobre", "do", "da", "dos", "das", "e", "de",
           "em", "olá", "obrigado", "obrigada", "reservar", "agendar", "chamada", "empresa", "empresas", "trabalha", "para",
           "você", "não"},
    "it": {"cosa", "che", "come", "chi", "quale", "quali", "dove", "quando", "perché", "il", "lo", "gli", "le", "un", "una",
           "è", "sono", "fa", "fare", "posso", "può", "voglio", "con", "su", "del", "della", "dei", "e", "di", "in", "ciao",
           "grazie", "prenotare", "chiamata", "azienda", "aziende", "lavora", "per", "lei", "noi", "non"},
    "nl": {"wat", "hoe", "wie", "welke", "waar", "wanneer", "waarom", "de", "het", "een", "is", "zijn", "doet", "doen", "kan",
           "ik", "wil", "met", "over", "van", "en", "in", "hallo", "bedankt", "boeken", "gesprek", "bedrijf", "bedrijven",
           "werkt", "voor", "u", "wij", "niet", "graag", "afspraak"},
    "tr": {"ne", "nasıl", "kim", "hangi", "nerede", "ne zaman", "neden", "bir", "ve", "ile", "için", "mı", "mi", "mu", "mü",
           "merhaba", "teşekkürler", "şirket", "görüşme", "randevu", "istiyorum", "hakkında", "yapıyor", "nedir"},
    "pl": {"co", "jak", "kto", "który", "która", "gdzie", "kiedy", "dlaczego", "jest", "są", "robi", "mogę", "chcę", "z", "o",
           "i", "w", "na", "cześć", "dziękuję", "zarezerwować", "rozmowa", "firma", "firmy", "pracuje", "dla", "nie", "proszę"},
    "id": {"apa", "bagaimana", "siapa", "yang", "mana", "kapan", "mengapa", "adalah", "dan", "dengan", "untuk", "saya", "ingin",
           "bisa", "tentang", "halo", "terima kasih", "perusahaan", "panggilan", "jadwal", "memesan", "ini", "itu", "tidak"},
    "sv": {"vad", "hur", "vem", "vilken", "vilka", "var", "när", "varför", "är", "gör", "kan", "jag", "vill", "med", "om",
           "och", "av", "i", "hej", "tack", "boka", "samtal", "företag", "företaget", "arbetar", "för", "inte", "ett", "en"},
}
_DIACRITIC = {"es": "ñ¿¡áéíóú", "fr": "çéèêàùœ", "de": "äöüß", "pt": "ãõçáéíóú", "it": "àèéìòù", "nl": "", "tr": "şğıçöü",
              "pl": "łśżźćńąę", "sv": "åäö", "id": ""}
_SCRIPTS = [
    ("hi", re.compile(r"[ऀ-ॿ]")), ("bn", re.compile(r"[ঀ-৿]")), ("ta", re.compile(r"[஀-௿]")),
    ("te", re.compile(r"[ఀ-౿]")), ("ru", re.compile(r"[Ѐ-ӿ]")), ("ar", re.compile(r"[؀-ۿ]")),
    ("he", re.compile(r"[֐-׿]")), ("el", re.compile(r"[Ͱ-Ͽ]")), ("th", re.compile(r"[฀-๿]")),
    ("ko", re.compile(r"[가-힯ᄀ-ᇿ]")), ("ja", re.compile(r"[぀-ヿ]")),
    ("zh", re.compile(r"[一-鿿]")),
]
_EMAIL_OR_URL = re.compile(r"\S+@\S+|https?://\S+", re.I)

REFUSALS = {
    "es": "No encontré eso en deependhq.com, así que prefiero no adivinar. Puedes reservar 30 minutos con Deep en "
          "https://scheduler.zoom.us/sreedeep o escribir a deep@championsmail.com.",
    "fr": "Je n'ai pas trouvé cela sur deependhq.com, je préfère donc ne pas deviner. Vous pouvez réserver 30 minutes avec Deep sur "
          "https://scheduler.zoom.us/sreedeep ou écrire à deep@championsmail.com.",
    "de": "Das habe ich auf deependhq.com nicht gefunden und möchte nicht raten. Sie können 30 Minuten mit Deep unter "
          "https://scheduler.zoom.us/sreedeep buchen oder an deep@championsmail.com schreiben.",
    "pt": "Não encontrei isso em deependhq.com, por isso prefiro não adivinhar. Pode reservar 30 minutos com o Deep em "
          "https://scheduler.zoom.us/sreedeep ou escrever para deep@championsmail.com.",
    "it": "Non ho trovato questa informazione su deependhq.com, quindi preferisco non indovinare. Puoi prenotare 30 minuti con Deep su "
          "https://scheduler.zoom.us/sreedeep o scrivere a deep@championsmail.com.",
    "nl": "Dat heb ik niet op deependhq.com gevonden, dus ik gok liever niet. U kunt 30 minuten met Deep boeken via "
          "https://scheduler.zoom.us/sreedeep of mailen naar deep@championsmail.com.",
    "hi": "यह मुझे deependhq.com पर नहीं मिला, इसलिए मैं अनुमान नहीं लगाना चाहूँगा। आप https://scheduler.zoom.us/sreedeep पर Deep के साथ "
          "30 मिनट बुक कर सकते हैं या deep@championsmail.com पर ईमेल कर सकते हैं।",
}


@dataclass
class LangInfo:
    code: str | None = None      # None = English / unknown: nothing changes
    english: str | None = None   # translation used for retrieval, or None
    note: str = ""               # appended to the system prompt

    @property
    def name(self) -> str:
        return NAMES.get(self.code or "", self.code or "English")


NONE = LangInfo()


def detect(text: str | None) -> str | None:
    """ISO code of a non-English language, or None (English / cannot tell). Scripts first, then stop words."""
    t = _EMAIL_OR_URL.sub(" ", text or "")
    for code, rx in _SCRIPTS:
        if len(rx.findall(t)) >= 2:
            return "ja" if code == "zh" and _SCRIPTS[10][1].search(t) else code
    words = re.findall(r"[^\W\d_]+(?:'[^\W\d_]+)?", t.lower())
    if not words:
        return None
    en = sum(1 for w in words if w in _EN)
    best, best_hits = None, 0
    for code, stops in _STOP.items():
        hits = sum(1 for w in words if w in stops)
        hits += sum(1 for ch in _DIACRITIC[code] if ch in t.lower())
        if hits > best_hits:
            best, best_hits = code, hits
    if best and best_hits >= 2 and best_hits > en:
        return best
    return None


def looks_english(text: str | None) -> bool:
    return detect(text) is None


def conversation_language(message: str, history: list[dict]) -> str | None:
    """The message's language, else the language of the visitor's recent turns (for a bare name or email)."""
    code = detect(message)
    if code:
        return code
    if len((message or "").split()) <= 6:
        for m in reversed(history[-6:]):
            if isinstance(m, dict) and m.get("role") == "user" and isinstance(m.get("content"), str):
                code = detect(m["content"])
                if code:
                    return code
    return None


def translate_to_english(text: str, client, model: str | None = None) -> str:
    """One short model call. On any failure the original text is returned (retrieval then does its best)."""
    try:
        r = client.chat.completions.create(
            model=model or settings.chat_model, temperature=0, max_tokens=300,
            messages=[{"role": "system", "content": "Translate the user's message to English. Keep names, email addresses, "
                                                    "URLs, product and company names unchanged. Output only the translation."},
                      {"role": "user", "content": text[:1500]}])
        out = (r.choices[0].message.content or "").strip()
        return out or text
    except Exception as e:
        log.warning("translation failed: %s", e)
        return text


def note_for(code: str | None) -> str:
    if not code:
        return ""
    name = NAMES.get(code, code)
    return (f"\nThe visitor writes in {name}. Write your whole answer in {name} (translate what you quote from the sources, "
            "keep the [id] markers, keep company and product names as they are, show dates and times the same way).")


def refusal(code: str | None) -> str:
    return REFUSALS.get(code or "", prompts.REFUSAL_NO_CONTEXT)


def prepare(message: str, history: list[dict], client) -> LangInfo:
    """Everything chat.py needs for one turn. English/unknown -> NONE (no model call)."""
    if not settings.multilingual:
        return NONE
    code = conversation_language(message, history)
    if not code:
        return NONE
    english = translate_to_english(message, client) if detect(message) else None  # a bare email needs no translation
    return LangInfo(code=code, english=english, note=note_for(code))
