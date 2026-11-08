import json
import random
from pathlib import Path

from openpyxl import Workbook

# Paths ως προς τη ρίζα του repo (ο φάκελος πάνω από το 02_sampling/).
ROOT = Path(__file__).resolve().parent.parent
INPUT_PATH = ROOT / "data" / "Output" / "reporting_obligations.json"

SEED = None  # βάζω αριθμό για να πάρω ξανά κάποιο παλιό δείγμα, π.χ. SEED = 42

# φόρτωση dataset
with open(INPUT_PATH, "r", encoding="utf-8") as f:
    data = json.load(f)

# αν δεν έχει οριστεί seed, δημιούργησε τυχαίο
if SEED is None:
    SEED = random.randint(0, 100000)
random.seed(SEED)

# κράτα label = 1 και label = 0
label_1 = [x for x in data if x["label"] == 1]
label_0 = [x for x in data if x["label"] == 0]

# πάρε 100 τυχαία από κάθε ομάδα
sample = random.sample(label_1, 100) + random.sample(label_0, 100)

# δημιουργία excel
wb = Workbook()
ws = wb.active
ws.title = "Sample"

# header
ws.append([
    "id", "previous_sentence", "text", "next_sentence",
    "law_number", "article",
    "Evaluation", "Reason"
])

# δεδομένα
for item in sample:
    ws.append([
        item["id"],
        item.get("previous_sentence", ""),
        item["text"],
        item.get("next_sentence", ""),
        item["source"]["law_number"],
        item["source"]["article"],
        "",
        "",
    ])

# κενή γραμμή και seed στο τέλος
ws.append([])
ws.append(["Seed", SEED])

# αποθήκευση
# το seed μπαίνει στο όνομα, ώστε να μη γραφτεί πάνω στο υπάρχον δείγμα
output_path = ROOT / "data" / "Annotation" / f"sample_200_reporting_obligations_seed{SEED}.xlsx"
wb.save(output_path)
print(f"Το Excel δημιουργήθηκε: {output_path} (seed: {SEED})")
