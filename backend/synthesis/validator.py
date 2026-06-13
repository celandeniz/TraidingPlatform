"""Static safety + conformance check for an LLM-generated strategy (no execution).

This is the cheap first layer of a two-layer defense; the subprocess sandbox
(sandbox.py) is the hard, kernel-enforced boundary. Here we reject the obvious
escape vectors via AST before anything is compiled or run:

  * imports               (the harness injects the only allowed names)
  * while loops           (infinite-loop vector)
  * dangerous builtins    (open/eval/exec/compile/__import__/globals/getattr/...)
  * dunder attribute access (__class__/__globals__/__subclasses__/...)

Then conformance: exactly one class implementing evaluate(self, ctx).
Returns (ok, reason, class_name).
"""
from __future__ import annotations

import ast

_BANNED_NAMES = {
    "open", "eval", "exec", "compile", "__import__", "globals", "locals",
    "input", "getattr", "setattr", "delattr", "vars", "memoryview",
    "breakpoint", "help", "exit", "quit", "copyright", "credits",
}


def validate_source(source: str) -> tuple[bool, str, str]:
    if not source or not source.strip():
        return False, "empty source", ""
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return False, f"syntax error: {exc}", ""

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            return False, "imports are not allowed", ""
        if isinstance(node, ast.While):
            return False, "while loops are not allowed", ""
        if isinstance(node, ast.Attribute) and node.attr.startswith("__"):
            return False, f"dunder attribute access not allowed: {node.attr}", ""
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            return False, f"use of '{node.id}' is not allowed", ""

    classes = [n for n in tree.body if isinstance(n, ast.ClassDef)]
    if len(classes) != 1:
        return False, f"expected exactly one class, found {len(classes)}", ""
    cls = classes[0]
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    if "evaluate" not in methods:
        return False, "class must define evaluate(self, ctx)", ""
    evaluate = next(n for n in cls.body
                    if isinstance(n, ast.FunctionDef) and n.name == "evaluate")
    args = [a.arg for a in evaluate.args.args]
    if len(args) < 2:
        return False, "evaluate must accept (self, ctx)", ""
    return True, "", cls.name
