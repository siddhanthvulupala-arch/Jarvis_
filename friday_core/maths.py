from __future__ import annotations
import ast, math, operator, re
OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod, ast.Pow: operator.pow}
FUNCS = {name: getattr(math, name) for name in ("sqrt", "sin", "cos", "tan", "log", "log10", "ceil", "floor")}; FUNCS.update({"abs": abs, "round": round})
CONSTANTS = {"pi": math.pi, "e": math.e}

def looks_like_math(text: str) -> bool:
    return bool(re.search(r"\d\s*[+\-*/^=]\s*\d", text)) or any(word in text for word in ("calculate", "evaluate", "solve", "square root", "plus", "minus", "times", "divided"))

def _evaluate(node: ast.AST):
    if isinstance(node, ast.Expression): return _evaluate(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)): return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS: return OPS[type(node.op)](_evaluate(node.left), _evaluate(node.right))
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)): return _evaluate(node.operand) if isinstance(node.op, ast.UAdd) else -_evaluate(node.operand)
    if isinstance(node, ast.Name) and node.id in CONSTANTS: return CONSTANTS[node.id]
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in FUNCS: return FUNCS[node.func.id](*[_evaluate(arg) for arg in node.args])
    raise ValueError("Unsupported expression")

def calculate(text: str) -> str | None:
    expression = re.sub(r"^(what is|calculate|evaluate)\s+", "", text.lower().strip())
    for source, target in (("multiplied by", "*"), ("times", "*"), ("divided by", "/"), ("plus", "+"), ("minus", "-"), ("^", "**")): expression = expression.replace(source, target)
    try: return f"The answer is {_evaluate(ast.parse(expression, mode='eval')):.10g}."
    except (SyntaxError, ValueError, ZeroDivisionError): return None
