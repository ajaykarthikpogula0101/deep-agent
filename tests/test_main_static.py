"""Static checks over app/: a second top-level definition silently replaces the first (main.py's two _booking_or_404
made every manage link a 500), and a route declared twice only ever reaches the first handler."""
from __future__ import annotations

import ast
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parent.parent / "app"


def test_no_module_defines_a_function_twice():
    dupes = []
    for f in sorted(APP.rglob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"), filename=str(f))
        names = Counter(n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
        dupes += [f"{f.relative_to(APP.parent)}: {name}" for name, k in names.items() if k > 1]
    assert dupes == []


def test_no_route_is_declared_twice():
    from app.main import app

    pairs = Counter((m, r.path) for r in app.routes for m in (getattr(r, "methods", None) or ()))
    assert [p for p, k in pairs.items() if k > 1] == []
