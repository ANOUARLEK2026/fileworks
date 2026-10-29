@echo off
chcp 65001 >nul
echo تثبيت المكتبات (مرة واحدة فقط)...
python -m pip install -r requirements.txt
echo.
echo تم. شغّل البرنامج بالنقر المزدوج على WorksApp.vbs أو run_app.pyw
pause
