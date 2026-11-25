"""Fail if a method that is not 'async def' is awaited anywhere in main.py."""
import ast
import sys
from pathlib import Path

source = Path("main.py").read_text(encoding="utf-8")
tree = ast.parse(source)

sync_methods = set()
async_methods = set()
for node in ast.walk(tree):
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        (async_methods if isinstance(node, ast.AsyncFunctionDef) else sync_methods).add(node.name)

problems = []
for node in ast.walk(tree):
    if isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
        call = node.value.func
        name = None
        if isinstance(call, ast.Attribute) and isinstance(call.value, ast.Name) and call.value.id == "self":
            name = call.attr
        elif isinstance(call, ast.Name):
            name = call.id
        if name and name in sync_methods and name not in async_methods:
            problems.append((node.lineno, name))

if problems:
    for line, name in problems:
        print(f"AWAIT_OF_SYNC {name} at main.py:{line}")
    sys.exit(1)
print(f"OK: no awaited sync function ({len(sync_methods)} sync / {len(async_methods)} async defined)")
