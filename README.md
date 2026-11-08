# Εντοπισμός Υποχρεώσεων Υποβολής Αναφοράς στην Ελληνική Νομοθεσία

Διπλωματική εργασία : Ανάπτυξη Συνόλου Δεδομένων (dataset) για τον εντοπισμό υποχρεώσεων υποβολής αναφορών (Reporting Obligations, RO) στην ελληνική νομοθεσία.

## Περιγραφή

Το σύστημα στοχεύει στην αυτόματη ανάλυση νομικών κειμένων με σκοπό την ανίχνευση προτάσεων που περιγράφουν υποχρεώσεις αναφοράς.

Η διαδικασία βασίζεται σε rule-based προσέγγιση και περιλαμβάνει τα εξής στάδια:

1. Εξαγωγή νομικών εγγράφων από βάση δεδομένων (harvester.db).
2. Διαχωρισμός κειμένου σε επιμέρους προτάσεις μέσω γλωσσικού splitter για ελληνικά νομικά κείμενα.
3. Εντοπισμός και ταξινόμηση προτάσεων που ενδέχεται να περιέχουν υποχρεώσεις αναφοράς, με χρήση κανόνων και pattern-based ανάλυσης (EURO-5K schema).
4. Παραγωγή δομημένου JSON με τα αποτελέσματα της ανάλυσης.

Μετά δημιουργούμε dataset αξιολόγησης 200 δειγμάτων για έλεγχο της απόδοσης του συστήματος. Οι 200 προτάσεις χαρακτηρίστηκαν από ανθρώπους με βάση τη ρουμπρίκα (`docs/annotation_rubrik.pdf`) και αποτελούν το gold standard (`data/Annotation/gold_200_v1.csv`).

Ως βοηθητικό εργαλείο για τον χαρακτηρισμό των 200 δειγμάτων (πριν από το gold) χρησιμοποιήθηκε LLM (GPT-4o-mini μέσω OpenRouter API).

Τέλος, με active learning εκπαιδεύεται το Greek-BERT σε γύρους: το μοντέλο επιλέγει προτάσεις, αυτές χαρακτηρίζονται και το μοντέλο επανεκπαιδεύεται (βλ. `04_active_learning/`).


## Το παραγόμενο αρχείο εξόδου (reporting_obligations.json)

Το reporting_obligations.json είναι το τελικό "προϊόν" του pipeline. Περιέχει μια λίστα από εγγραφές — μία για κάθε πρόταση νόμου, που ο αλγόριθμος ξεχώρισε ως πιθανή υποχρέωση αναφοράς και την αξιολόγησε. Κάθε εγγραφή είναι ένα αντικείμενο JSON με τα εξής πεδία:

id — μοναδικό αναγνωριστικό της εγγραφής (π.χ. GR_OBL_0001), για εύκολη παραπομπή.

text — η ίδια η πρόταση που αξιολογείται. Αυτή είναι το επίκεντρο: το σύστημα κρίνει αυτήν ως υποχρέωση αναφοράς ή όχι.

previous_sentence / next_sentence — η προηγούμενη και η επόμενη πρόταση στο κείμενο του νόμου. Δίνονται ως συμφραζόμενα, ώστε να είναι κατανοητό το πλαίσιο της υπό εξέταση πρότασης.

label — η ετικέτα της ταξινόμησης: 1 αν η πρόταση χαρακτηρίστηκε ως υποχρέωση αναφοράς, 0 αν όχι.

### metadata — πληροφορίες για την απόφαση του συστήματος:

trigger_phrase: η φράση που ενεργοποίησε την ανίχνευση (π.χ. «υποχρεούται»).

explanation: σύντομη αιτιολόγηση. Για τις θετικές (label 1) περιγράφει τα στοιχεία που εντοπίστηκαν (υπόχρεος, αποδέκτης, συχνότητα)· για τις αρνητικές (label 0) αναφέρει τον λόγο απόρριψης (π.χ. no_recipient — δεν βρέθηκε αποδέκτης-αρχή).


source — η προέλευση της πρότασης στη νομοθεσία: αριθμός νόμου (law_number), αριθμός ΦΕΚ (fek_number), έτος (year) και άρθρο (article).

Το αρχείο json περιέχει όλες τις περιπτώσεις (label=0 & label=1).

## Δομή

| Φάκελος / αρχείο | Περιγραφή |
|---|---|
| `01_pipeline/reporting_obligations_v1.py` | Κύρια λογική ανίχνευσης και ταξινόμησης |
| `01_pipeline/euro5k_patterns.py` | Λεξικά μοτίβων (deontic, reporting, recipients, exclusions) |
| `01_pipeline/legal_splitter_gr.py` | Διάσπαση νομικού κειμένου σε προτάσεις |
| `02_sampling/random200_v1.py` | Δειγματοληψία 100 label=1 + 100 label=0 από το json (με τις στήλες του συστήματος) |
| `02_sampling/random200_v1_lite.py` | Ίδια δειγματοληψία, «τυφλή» έκδοση: μόνο κείμενο και κενές στήλες `Evaluation` / `Reason` |
| `03_llm_baseline/llm_classifier_v1.py` | Βοηθητικό εργαλείο χαρακτηρισμού των 200 δειγμάτων με GPT-4o-mini (OpenRouter) |
| `04_active_learning/` | Γύροι active learning με Greek-BERT (notebook) |
| `data/Output/reporting_obligations.json` | Έξοδος του pipeline (8.080 υποψήφιες, όλες label 0 & 1) |
| `data/Annotation/sample_200_reporting_obligations.xlsx` | Το δείγμα των 200 (seed 64536) |
| `data/Annotation/gold_200_v1.csv` | Gold standard των 200 (77 RO / 123 NOT_RO) |
| `docs/annotation_rubrik.pdf` | Ρουμπρίκα χαρακτηρισμού |

Η βάση `harvester.db` (~1.6GB, 3.485 νόμοι) δεν περιλαμβάνεται λόγω μεγέθους· για να τρέξει το pipeline πρέπει να μπει στο `data/harvester.db`.

## Εγκατάσταση

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
python -m spacy download el_core_news_lg
```

## Χρήση

```bash
# Παραγωγή json (διαβάζει data/harvester.db, γράφει data/Output/ και logs/classifier.log)
python 01_pipeline/reporting_obligations_v1.py

# Δείγμα 200 (γράφει data/Annotation/sample_200_reporting_obligations_seed<SEED>.xlsx)
python 02_sampling/random200_v1_lite.py

# Χαρακτηρισμός με LLM (απαιτεί κλειδί OpenRouter ως environment variable)
export OPENROUTER_API_KEY="sk-or-..."   # Windows: set OPENROUTER_API_KEY=...
python 03_llm_baseline/llm_classifier_v1.py
```

## Σημείωση για τα credentials

Το `llm_classifier_v1.py` διαβάζει το κλειδί OpenRouter **αποκλειστικά** από τη μεταβλητή περιβάλλοντος `OPENROUTER_API_KEY`. Δεν αποθηκεύεται ποτέ κλειδί
μέσα στον κώδικα ή στο repository. Μπαίνει χειροκίνητα κάθε φορά στο τερματικό.
