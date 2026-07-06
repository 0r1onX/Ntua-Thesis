import json
import random
import re
from openpyxl import Workbook

SEED = None  # βάζω αριθμό για να πάρω ξανά κάποιο παλιό δείγμα, π.χ. SEED = 42

# φόρτωση dataset
with open("reporting_obligations.json", "r", encoding="utf-8") as f:
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


def parse_explanation(explanation: str) -> tuple[str, str, str]:
    """
    Εξάγει Subject, Frequency, Conditionality από το explanation.
    Επιστρέφει ("", "", "") αν δεν βρεθούν (π.χ. label=0).
    """
    subject = ""
    frequency = ""
    conditionality = ""

    # Subject: μετά το "Υπόχρεος -> " μέχρι την τελεία
    subj_match = re.search(r"Υπόχρεος\s*->\s*(.+?)(?:\.|$)", explanation)
    if subj_match:
        subject = subj_match.group(1).strip()

    # Frequency
    freq_match = re.search(r"Frequency:\s*(.+?)(?:\.|$)", explanation)
    if freq_match:
        frequency = freq_match.group(1).strip()

    # Conditionality
    cond_match = re.search(r"Conditionality:\s*(.+?)(?:\.|$)", explanation)
    if cond_match:
        conditionality = cond_match.group(1).strip()

    return subject, frequency, conditionality


# δημιουργία excel
wb = Workbook()
ws = wb.active
ws.title = "Sample"

# header
ws.append([
    "id", "previous_sentence", "text", "next_sentence",
    "law_number", "article", "label",
    "trigger_phrase", "subject", "frequency", "conditionality"
])

# δεδομένα
for item in sample:
    meta = item.get("metadata", {})
    trigger_phrase = meta.get("trigger_phrase", "")
    explanation = meta.get("explanation", "")
    subject, frequency, conditionality = parse_explanation(explanation)

    ws.append([
        item["id"],
        item.get("previous_sentence", ""),
        item["text"],
        item.get("next_sentence", ""),
        item["source"]["law_number"],
        item["source"]["article"],
        item["label"],
        trigger_phrase,
        subject,
        frequency,
        conditionality,
    ])

# κενή γραμμή και seed στο τέλος
ws.append([])
ws.append(["Seed", SEED])

# αποθήκευση
wb.save("sample_200_reporting_obligations.xlsx")
print(f"Το Excel δημιουργήθηκε: sample_200_reporting_obligations.xlsx (seed: {SEED})")