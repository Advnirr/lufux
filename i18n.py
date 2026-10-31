"""Translations: gettext catalogs, picked by the saved choice or the locale.

Installed copies read the compiled .mo files. A source checkout has none, so
it reads po/ directly and needs no build step.
"""
import ast
import gettext
import os

DOMAIN = "lufux"
HERE = os.path.dirname(os.path.abspath(__file__))
LOCALE_DIRS = (os.path.join(HERE, "locale"), "/app/share/locale", "/usr/share/locale")
PO_DIR = os.path.join(HERE, "po")

_tr = gettext.NullTranslations()
_lang = "en"


def _(text):
    return _tr.gettext(text)


def _candidates(lang):
    """Language codes to try, as gettext does: ru_RU.UTF-8 gives ru_RU, then ru."""
    if lang:
        names = [lang]
    else:
        names = []
        for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
            value = os.environ.get(var)
            if value:
                names = value.split(":")
                break
    for name in names:
        name = name.split(".")[0].split("@")[0]
        if name in ("C", "POSIX", ""):
            return
        yield name
        if "_" in name:
            yield name.split("_")[0]


def read_po(path):
    """{msgid: msgstr} out of a .po file, untranslated and fuzzy entries left out."""
    catalog = {}
    entry = {}
    field = None
    fuzzy = False

    def flush():
        if entry.get("msgid") and entry.get("msgstr") and not fuzzy:
            catalog[entry["msgid"]] = entry["msgstr"]

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            # a comment or a msgid after a msgstr starts the next entry
            if field == "msgstr" and (line.startswith("#") or line.startswith("msgid ")):
                flush()
                entry, field, fuzzy = {}, None, False
            if not line:
                flush()
                entry, field, fuzzy = {}, None, False
            elif line.startswith("#,"):
                fuzzy = fuzzy or "fuzzy" in line
            elif line.startswith("msgid "):
                field = "msgid"
                entry[field] = ast.literal_eval(line[6:])
            elif line.startswith("msgstr "):
                field = "msgstr"
                entry[field] = ast.literal_eval(line[7:])
            elif line.startswith('"') and field:
                entry[field] += ast.literal_eval(line)
    flush()
    return catalog


class _PoTranslations(gettext.NullTranslations):
    def __init__(self, catalog):
        super().__init__()
        self._catalog = catalog

    def gettext(self, message):
        return self._catalog.get(message, message)


def _find(code):
    for directory in LOCALE_DIRS:
        mo = os.path.join(directory, code, "LC_MESSAGES", DOMAIN + ".mo")
        if os.path.isfile(mo):
            with open(mo, "rb") as f:
                return gettext.GNUTranslations(f)
    po = os.path.join(PO_DIR, code + ".po")
    if os.path.isfile(po):
        return _PoTranslations(read_po(po))
    return None


def set_language(lang=None):
    """Load the catalog for lang ("ru_RU.UTF-8"), or for the locale when None."""
    global _tr, _lang
    for code in _candidates(lang):
        tr = _find(code)
        if tr:
            _tr, _lang = tr, code
            return
    _tr, _lang = gettext.NullTranslations(), "en"


def language():
    """The code of the loaded catalog, "en" when the strings are untranslated."""
    return _lang


set_language()
