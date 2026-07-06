"""
Pipeline ανίχνευσης Υποχρεώσεων Αναφοράς (Reporting Obligations) σε κείμενα ελληνικής νομοθεσίας, κατά το EURO-5K annotation standard.

Ροή επεξεργασίας:
    1. Ανάγνωση νόμων από τη βάση (harvester.db)
    2. Διάσπαση σε προτάσεις (legal_splitter_gr)
    3. Candidate detection (deontic + reporting)
    4. EURO-5K classification (4 στάδια + κανόνες αποκλεισμού)
    5. Εξαγωγή υποψήφιων RO σε JSON 

Τα λεξικά κανόνων (μοτίβα) βρίσκονται στο euro5k_patterns.py.
"""

import json
import logging
import re
import sqlite3
from pathlib import Path

from legal_splitter_gr import (
    build_legal_nlp_gr,
    split_and_clean,
    strip_headers_from_sent,
)
from euro5k_patterns import (
    DEONTIC_COMPILED,
    REPORTING_COMPILED,
    INFORMATION_COMPILED,
    PUBLIC_RECIPIENT_COMPILED,
    SUPERVISORY_PURPOSE_COMPILED,
    EXCLUSION_COMPILED,
    REPORTING_NON_SUBMISSION_COMPILED,
    TRIGGER_COMPILED,
)

logger = logging.getLogger(__name__)

# Όρια για τον paragraph-aware context builder.
CONTEXT_MAX_CHARS = 500
CONTEXT_MIN_MEANINGFUL_LEN = 35

# Μέγιστο μήκος πρότασης (σε λέξεις) που εξετάζεται ως candidate.
MAX_SENTENCE_WORDS = 200


def setup_logging():
    """Διαγνωστικά στο classifier.log, καθαρή έξοδος προόδου στην κονσόλα."""
    file_handler = logging.FileHandler("classifier.log", encoding="utf-8", mode="w")
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    )
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(message)s"))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)


