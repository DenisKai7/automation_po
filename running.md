test:
python tests/test_automation.py

approval prompt manual
python main.py --source "Sample Invoice"

eksekusi pipeline:
python main.py --source "Sample Invoice" --auto-approve

eksekusi mode headless:
python main.py --source "Sample Invoice" --auto-approve --headless

eksekusi interaktif (approval prompt terminal / email):
python main.py --source "Sample Invoice"