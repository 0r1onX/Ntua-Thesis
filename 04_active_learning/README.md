# Active learning με Greek-BERT

Το μοντέλο (`nlpaueb/bert-base-greek-uncased-v1`) εκπαιδεύεται σε γύρους. Σε κάθε γύρο επιλέγει 150 προτάσεις από το pool, αυτές χαρακτηρίζονται (`Evaluation` = RO / NOT_RO, `Reason`) με βάση τη ρουμπρίκα (`docs/annotation_rubrik.pdf`) και το μοντέλο επανεκπαιδεύεται με τα επιπλέον δεδομένα.

- **Γύρος 0:** εκπαίδευση μόνο στο train μέρος του gold των 200.
- **Γύρος N:** gold train + `round_01 … round_N_labelled.xlsx`.
- **Test:** 60 σταθερές προτάσεις του gold (23 RO), ίδιες σε όλους τους γύρους.
- **Κριτήριο διακοπής:** έως 6 γύροι, ή διακοπή αν δύο συνεχόμενοι γύροι δεν βελτιώσουν το test F1.

## Αρχεία

| Αρχείο | Περιγραφή |
|---|---|
| `colab_run.ipynb` | Το notebook που έτρεξε στο Google Colab (T4) |

Pool: το `data/Output/reporting_obligations.json` (8.080 προτάσεις)· στο notebook ονομάζεται `ro_candidates_pool_v1.json`. Οι 200 προτάσεις του gold αφαιρούνται από τον κώδικα.

Το notebook καλεί τα scripts `code/train_bert_gr.py` και `code/select_round.py` του κοινού φακέλου της διπλωματικής, που δεν περιλαμβάνονται εδώ. Η μεταβλητή `BASE` (κελί 2) δείχνει στον φάκελο του Google Drive από τον οποίο έτρεξε.

