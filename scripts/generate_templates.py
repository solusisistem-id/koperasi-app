"""
Generate sample import templates and sample test import files.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.bulk_import.engine import generate_member_import_template
from app.savings.service import generate_savings_opening_balance_template
from app.config import TEMPLATES_DIR

def generate_all_templates():
    os.makedirs(TEMPLATES_DIR, exist_ok=True)

    # 1. Member Import Templates (.xlsx & .csv)
    xlsx_bytes, xlsx_name, _ = generate_member_import_template("xlsx")
    with open(os.path.join(TEMPLATES_DIR, xlsx_name), "wb") as f:
        f.write(xlsx_bytes)
    print(f"Generated: {os.path.join(TEMPLATES_DIR, xlsx_name)}")

    csv_bytes, csv_name, _ = generate_member_import_template("csv")
    with open(os.path.join(TEMPLATES_DIR, csv_name), "wb") as f:
        f.write(csv_bytes)
    print(f"Generated: {os.path.join(TEMPLATES_DIR, csv_name)}")

    # 2. Opening Balance Templates (.xlsx & .csv)
    ob_xlsx_bytes, ob_xlsx_name, _ = generate_savings_opening_balance_template("xlsx")
    with open(os.path.join(TEMPLATES_DIR, ob_xlsx_name), "wb") as f:
        f.write(ob_xlsx_bytes)
    print(f"Generated: {os.path.join(TEMPLATES_DIR, ob_xlsx_name)}")

    ob_csv_bytes, ob_csv_name, _ = generate_savings_opening_balance_template("csv")
    with open(os.path.join(TEMPLATES_DIR, ob_csv_name), "wb") as f:
        f.write(ob_csv_bytes)
    print(f"Generated: {os.path.join(TEMPLATES_DIR, ob_csv_name)}")

if __name__ == "__main__":
    generate_all_templates()