# ======================================================
# 1) Ανάγνωση νόμων από τη βάση
# ======================================================
def fetch_laws(db_path="harvester.db"):
    """
    Επιστρέφει έναν νόμο ανά nomosNum, με το κείμενο του πιο πρόσφατου ΦΕΚ.

    Το ROW_NUMBER() εξασφαλίζει ότι title/fekTEXT προέρχονται από την ίδια γραμμή με το πιο πρόσφατο fekDate
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    sql = """
        SELECT law_num, title, fek_number, fek_year, fek_text
        FROM (
            SELECT
                nomosNum   AS law_num,
                nomosTitle AS title,
                fekDate    AS fek_date,
                fekNumber  AS fek_number,
                fekEtos    AS fek_year,
                fekTEXT    AS fek_text,
                ROW_NUMBER() OVER (
                    PARTITION BY nomosNum
                    ORDER BY fekDate DESC, fekNumber DESC
                ) AS rn
            FROM et
            WHERE
                nomosTitle NOT LIKE '%ΚΥΡΩΣΕΙΣ%'
                AND fekNumber > 0
                AND fekTEXT IS NOT NULL
                AND TRIM(fekTEXT) != ''
        )
        WHERE rn = 1
        ORDER BY fek_date DESC, law_num DESC;
    """

    cur.execute(sql)
    rows = cur.fetchall()
    conn.close()
    return rows


# ======================================================
# 2) Candidate detection
# ======================================================
_NEGATED_REPORTING_RE = re.compile(
    r'\bνα\s+μην?\s+(γνωστοποι|κοινοποι|διαβιβάζ|ενημερ)', re.IGNORECASE
)
_DISCRETIONARY_RE = re.compile(
    r'\b(μπορε[ίι]|δύναται)\s+να\s+\w*(υποβάλ|κοινοποι|ενημερ)', re.IGNORECASE
)
_ON_REQUEST_RE = re.compile(r'κατόπιν\s+αιτήσεως', re.IGNORECASE)
_ON_REQUEST_PROVIDE_RE = re.compile(
    r'οφείλ\w+\s+να\s+(παράσχ|ενημερ\w+\s+\w+\s+αιτ)', re.IGNORECASE
)


def is_reporting_obligation(sentence: str) -> bool:
    """Φίλτρο candidates: δεοντικό + ρήμα αναφοράς"""
    text = sentence.lower()

    if len(text.split()) > MAX_SENTENCE_WORDS:
        return False

    if _NEGATED_REPORTING_RE.search(text):
        return False

    # Δυνητικές διατυπώσεις (μπορεί/δύναται) γίνονται δεκτές μόνο αν υπάρχει και δεοντικό.
    if _DISCRETIONARY_RE.search(text):
        if not any(p.search(text) for p in DEONTIC_COMPILED):
            return False

    # Παροχή πληροφορίας κατόπιν αιτήσεως δεν συνιστά υποχρέωση αναφοράς.
    if _ON_REQUEST_RE.search(text) and _ON_REQUEST_PROVIDE_RE.search(text):
        return False

    has_deontic = any(p.search(text) for p in DEONTIC_COMPILED)
    has_reporting = any(p.search(text) for p in REPORTING_COMPILED)
    return has_deontic and has_reporting


# ======================================================
# 3) EURO-5K classification
# ======================================================
_REGISTER_KEEPING_RE = re.compile(
    r'τηρείται\s+(ιδιαίτερ\w+\s+)?(αρχείο|βιβλίο)\b', re.IGNORECASE
)
_WEBSITE_PUBLICATION_RE = re.compile(
    r'(δημοσιεύεται|αναρτ\w+)\s+\w*\s*(στην?|στο)\s+(ιστοσελίδ|ιστότοπ|εφημερίδ)',
    re.IGNORECASE,
)
_PROHIBITION_RE = re.compile(
    r'δεν\s+(επιτρέπ|υποχρεού|επιτρέπεται)(.{0,80})', re.IGNORECASE
)
_APPLICANT_RE = re.compile(r'αιτούντ\w+\s+(φορέ|πρόσωπ|εργοδότ)', re.IGNORECASE)
_LICENSING_CONTEXT_RE = re.compile(
    r'(άδει|χορήγησ|αδειοδότ|δικαιολογητικ)', re.IGNORECASE
)
_PUBLIC_DISCLOSURE_RE = re.compile(r'\bδημοσιοποι', re.IGNORECASE)
_PUBLISH_DUTY_RE = re.compile(r'\bοφείλει\s+να\s+δημοσιεύ', re.IGNORECASE)
_APPROVAL_SUBMISSION_RE = re.compile(
    r'υποβ\w+\s+(προς|για)\s+έγκριση', re.IGNORECASE
)


def compute_label_euro5k(sentence: str) -> tuple[int, str]:
    """
    Πλήρης EURO-5K ταξινόμηση μίας πρότασης, σε τέσσερα στάδια:
    δεοντικό όρο, παροχή πληροφορίας, δημόσιος αποδέκτης, κανόνες αποκλεισμού. 
    Επιστρέφει (label, reason).
    """
    text = sentence.lower()

    if not any(p.search(text) for p in DEONTIC_COMPILED):
        return 0, "no_deontic"

    if not any(p.search(text) for p in INFORMATION_COMPILED):
        return 0, "no_information"

    if not any(p.search(text) for p in PUBLIC_RECIPIENT_COMPILED):
        return 0, "no_recipient"

    if any(p.search(text) for p in EXCLUSION_COMPILED):
        return 0, "excluded_case"

    # --- Conditional exclusions ---

    # Τήρηση αρχείου/βιβλίων χωρίς πράξη αναφοράς.
    if _REGISTER_KEEPING_RE.search(text):
        if not any(p.search(text) for p in REPORTING_COMPILED):
            return 0, "excluded_case"

    # Δημοσίευση σε ιστοσελίδα/εφημερίδα χωρίς πράξη αναφοράς.
    if _WEBSITE_PUBLICATION_RE.search(text):
        if not any(p.search(text) for p in REPORTING_COMPILED):
            return 0, "excluded_case"

    # Απαγόρευση που αφορά την ίδια την πράξη αναφοράς.
    prohibition = _PROHIBITION_RE.search(text)
    if prohibition:
        context_after = prohibition.group(2)
        if any(p.search(context_after) for p in REPORTING_COMPILED):
            return 0, "excluded_case"

    # Αιτών σε πλαίσιο αδειοδότησης.
    if _APPLICANT_RE.search(text) and _LICENSING_CONTEXT_RE.search(text):
        return 0, "excluded_case"

    # Δημοσιοποίηση/δημοσίευση προς αρχή.
    if _PUBLIC_DISCLOSURE_RE.search(text) or _PUBLISH_DUTY_RE.search(text):
        if not any(p.search(text) for p in REPORTING_COMPILED):
            return 0, "excluded_case"

    # Υποβολή προς έγκριση
    if _APPROVAL_SUBMISSION_RE.search(text):
        if not any(p.search(text) for p in REPORTING_NON_SUBMISSION_COMPILED):
            return 0, "excluded_case"

    if any(p.search(text) for p in SUPERVISORY_PURPOSE_COMPILED):
        return 1, "valid_ro"

    return 1, "borderline_ro"


def find_trigger(sentence: str) -> str | None:
    """Επιστρέφει την πρώτη φράση που ενεργοποίησε deontic/reporting pattern."""
    text = sentence.lower()
    for pattern in TRIGGER_COMPILED:
        match = pattern.search(text)
        if match:
            return match.group(0)
    return None


# ======================================================
# 4) Explanation builder στα Metadata
# ======================================================
def extract_frequency(sentence: str) -> str:
    text = sentence.lower()
    recurring_terms = ("ετησί", "κάθε", "ανά μήνα", "ανά έτος", "μηνιαί", "τριμηνιαί")
    return "recurring" if any(t in text for t in recurring_terms) else "one-time"


def extract_conditionality(sentence: str) -> str:
    text = sentence.lower()
    conditional_terms = ("εφόσον", "αν ", "εάν", "σε περίπτωση", "όταν")
    return "conditional" if any(t in text for t in conditional_terms) else "unconditional"


def extract_direction(sentence: str) -> tuple[str, str]:
    # Έως 3 λέξεις μετά την πρόθεση, με κεφαλαίο αρχικό, ως αποδέκτης.
    # Σκόπιμα χωρίς IGNORECASE (το κεφαλαίο αρχικό είναι μέρος του κανόνα)
    recipient_match = re.search(
        r'\b(στην|στον|στο|προς)\s+((?:[Α-Ω][^ ,.;:]*\s*){1,3})', sentence
    )
    recipient = recipient_match.group(2).strip() if recipient_match else "Δημόσια Αρχή"

    subject_match = re.search(
        r'^([^.,;:]+?)\s+(υποβάλλ|κοινοποι|διαβιβάζ|αποστέλλ|ενημερών|αναφέρ)',
        sentence.lower(),
    )
    subject = subject_match.group(1).strip().capitalize() if subject_match else "Υπόχρεος"

    return subject, recipient


def build_explanation(sentence: str) -> str:
    subject, recipient = extract_direction(sentence)
    frequency = extract_frequency(sentence)
    conditionality = extract_conditionality(sentence)
    return f"RO: {subject} -> {recipient}. Frequency: {frequency}. Conditionality: {conditionality}."


# ======================================================
# 5) Regex άρθρων
# ======================================================
article_pattern = re.compile(r'^\s*[άα]ρθρο\s+(\d+[α-ωa-z]?)', re.IGNORECASE)


# ======================================================
# 6) Paragraph-aware context builder
# ======================================================
_PARA_START_RE = re.compile(
    r'^('
    r'\d+(?:\.\d+)*[α-ωΑ-Ω]?\.?\s'    # 1. / 14.5.3. / 1.α.
    r'|[α-ωΑ-Ω]{1,3}\)\s'             # α) / βα)
    r'|\([α-ωΑ-Ω]{1,3}\)\s'           # (α) / (β)
    r'|[ivxlIVXL]{1,6}\.\s'           # i. / iv.
    r')',
    re.UNICODE,
)


def _build_paragraph_groups(sentences: list[str]) -> list[list[int]]:
    """
    Ομαδοποιεί τις προτάσεις σε παραγράφους. Κάθε παράγραφος ξεκινά με paragraph marker (1., α), i. κλπ). Επιστρέφει λίστα από groups,
    κάθε group = λίστα indices.
    """
    if not sentences:
        return []

    groups = []
    current_group = [0]

    for i in range(1, len(sentences)):
        if _PARA_START_RE.match(sentences[i].strip()):
            groups.append(current_group)
            current_group = [i]
        else:
            current_group.append(i)

    groups.append(current_group)
    return groups


def _truncate_prev(text: str, max_chars: int) -> str | None:
    """
    Κρατά τους τελευταίους max_chars χαρακτήρες του text, κόβοντας στο πρώτο sentence boundary ώστε να μην αρχίζει στη μέση της λέξης.
    Επιστρέφει None αν το αποτέλεσμα είναι πολύ σύντομο για να έχει νόημα.
    """
    if len(text) <= max_chars:
        return text if len(text.strip()) >= CONTEXT_MIN_MEANINGFUL_LEN else None

    truncated = text[-max_chars:]

    sent_boundary = re.search(r'[.;·»]\s+', truncated, re.UNICODE)
    if sent_boundary:
        truncated = truncated[sent_boundary.end():]

    truncated = truncated.strip()
    if not truncated:
        return None

    return truncated if len(truncated) >= CONTEXT_MIN_MEANINGFUL_LEN else None


def _truncate_next(text: str, max_chars: int) -> str:
    """
    Κρατά τους πρώτους max_chars χαρακτήρες, κόβοντας στο τέλος της τελευταίας πλήρους πρότασης (. ; · ») και αποφεύγοντας enumeration
    markers. Fallback: τελευταίο κενό.
    """
    if len(text) <= max_chars:
        return text

    truncated = text[:max_chars]

    best_end = None
    for m in re.finditer(r'[.;·»]\s*', truncated):
        before = truncated[:m.start()].rstrip()
        # Αποφυγή κοψίματος σε enumeration marker ή αριθμό παραπομπής.
        if re.search(r'([α-ωΑ-Ω]{1,3}|[ivxlIVXL]{1,6}|\d+)$', before):
            continue
        # Αποφυγή κοψίματος αν ακολουθεί αριθμός
        after = truncated[m.end():]
        if after and after[0].isdigit():
            continue
        best_end = m.end()

    if best_end:
        return truncated[:best_end].strip()

    space_idx = truncated.rfind(" ")
    return truncated[:space_idx] if space_idx != -1 else truncated


_HEADER_ONLY_RE = re.compile(
    r'^\s*('
    r'(?:Ά|Α)ρθρο\s+\d+[Α-ΩA-Zα-ω]?\s*[.\-–]?\s*[Α-ΩΆΈΉΊΌΎΏ][^\n.]{0,60}'  # Άρθρο N Τίτλος
    r'|(?:Ά|Α)ρθρο\s*\d*\s*'                          # σκέτο "Άρθρο" ή "Άρθρο N"
    r'|ΑΡΘΡΟ\s+\d+[Α-ΩA-Zα-ω]?[^\n]{0,60}'
    r'|ΚΕΦΑΛΑΙΟ\s+[^\n]{0,60}'
    r'|ΜΕΡΟΣ\s+[^\n]{0,60}'
    r'|ΤΜΗΜΑ\s+[^\n]{0,60}'
    r'|ΤΙΤΛΟΣ\s+[^\n]{0,60}'
    r')\s*$',
    re.UNICODE,
)


def _is_header_only(text: str) -> bool:
    """
    True αν το κομμάτι είναι αμιγώς επικεφαλίδα/τίτλος άρθρου χωρίς ουσιαστικό περιεχόμενο — δηλαδή δεν χρησιμεύει ως context.
    """
    stripped = text.strip()
    if not stripped:
        return True
    return bool(_HEADER_ONLY_RE.match(stripped))


def _meaningful_context(sentences: list[str], indices: list[int]) -> str:
    """
    Ενώνει τα κομμάτια των indices αγνοώντας όσα είναι αμιγώς επικεφαλίδες,
    ώστε το context να μην αποτελείται από τίτλους άρθρων.
    """
    parts = [sentences[j] for j in indices if not _is_header_only(sentences[j])]
    return " ".join(parts).strip()


def _build_context_map(
    sentences: list[str],
    para_groups: list[list[int]],
) -> dict[int, tuple[str | None, str | None]]:
    """
    Context ανά πρόταση, με εγγύηση μη-κενού prev/next όποτε υπάρχει γειτονικό ουσιαστικό κείμενο στο έγγραφο.

    Πρώτα δοκιμάζεται paragraph-aware context (ίδια ή γειτονική παράγραφος).
    Αν αυτό είναι κενό (π.χ. όλοι οι γείτονες ήταν επικεφαλίδες ή πολύ σύντομοι), γίνεται γραμμική αναζήτηση της πλησιέστερης ουσιαστικής
    πρότασης, μπρος/πίσω, σε όλο το έγγραφο. Μόνο η πρώτη πρώτη πρόταση του εγγράφου μένει χωρίς prev και η τέρμα τελευταία χωρίς next.
    """
    idx_to_group: dict[int, tuple[int, int]] = {}
    for g_idx, group in enumerate(para_groups):
        for pos, s_idx in enumerate(group):
            idx_to_group[s_idx] = (g_idx, pos)

    def nearest_prev(s_idx: int) -> str | None:
        for j in range(s_idx - 1, -1, -1):
            if not _is_header_only(sentences[j]):
                return sentences[j].strip()
        return None

    def nearest_next(s_idx: int) -> str | None:
        for j in range(s_idx + 1, len(sentences)):
            if not _is_header_only(sentences[j]):
                return strip_headers_from_sent(sentences[j]).strip()
        return None

    context_map: dict[int, tuple[str | None, str | None]] = {}

    for s_idx in range(len(sentences)):
        g_idx, pos = idx_to_group[s_idx]
        group = para_groups[g_idx]

        # --- Previous ---
        if pos > 0:
            full_prev = _meaningful_context(sentences, group[:pos])
        elif g_idx > 0:
            full_prev = _meaningful_context(sentences, para_groups[g_idx - 1])
        else:
            full_prev = ""

        previous_sentence = (
            _truncate_prev(full_prev, CONTEXT_MAX_CHARS) if full_prev else None
        )
        if previous_sentence is None:
            previous_sentence = nearest_prev(s_idx)

        # --- Next ---
        if pos < len(group) - 1:
            full_next = _meaningful_context(sentences, group[pos + 1:])
        elif g_idx < len(para_groups) - 1:
            full_next = _meaningful_context(sentences, para_groups[g_idx + 1])
        else:
            full_next = ""

        if full_next:
            full_next = strip_headers_from_sent(full_next)
            next_sentence = _truncate_next(full_next, CONTEXT_MAX_CHARS)
        else:
            next_sentence = None
        if next_sentence is None or not next_sentence.strip():
            next_sentence = nearest_next(s_idx)

        context_map[s_idx] = (previous_sentence, next_sentence)

    return context_map


# ======================================================
# 7) Επεξεργασία ενός νόμου
# ======================================================
def process_law(law, nlp, next_id: int, debug_file) -> tuple[list[dict], int]:
    """
    Εξάγει τα candidate entries ενός νόμου. Επιστρέφει (entries, matches),
    όπου matches ο αριθμός των label=1
    """
    sentences = split_and_clean(law["fek_text"], nlp)
    para_groups = _build_paragraph_groups(sentences)
    context_map = _build_context_map(sentences, para_groups)

    entries = []
    matches = 0
    current_article = None

    for i, sent in enumerate(sentences):
        article_match = article_pattern.match(sent)
        if article_match:
            current_article = article_match.group(1)

        if not is_reporting_obligation(sent):
            continue

        label, reason = compute_label_euro5k(sent)

        if label == 0 and reason == "excluded_case":
            text = sent.lower()
            for p in EXCLUSION_COMPILED:
                if p.search(text):
                    debug_file.write(f"PATTERN: {p.pattern}\nSENT: {sent}\n---\n")
                    break

        if label == 1:
            matches += 1

        trigger = find_trigger(sent)
        explanation = (
            build_explanation(sent) if label == 1 else f"Rejected: {reason}"
        )

        prev_sentence, next_sentence = context_map[i]

        entries.append({
            "id": f"GR_OBL_{next_id + len(entries):04d}",
            "previous_sentence": prev_sentence,
            "text": sent,
            "next_sentence": next_sentence,
            "label": label,
            "metadata": {
                "trigger_phrase": trigger if trigger else "N/A",
                "explanation": explanation,
            },
            "source": {
                "law_number": str(law["law_num"]),
                "fek_number": str(law["fek_number"] or "–"),
                "year": str(law["fek_year"] or "–"),
                "article": str(current_article) if current_article else None,
            },
        })

    return entries, matches


# ======================================================
# Main
# ======================================================
def main():
    setup_logging()

    nlp = build_legal_nlp_gr()
    laws = fetch_laws()
    logger.info("Βρέθηκαν %d νόμοι για επεξεργασία", len(laws))

    all_entries = []
    laws_with_candidates = 0
    laws_with_obligations = 0
    total_obligations = 0

    header = "| {:<8} | {:<10} | {:<6} | {:<11} | {:<14} |".format(
        "Νόμος", "ΦΕΚ", "Έτος", "Candidates", "True Positives"
    )
    logger.info(header)
    logger.info("-" * len(header))

    with open("excluded_debug.txt", "w", encoding="utf-8") as dbg:
        for law in laws:
            entries, matches = process_law(law, nlp, len(all_entries) + 1, dbg)
            all_entries.extend(entries)
            total_obligations += matches

            if entries:
                laws_with_candidates += 1
            if matches:
                laws_with_obligations += 1

            logger.info("| {:<8} | {:<10} | {:<6} | {:<11} | {:<14} |".format(
                law["law_num"], law["fek_number"] or "–", law["fek_year"] or "–",
                len(entries), matches,
            ))

    output_file = Path("reporting_obligations.json")
    with output_file.open("w", encoding="utf-8") as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)

    logger.info("")
    logger.info("================= ΣΥΝΟΨΗ =================")
    logger.info("Εξετάστηκαν %d νόμοι.", len(laws))
    logger.info("%d νόμοι έχουν πιθανές υποχρεώσεις αναφοράς.", laws_with_candidates)
    logger.info("Σύνολο candidates: %d", len(all_entries))
    logger.info("True positives (label=1): %d", total_obligations)
    logger.info("===========================================")


if __name__ == "__main__":
    main()
