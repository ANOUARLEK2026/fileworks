"""مكتبة معادلات القياس. المعادلات أدوات قياس قابلة للاختيار والتعديل، لا قواعد تعاقدية.

التعبير يُقيَّم بمحلل آمن (+ - * / ** وأقواس وأسماء المدخلات و pi فقط)، دون eval.
"""
import ast
from dataclasses import dataclass, field
from .money import D, PI


class FormulaError(ValueError):
    pass


class MissingInput(FormulaError):
    pass


@dataclass
class Formula:
    code: str
    name: str
    expr: str
    inputs: list  # [{'name','label','default'}]
    unit_hint: str = ""
    builtin: bool = False


def _inp(name, label, default=None):
    return {"name": name, "label": label, "default": default}


_N = _inp("n", "العدد", "1")

BUILTIN_FORMULAS = [
    Formula("count", "عدد", "n", [_inp("n", "العدد")], "وحدة", True),
    Formula("length", "طول (عدد × طول)", "n*L", [_N, _inp("L", "الطول")], "مط", True),
    Formula("area", "مساحة (عدد × طول × عرض)", "n*L*l", [_N, _inp("L", "الطول"), _inp("l", "العرض")], "م²", True),
    Formula("volume", "حجم (عدد × طول × عرض × ارتفاع)", "n*L*l*h",
            [_N, _inp("L", "الطول"), _inp("l", "العرض"), _inp("h", "الارتفاع")], "م³", True),
    Formula("circle_area", "مساحة قرص", "n*pi*r**2", [_N, _inp("r", "نصف القطر")], "م²", True),
    Formula("cylinder_volume", "حجم أسطوانة", "n*pi*r**2*h", [_N, _inp("r", "نصف القطر"), _inp("h", "الارتفاع")], "م³", True),
    Formula("triangle_area", "مساحة مثلث", "n*b*h/2", [_N, _inp("b", "القاعدة"), _inp("h", "الارتفاع")], "م²", True),
    Formula("sum_area", "مساحة مركبة (عدد × (طول1 + طول2) × عرض)", "n*(L1+L2)*l",
            [_N, _inp("L1", "الطول 1"), _inp("L2", "الطول 2"), _inp("l", "العرض")], "م²", True),
]


def _ev(node, env):
    if isinstance(node, ast.Expression):
        return _ev(node.body, env)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return D(repr(node.value))
    if isinstance(node, ast.Name):
        if node.id == "pi":
            return PI
        if node.id in env:
            return env[node.id]
        raise MissingInput(f"مدخل غير معروف: {node.id}")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _ev(node.operand, env)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.BinOp):
        a, b = _ev(node.left, env), _ev(node.right, env)
        op = node.op
        if isinstance(op, ast.Add):
            return a + b
        if isinstance(op, ast.Sub):
            return a - b
        if isinstance(op, ast.Mult):
            return a * b
        if isinstance(op, ast.Div):
            if b == 0:
                raise FormulaError("قسمة على صفر")
            return a / b
        if isinstance(op, ast.Pow):
            if b != b.to_integral_value() or not (0 <= b <= 6):
                raise FormulaError("الأس يجب أن يكون عددًا صحيحًا بين 0 و6")
            return a ** int(b)
    raise FormulaError("تعبير غير مسموح في المعادلة")


def validate_expr(expr, input_names):
    tree = ast.parse(expr, mode="eval")
    env = {n: D(1) for n in input_names}
    _ev(tree, env)  # يرمي خطأ إن وُجد اسم أو عملية غير مسموحة
    return True


def evaluate(formula: Formula, values: dict):
    """نتيجة بدقة كاملة (بلا تقريب). المدخل الناقص بلا قيمة افتراضية => MissingInput."""
    env = {}
    for spec in formula.inputs:
        raw = values.get(spec["name"])
        if raw in (None, ""):
            raw = spec.get("default")
        if raw in (None, ""):
            raise MissingInput(f"المدخل «{spec['label']}» ({spec['name']}) مفقود")
        env[spec["name"]] = D(raw)
    return _ev(ast.parse(formula.expr, mode="eval"), env)


def suggest_for_unit(unit):
    """اقتراح فقط (لا يُفرض): معادلة مناسبة لوحدة البند."""
    u = (unit or "").replace(" ", "")
    table = {"مط": "length", "م/ط": "length", "مط.": "length", "م2": "area", "م²": "area",
             "م3": "volume", "م³": "volume", "و": "count", "ج": "count"}
    return table.get(u)
