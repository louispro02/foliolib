"""Interface languages.

English is the source language: every text is written in English in the code, and a language file (`fr.py`) maps each English
text to its translation. A text with no translation is shown in English, so a language can be added or completed one text at a
time. To add a language, create `app/i18n/<code>.py` with a `MESSAGES` dict and list the language in `LANGUAGES` below.

A text may contain `{name}` placeholders, filled with the parameters given to `t()` (on the server) or `T()` (in the page).
Both sides use the same files: the page downloads the messages of its language from `/api/i18n`.
"""
import functools
import importlib

LANGUAGES = {"en": "English", "fr": "Français"}
DEFAULT = "en"


@functools.cache
def _load(lang):
    module = importlib.import_module(f"{__name__}.{lang}")
    fix = getattr(module, "typography", None)         # a language may adjust its texts once, when they are loaded
    return {text: fix(translation) for text, translation in module.MESSAGES.items()} if fix else dict(module.MESSAGES)


def messages(lang):
    """{English text: translation} for `lang`; empty for English and for any unknown language."""
    if lang == DEFAULT or lang not in LANGUAGES:
        return {}
    return _load(lang)


def t(lang, text, **params):
    """`text` in `lang`, with its placeholders filled in."""
    out = messages(lang).get(text, text)
    return out.format(**params) if params else out


def number(lang, value, decimals=0, signed=False):
    """A plain number for a sentence, with the decimal mark of the language (a comma in French)."""
    out = f"{value:+.{decimals}f}" if signed else f"{value:.{decimals}f}"
    return out.replace(".", ",") if lang == "fr" else out


def join_and(lang, items):
    """'a, b and c' in the language."""
    items = list(items)
    if len(items) < 2:
        return "".join(items)
    return ", ".join(items[:-1]) + f" {t(lang, 'and')} " + items[-1]


def pick(explicit, accept_language=""):
    """The language to answer in: an explicit choice (query string or cookie) if it is supported, otherwise the browser's
    preference (the `Accept-Language` header), otherwise English."""
    if explicit in LANGUAGES:
        return explicit
    ranked = []
    for part in (accept_language or "").split(","):
        tag, _, q = part.strip().partition(";q=")
        try:
            weight = float(q) if q else 1.0
        except ValueError:
            weight = 0.0
        primary = tag.split("-")[0].strip().lower()
        if primary in LANGUAGES and weight > 0:
            ranked.append((-weight, len(ranked), primary))
    return min(ranked)[2] if ranked else DEFAULT


class Msg(ValueError):
    """An error meant for the user, which can be shown in any language: an English template and its parameters.
    `str(error)` is the English text; `error.text(lang)` is the translation."""

    def __init__(self, template, **params):
        super().__init__(template.format(**params) if params else template)
        self.template, self.params = template, params

    def text(self, lang):
        return t(lang, self.template, **self.params)


class RowErrors(Msg):
    """The problems found in several rows of a file, reported together (at most `limit` of them)."""

    def __init__(self, errors, limit=5):
        self.errors, self.limit = errors, limit
        super().__init__(self.text("en"))

    def text(self, lang):
        shown = "; ".join(t(lang, "row {n}: {error}", n=n, error=e.text(lang)) for n, e in self.errors[:self.limit])
        more = len(self.errors) - self.limit
        return shown + (t(lang, " (and {count} more)", count=more) if more > 0 else "")
