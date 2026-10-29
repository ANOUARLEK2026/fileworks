"""فحص ساكن لملفات ui/ لأن PySide6 غير متاح لتشغيلها: (1) أسماء مستعملة لم تُعرَّف ولم تُستورد في الملف،
(2) سمات self.X تُقرأ ولا تُسنَد في أي مكان من الصف (يلتقط أخطاء مثل btable/table). يستثني أسماء Qt المعروفة (camelCase).
ليس بديلًا عن تشغيل الواجهة الحقيقي؛ هو شبكة أمان فقط."""
import ast, builtins, glob, os, re, sys

QT_PLAIN = {"show", "hide", "close", "update", "style", "parent", "exec", "accept", "reject", "done", "open", "finished", "resize",
            "move", "size", "width", "height", "layout", "window", "pos", "geometry", "focusWidget", "rect", "raise_", "lower", "repaint",
            "clicked", "triggered", "toggled", "activated", "timeout", "destroyed", "objectName", "text", "clear", "setFocus",
            "font", "viewport", "view", "widget", "grab", "palette", "cursor", "isEnabled", "isVisible", "hasFocus", "isRightToLeft", "rect", "update", "show"}
CAMEL = re.compile(r"^[a-z]+[A-Z]\w*$")


def class_attrs(cls):
    """سمات صف: دوال + ثوابت + كل self.X يُسنَد فيه."""
    out = {f.name for f in cls.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))}
    for st in cls.body:
        if isinstance(st, ast.Assign):
            for t in st.targets:
                out |= {x.id for x in ast.walk(t) if isinstance(x, ast.Name)}
    for n in ast.walk(cls):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self" and isinstance(n.ctx, ast.Store):
            out.add(n.attr)
    return out


def all_classes(root):
    reg = {}
    for f in glob.glob(os.path.join(root, "*.py")):
        for c in [c for c in ast.walk(ast.parse(open(f, encoding="utf-8").read())) if isinstance(c, ast.ClassDef)]:
            reg[c.name] = c
    return reg


REGISTRY = {}


def inherited(cls, seen=()):
    out = class_attrs(cls)
    for b in cls.bases:
        name = b.id if isinstance(b, ast.Name) else None
        if name in REGISTRY and name not in seen:
            out |= inherited(REGISTRY[name], seen + (name,))
    return out


def check(path):
    tree = ast.parse(open(path, encoding="utf-8").read(), path)
    problems = []
    stored = set(dir(builtins))
    for n in ast.walk(tree):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            stored |= {(a.asname or a.name).split(".")[0] for a in n.names}
        elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            stored.add(n.name)
            if not isinstance(n, ast.ClassDef):
                a = n.args
                stored |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs} | {x.arg for x in (a.vararg, a.kwarg) if x}
        elif isinstance(n, ast.Lambda):
            a = n.args
            stored |= {x.arg for x in a.posonlyargs + a.args + a.kwonlyargs} | {x.arg for x in (a.vararg, a.kwarg) if x}
        elif isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del)):
            stored.add(n.id)
        elif isinstance(n, ast.ExceptHandler) and n.name:
            stored.add(n.name)
    for n in ast.walk(tree):
        if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id not in stored:
            problems.append(f"{path}:{n.lineno}: اسم غير معرّف «{n.id}»")
    for cls in [c for c in ast.walk(tree) if isinstance(c, ast.ClassDef)]:
        defined = inherited(cls)
        for n in ast.walk(cls):
            if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "self"
                    and isinstance(n.ctx, ast.Load) and n.attr not in defined and n.attr not in QT_PLAIN and not CAMEL.match(n.attr)):
                problems.append(f"{path}:{n.lineno}: self.{n.attr} لم يُسنَد في الصف {cls.name}")
    return problems


def check_backend_calls(root):
    """كل S.x / SV.x / EX.x / D(...) تستدعيه الواجهة من الطبقات الخلفية يجب أن يكون موجودًا فعلًا فيها (يعمل دون Qt)."""
    sys.path.insert(0, os.path.join(root, ".."))
    from worksapp import storage, services, export, money
    mods = {"S": storage, "SV": services, "EX": export, "E": export}
    problems = []
    for f in sorted(glob.glob(os.path.join(root, "*.py"))):
        tree = ast.parse(open(f, encoding="utf-8").read())
        alias = {}
        for n in ast.walk(tree):
            if isinstance(n, ast.ImportFrom) and n.module in ("worksapp", None) or isinstance(n, ast.ImportFrom) and n.module == "worksapp":
                for a in n.names:
                    if a.name in ("storage", "services", "export"):
                        alias[a.asname or a.name] = {"storage": storage, "services": services, "export": export}[a.name]
            elif isinstance(n, ast.ImportFrom) and n.module == "worksapp.money":
                for a in n.names:
                    if not hasattr(money, a.name):
                        problems.append(f"{f}:{n.lineno}: money.{a.name} غير موجود")
        for n in ast.walk(tree):
            if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id in alias:
                if not hasattr(alias[n.value.id], n.attr):
                    problems.append(f"{f}:{n.lineno}: {n.value.id}.{n.attr} غير موجود في الطبقة الخلفية")
    return problems


if __name__ == "__main__":
    root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ui")
    REGISTRY.update(all_classes(root))
    allp = [p for f in sorted(glob.glob(os.path.join(root, "*.py"))) for p in check(f)]
    allp += check_backend_calls(root)
    print("\n".join(allp) or "لا مشكلات ظاهرة")
    sys.exit(1 if allp else 0)
