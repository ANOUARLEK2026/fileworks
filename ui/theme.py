"""ثوابت ألوان خلايا الجداول (تبقى فاتحة في الوضعين، ويُضبط لونُ نصها داكنًا في cell() كي تُقرأ دائمًا).
المظهر العام (الألوان، الخطوط، QSS، الأيقونات) في ui/design.py، والمكوّنات المتحركة في ui/fx.py."""
from PySide6.QtGui import QColor

SEVERITY_LABEL = {"info": "معلومة", "warning": "تحذير", "blocking": "يمنع الاعتماد"}
SEVERITY_COLOR = {"info": QColor("#dff0fb"), "warning": QColor("#fff0c9"), "blocking": QColor("#fbd9d6")}
INPUT_COLOR = QColor("#ffffff")        # حقول يدخلها المستخدم
CALC_COLOR = QColor("#e6f1ef")         # نتائج محسوبة (للقراءة فقط)
CELL_TEXT = QColor("#0f2e2b")          # نص الخلايا الملوّنة
