# انقر مرتين: يفتح البرنامج دون نافذة CMD (الامتداد .pyw يعمل عبر pythonw).
import os
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.getcwd())
from run_app import main

sys.exit(main())
