"""Finds every translatable text in the sources, so that a test can check that each one has a translation (and that no
translation is left over). The English text is the key: see `app/i18n/__init__.py`."""
import ast
import json
import re
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LITERAL = r'"((?:[^"\\\n]|\\.)*)"'


def _decode(literal):
    return json.loads('"' + literal + '"')


def js_keys(source):
    """Texts in app.js: tt("..."), N_("..."), plural(n, "one", "many") and the glossary."""
    keys = {_decode(m.group(1)) for m in re.finditer(r"\b(?:tt|N_)\(\s*" + LITERAL, source)}
    for m in re.finditer(r"\bplural\([^\"\n]*?,\s*" + LITERAL + r"\s*,\s*" + LITERAL, source):
        keys |= {_decode(m.group(1)), _decode(m.group(2))}
    gloss = re.search(r"const GLOSS = \{(.*?)\n\};", source, re.S).group(1)
    for m in re.finditer(r"\[\s*" + LITERAL + r"\s*,\s*" + LITERAL + r"\s*\]", gloss):
        keys |= {_decode(m.group(1)), _decode(m.group(2))}
    return keys


class _Html(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.keys, self._open, self._text = set(), None, []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        for name in (a.get("data-t-attrs") or "").split(","):
            if name.strip() and a.get(name.strip()):
                self.keys.add(a[name.strip()])
        if "data-t" in a:
            self._open, self._text = tag, []

    def handle_data(self, data):
        if self._open:
            self._text.append(data)

    def handle_endtag(self, tag):
        if self._open == tag:
            self.keys.add("".join(self._text).strip())
            self._open = None


def html_keys(source):
    """Texts in index.html: the text of every data-t element and the attributes listed in data-t-attrs."""
    parser = _Html()
    parser.feed(source)
    return parser.keys


# Where the text is, in each call that takes one: the position of the argument.
_CALLS = {"t": 1, "tr": 1, "Msg": 0, "_error": 1, "say": 0, "_login_html": 0}


def _strings(node):
    """The texts an argument can be: a literal, or the alternatives of `a or b` and `a if c else b`; never an index like p["label"]."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.BoolOp):
        return [s for v in node.values for s in _strings(v)]
    if isinstance(node, ast.IfExp):
        return _strings(node.body) + _strings(node.orelse)
    return []


def py_keys(source):
    """Texts in the Python sources: the arguments of t(), Msg(), the server's error and progress messages, and the tables of
    labels (accounts, benchmarks, periods, fees, categories) that are translated when they are sent to the page."""
    tree, keys = ast.parse(source), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in _CALLS and len(node.args) > _CALLS[name]:
                keys |= set(_strings(node.args[_CALLS[name]]))
            for kw in node.keywords:
                if kw.arg == "step" and isinstance(kw.value, ast.Tuple):
                    keys |= set(_strings(kw.value.elts[0]))
            if name == "append" and node.args and isinstance(node.args[0], ast.Tuple) and node.args[0].elts:     # warnings.append((text, params))
                keys |= set(_strings(node.args[0].elts[0]))
        elif isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
            target = node.targets[0].id
            if target == "text":                                                  # the message of the login page, chosen then passed on
                keys |= set(_strings(node.value))
            if target in ("ACCOUNTS", "SHORT_NAMES") and isinstance(node.value, ast.Dict):
                keys |= {v.value for v in node.value.values}
            elif target == "BENCHMARKS":
                for row in node.value.elts:
                    keys |= {row.elts[1].value, row.elts[3].value}
            elif target == "marks":                                               # the periods of perf.periods()
                keys |= {row.elts[0].value for row in node.value.elts}
            elif target in ("fees", "taxes") and isinstance(node.value, ast.List):  # the lines of the costs table
                keys |= {row.elts[0].value for row in node.value.elts}
        elif isinstance(node, ast.FunctionDef) and node.name == "_category":
            keys |= {n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and isinstance(n.value, str) and n.value in ("ETF", "Stock")}
    return keys


def all_keys():
    """{English text: [where it is used]}, for every source file of the application."""
    found = {}
    app = ROOT / "app"
    for key in js_keys((app / "static" / "app.js").read_text(encoding="utf-8")):
        found.setdefault(key, []).append("app.js")
    for key in html_keys((app / "static" / "index.html").read_text(encoding="utf-8")):
        found.setdefault(key, []).append("index.html")
    for path in sorted(app.rglob("*.py")):
        if path.parts[-2] == "i18n" and path.name == "fr.py":
            continue
        for key in py_keys(path.read_text(encoding="utf-8")):
            found.setdefault(key, []).append(str(path.relative_to(app)))
    return found
