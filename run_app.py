"""نقطة التشغيل. للتشغيل بلا نافذة CMD: انقر مرتين على run_app.pyw أو WorksApp.vbs (أو ملف WorksApp.exe المبني).
قاعدة البيانات الافتراضية: %APPDATA%\\WorksApp\\works.db ، وسجل الأخطاء: %APPDATA%\\WorksApp\\error.log"""
import os
import sys
import traceback


def data_dir():
    base = os.environ.get("APPDATA")
    folder = os.path.join(base, "WorksApp") if base else os.path.join(os.path.expanduser("~"), ".worksapp")
    os.makedirs(folder, exist_ok=True)
    return folder


def default_db():
    return os.path.join(data_dir(), "works.db")


def _log(text):
    try:
        with open(os.path.join(data_dir(), "error.log"), "a", encoding="utf-8") as fh:
            fh.write(text + "\n")
    except OSError:
        pass


def _native_message(title, text):
    """رسالة خطأ تعمل بلا PySide6 وبلا طرفية (مهم لأن pythonw/‏--noconsole لا يعرضان أي أخطاء)."""
    if os.name == "nt":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, title, 0x10)
            return
        except Exception:
            pass
    print(f"{title}: {text}", file=sys.stderr)


def main():
    # pythonw و--noconsole يجعلان stdout/stderr = None فتنهار أي print
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w")
    try:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QApplication, QMessageBox
    except ImportError as e:
        _native_message("إدارة وثائق الأشغال", f"المكتبات المطلوبة غير مثبتة ({e}).\nشغّل الملف install_requirements.bat مرة واحدة ثم أعد المحاولة.")
        return 1
    from worksapp import storage as S
    from ui.main_window import MainWindow
    from ui import design

    from PySide6.QtCore import QSettings
    app = QApplication(sys.argv)
    app.setStyle("Fusion")                                  # أساس موحّد تعمل عليه أنماط QSS بشكل متوقع
    app.setLayoutDirection(Qt.LayoutDirection.RightToLeft)
    app.setApplicationName("WorksApp"); app.setOrganizationName("WorksApp")
    base = os.path.dirname(os.path.abspath(__file__))
    design.setup_fonts(app, base)                           # ضع خط Cairo أو Tajawal (.ttf) في المجلد fonts/ لأفضل مظهر
    design.apply(app, QSettings("WorksApp", "WorksApp").value("theme", "light"))
    icon = os.path.join(base, "app.ico")
    from PySide6.QtGui import QIcon
    app.setWindowIcon(QIcon(icon) if os.path.exists(icon) else design.app_icon())

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        _log(text)
        QMessageBox.critical(None, "خطأ غير متوقع", f"{exc}\n\nسُجّلت التفاصيل في:\n{os.path.join(data_dir(), 'error.log')}")
    sys.excepthook = hook
    try:
        conn = S.connect(sys.argv[1] if len(sys.argv) > 1 else default_db())
    except Exception as e:
        _log(traceback.format_exc())
        QMessageBox.critical(None, "تعذر فتح قاعدة البيانات", str(e))
        return 1
    win = MainWindow(conn)
    win.show_initial()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
