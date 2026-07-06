"""
Διάσπαση κειμένων ελληνικής νομοθεσίας σε προτάσεις.

Συνδυάζει το spaCy sentencizer με custom pipeline components και post-processing βήματα προσαρμοσμένα στις ιδιαιτερότητες των νομικών
κειμένων: ιεραρχική αρίθμηση, συντομογραφίες, enumeration markers, επικεφαλίδες δομής (ΚΕΦΑΛΑΙΟ, Άρθρο κ.λπ.) και boilerplate τέλους νόμου.

Public API: build_legal_nlp_gr(), split_and_clean().
"""

import re
import spacy
from spacy.language import Language
from spacy.tokens import Doc

# ======================================================
# Ελληνικές νομικές δομές
# ======================================================
LEGAL_STRUCT_GR = {
    "μέρος", "μέρη",
    "κεφάλαιο", "κεφάλαια",
    "ενότητα", "ενότητες",
    "υποενότητα", "υποενότητες",
    "άρθρο", "άρθρα",
    "παράγραφος", "παράγραφοι",
    "περίπτωση", "περιπτώσεις",
    "υποπαράγραφος", "υποπαράγραφοι"
}

# ======================================================
# Συντομογραφίες
# ======================================================
LEGAL_ABBR_GR = {
    "Ν.", "ν.", "Π.Δ.", "ΚΥΑ", "Αρ.", "αρ.", "περ.", "παρ.",
    "άρθ.", "κεφ.", "εδ.", "στοιχ.", "υπ.", "περιπτ.", "περίπτ.",
    "υποπαρ.", "υποπαρ",
    "παρ", "περ", "άρθ", "εδ", "στοιχ", "περιπτ", "περίπτ"
}

# ======================================================
# Regex: standalone paragraph marker
# ======================================================
_STANDALONE_MARKER_RE = re.compile(
    r'^('
    r'\d+(?:\.\d+)*[α-ωΑ-Ω]?\.?'    # 1. / 14.5.3. / 1.α.
    r'|[α-ωΑ-Ω]{1,3}\)'             # α) / βα)
    r'|[α-ωΑ-Ω]{1,3}\.'             # β. / αα.
    r'|[ivxlIVXL]{1,6}\.'           # i. / iv.
    r')\s*$',
    re.UNICODE
)

# ======================================================
# Regex: Αρχή νέας παραγράφου 
# ======================================================
_PARA_MARKER_RE = re.compile(
    r'(?<=[.;»·"\u201d\u00bb])\s{2,}(?='
    r'(?:\d+(?:\.\d+)*[α-ωΑ-Ω]?\.?\s'   # 1. / 14.5.3. / 1.α.
    r'|[ivxlIVXL]{1,6}\.\s'             # i. / iv.
    r'|ΚΕΦΑΛΑΙΟ\s'
    r'|ΜΕΡΟΣ\s'
    r'|ΤΜΗΜΑ\s'
    r'|ΤΙΤΛΟΣ\s'
    r'|(?:Ά|Α)ρθρο\s+\d'
    r'|ΑΡΘΡΟ\s+\d'
    r'))',
    re.UNICODE
)

# ======================================================
# Regex: δομική επικεφαλίδα εντός παραγράφου
# ======================================================
# Όταν δύο διατάξεις κολλάνε με μια επικεφαλίδα (Άρθρο N, ΚΕΦΑΛΑΙΟ κ.λπ.)
# ανάμεσά τους, το spaCy δεν σπάει γιατί ο τίτλος δεν έχει τελική στίξη.
# Σπάμε πριν από την επικεφαλίδα όταν εμφανίζεται μετά από αλλαγή γραμμής.
_STRUCT_HEADER_SPLIT_RE = re.compile(
    r'\s*\n\s*'
    r'(?='
    r'(?:Ά|Α)ρθρο\s+\d'
    r'|ΑΡΘΡΟ\s+\d'
    r'|ΚΕΦΑΛΑΙΟ\s'
    r'|ΜΕΡΟΣ\s'
    r'|ΤΜΗΜΑ\s'
    r'|ΤΙΤΛΟΣ\s'
    r'|ΕΝΟΤΗΤΑ\s'
    r')',
    re.UNICODE
)

# ======================================================
# Regex: header line
# ======================================================
_HEADER_LINE_RE = re.compile(
    r'^('
    r'ΚΕΦΑΛΑΙΟ\s+[^\n]+'
    r'|ΜΕΡΟΣ\s+[^\n]+'
    r'|ΤΜΗΜΑ\s+[^\n]+'
    r'|ΤΙΤΛΟΣ\s+[^\n]+'
    r'|ΕΝΟΤΗΤΑ\s+[^\n]+'
    r'|ΥΠΟΕΝΟΤΗΤΑ\s+[^\n]+'
    r'|(?:Ά|Α)ρθρο\s+\d+[Α-ΩA-Zα-ω]?(?:\s*[-–]\s*[^\n]+)?'
    r'|ΑΡΘΡΟ\s+\d+[Α-ΩA-Zα-ω]?(?:\s*[-–]\s*[^\n]+)?'
    r'|\(άρθρο\s+[^\n]+\)'
    r'|\d+\.\s+[Α-ΩΆΈΉΊΌΎΏ][Α-ΩΆΈΉΊΌΎΏ\s]{3,}'
    r'|[Α-ΩΆΈΉΊΌΎΏα-ω]\.\s+[Α-ΩΆΈΉΊΌΎΏ\s]{3,}'
    r'|[Α-ΩΆΈΉΊΌΎΏ]{2,}(?:\s+[Α-ΩΆΈΉΊΌΎΏ]{2,})+'
    r')$',
    re.UNICODE | re.MULTILINE
)

# ======================================================
# Regex: trailing marker στο τέλος πρότασης
# ======================================================
_TRAILING_MARKER_RE = re.compile(
    r'(?<!\w)'           # δεν προηγείται γράμμα/ψηφίο + δεν είναι τέλος λέξης
    r'[«\u00ab]?\s*'
    r'(\d+(?:\.\d+)*[α-ωΑ-Ω]?\.?'    # αριθμητικό: 1. / 1.2. / 1.α.
    r'|[α-ωΑ-Ω]{1,3}\)'              # α) β) αα)
    r'|[α-ωΑ-Ω]{1,3}\.'              # α. β. αα. 
    r')\s*$',
    re.UNICODE
)

# ======================================================
# Regex: boilerplate τέλους νόμου
# ======================================================
_BOILERPLATE_RE = re.compile(
    r'('
    r'Παραγγέλλομε\s+τη\s+δημοσίευση'
    r'|Ο\s+ΠΡΟΕΔΡΟΣ\s+ΤΗΣ\s+ΔΗΜΟΚΡΑΤΙΑΣ'
    r'|ΟΙ\s+ΥΠΟΥΡΓΟΙ\b'
    r'|Θεωρήθηκε\s+και\s+τέθηκε\s+η\s+Μεγάλη\s+Σφραγίδα'
    r'|Ο\s+ΕΠΙ\s+ΤΗΣ\s+ΔΙΚΑΙΟΣΥΝΗΣ\s+ΥΠΟΥΡΓΟΣ'
    r'|Ο\s+ΠΡΩΘΥΠΟΥΡΓΟΣ\s+ΚΑΙ\s+ΥΠΟΥΡΓΟΣ'
    r')',
    re.UNICODE
)

# ======================================================
# Regex: υπόλειμμα προθέματος στην αρχή πρότασης
# ======================================================
# Καθαρίζει "θορυβώδη" προθέματα που κρέμονται από την προηγούμενη διάταξη:
# ακρωνύμιο+παρένθεση ("ΕΕ) 1."), κεφαλαία+τελεία ("ΔΕ. 5."), ή διπλό # αριθμό ("13. 6.", "158. 3."). Ο μονός αριθμός παραγράφου ("4. Ιατροί...")

_JUNK_PREFIX_RE = re.compile(
    r'^\s*(?:'
    r'[Α-Ω]{1,4}\)\s+'                # "ΕΕ) "
    r'|[Α-Ω]{2,4}\.\s+'               # "ΔΕ. "
    r'|\d{1,3}\.\s+(?=\d{1,3}[.)])'   # "13. " μόνο πριν από άλλον αριθμό
    r')',
    re.UNICODE,
)


# ======================================================
# Merge hierarchical numbering (π.χ. 6.2.2., 1.α.)
# ======================================================
@Language.component("merge_multilevel_numbers_gr")
def merge_multilevel_numbers_gr(doc: Doc) -> Doc:
    spans = []
    i = 0

    while i < len(doc):
        if not doc[i].text.isdigit():
            i += 1
            continue

        start = i
        i += 1

        while i < len(doc) and doc[i].text == ".":
            i += 1
            if i < len(doc) and (doc[i].text.isdigit() or
                                  re.fullmatch(r'[α-ωΑ-Ω]', doc[i].text)):
                i += 1
            else:
                break

        candidate = doc[start:i].text.replace(" ", "")
        if re.fullmatch(r"\d+(?:[.\s]\d+)*(?:[.\s][α-ωΑ-Ω])?\.?", candidate) \
                and ('.' in candidate or len(candidate) > 1):
            spans.append(doc[start:i])

    if spans:
        with doc.retokenize() as retokenizer:
            for span in spans:
                try:
                    retokenizer.merge(span)
                except ValueError:
                    pass

    for token in doc:
        if re.match(r"^\d+(?:\.\d+)+[α-ωΑ-Ω]?\.?$", token.text):
            if token.i + 1 >= len(doc):
                continue

            next_token = doc[token.i + 1]
            prev_token = doc[token.i - 1] if token.i > 0 else None
            prev_text = prev_token.text.lower() if prev_token else ""

            if prev_text in LEGAL_STRUCT_GR or prev_text in {",", "και", "ή", "(", "ως"}:
                continue

            if next_token.text and next_token.text[0].isupper():
                next_token.is_sent_start = True

    return doc


# ======================================================
# Μπλοκάρισμα "3." στην αρχή παραγράφου
# ======================================================
@Language.component("block_numbering_gr")
def block_numbering_gr(doc: Doc) -> Doc:
    for i in range(len(doc) - 2):

        if doc[i].like_num and doc[i + 1].text == ".":

            prev_token = doc[i - 1] if i > 0 else None
            prev_prev_token = doc[i - 2] if i > 1 else None
            next_token = doc[i + 2]

            if next_token.text and next_token.text[0].isupper():
                continue

            if (
                prev_token and prev_token.text == "." and
                prev_prev_token and prev_prev_token.text.lower() in {"παρ", "άρθ", "περ", "εδ"}
            ):
                next_token.is_sent_start = False

    return doc


# ======================================================
# Συντομογραφίες + enumeration
# ======================================================
@Language.component("legal_fix_gr")
def legal_fix_gr(doc: Doc) -> Doc:
    for i, token in enumerate(doc[:-1]):

        if token.text in LEGAL_ABBR_GR:
            doc[i + 1].is_sent_start = False

        abbr_stems = {"παρ", "περ", "άρθ", "εδ", "στοιχ", "αρ", "υπ", "κεφ", "περιπτ", "περίπτ", "υποπαρ"}
        if token.text.lower() in abbr_stems and i + 1 < len(doc) and doc[i + 1].text == ".":
            if i + 2 < len(doc):
                doc[i + 2].is_sent_start = False

        if re.fullmatch(r"[α-ω]{1,2}", token.text) and doc[i + 1].text == ".":
            prev_token = doc[i - 1] if i > 0 else None
            if i == 0 and i + 2 < len(doc):
                doc[i + 2].is_sent_start = False
            elif prev_token and (prev_token.text == ":" or "\n" in prev_token.text):
                if i + 2 < len(doc):
                    doc[i + 2].is_sent_start = False

        if re.fullmatch(r"[α-ωΑ-Ω]{1,3}", token.text) and doc[i + 1].text == ")":
            if i + 2 < len(doc):
                doc[i + 2].is_sent_start = False

        if token.text == "(" and i + 2 < len(doc):
            if re.fullmatch(r"[α-ωΑ-Ω]{1,3}", doc[i + 1].text) and doc[i + 2].text == ")":
                if i + 3 < len(doc):
                    doc[i + 3].is_sent_start = False

        if token.text.lower() in LEGAL_STRUCT_GR and doc[i + 1].like_num:
            doc[i + 1].is_sent_start = False
            if i + 2 < len(doc):
                doc[i + 2].is_sent_start = False

    return doc


# ======================================================
# Post-processing 1: επανένωση "ξεκρέμαστων" suffix λέξεων
# ======================================================
# Το spaCy μερικές φορές σπάει μια ελληνική λέξη στη μέση (π.χ. "υπευθύν" | "ους.")
# κι η επόμενη πρόταση αρχίζει με το υπόλοιπο της λέξης + τελεία.
_DANGLING_SUFFIX_RE = re.compile(
    r'^([α-ωΑ-Ω]{1,6})\.\s*',
    re.UNICODE
)


def fix_dangling_suffixes(sentences: list[str]) -> list[str]:
    """
    Αν η πρόταση[i] τελειώνει χωρίς σωστή στίξη ΚΑΙ η πρόταση[i+1]
    αρχίζει με ελληνικό suffix + τελεία (π.χ. 'ους.', 'ς.', 'κων.'),
    τότε το suffix ανήκει στο τέλος της προηγούμενης πρότασης.
    Ενώνουμε και συνεχίζουμε με ό,τι μένει στην πρόταση[i+1].
    """
    if not sentences:
        return sentences

    sents = list(sentences)

    result = []
    i = 0
    while i < len(sents):
        sent = sents[i]

        if i + 1 < len(sents):
            next_sent = sents[i + 1]
            if sent and sent[-1] not in '.;·»"':
                m = _DANGLING_SUFFIX_RE.match(next_sent)
                if m:
                    suffix = m.group(1)
                    remainder = next_sent[m.end():]
                    result.append(sent + suffix + '.')
                    if remainder.strip():
                        sents[i + 1] = remainder
                    else:
                        i += 2
                        continue
                    i += 1
                    continue

        result.append(sent)
        i += 1

    return result


# ======================================================
# Post-processing 2: split σε paragraph markers
# ======================================================
def split_on_paragraph_starts(sentences: list[str]) -> list[str]:
    result = []
    for sent in sentences:
        for part in _PARA_MARKER_RE.split(sent):
            for sub in _STRUCT_HEADER_SPLIT_RE.split(part):
                sub = sub.strip()
                if sub:
                    result.append(sub)
    return result


# ======================================================
# Post-processing 3: αφαίρεση trailing markers
# ======================================================
def fix_trailing_markers(sentences: list[str]) -> list[str]:
    result = []
    pending_prefix = None

    for sent in sentences:
        if pending_prefix:
            sent = pending_prefix + " " + sent
            pending_prefix = None

        m = _TRAILING_MARKER_RE.search(sent)
        if m:
            marker = m.group(1)
            sent_clean = sent[:m.start()].strip()
            if sent_clean:
                result.append(sent_clean)
            pending_prefix = marker
        else:
            result.append(sent)

    if pending_prefix:
        result.append(pending_prefix)

    return result


# ==========================================================
# Post-processing 4: strip headers από την αρχή της πρότασης
# ==========================================================
def strip_leading_headers(sentences: list[str]) -> list[str]:
    result = []
    for sent in sentences:
        cleaned = strip_headers_from_sent(sent)
        result.append(cleaned if cleaned else sent)
    return result


# "Υπόλειμμα" αρχής από προηγούμενη παράγραφο (π.χ. "παρ. 1.") 
_LEADING_FRAGMENT_RE = re.compile(
    r'^(παρ|άρθ|περ|εδ|στοιχ|υποπαρ)\.\s*\d*[α-ω]?\.?\s*$', re.I | re.UNICODE)
# Σκέτος αριθμητικός/enumeration marker στην αρχή (π.χ. "1.", "α)") που απέμεινε μπροστά από επικεφαλίδα.
_LEADING_MARKER_RE = re.compile(
    r'^(\d{1,3}[.)]|[α-ω]{1,4}[.)]|\([α-ω]{1,4}\))\s*$', re.UNICODE)
# Παρένθεση παραπομπής, π.χ. "(άρθρο 10 Οδηγίας 2021/1187)".
_REF_PAREN_RE = re.compile(r'^\((άρθρο|Άρθρο|βλ)\.?\s+[^\n]+\)$', re.UNICODE)
# Επικεφαλίδα άρθρου, για τον εντοπισμό τίτλου που ακολουθεί.
_ARTICLE_HEADER_RE = re.compile(r'^(?:Ά|Α)ρθρο\s+\d+|^ΑΡΘΡΟ\s+\d+', re.UNICODE)
# Σχήμα τίτλου: σύντομη γραμμή με κεφαλαίο αρχικό, χωρίς ρήμα-δείκτη.
_TITLE_SHAPE_RE = re.compile(
    r'^[Α-ΩΆΈΉΊΌΎΏ][α-ωά-ώ]+(?:\s+[Α-Ωα-ωά-ώ]+){0,4}$', re.UNICODE)
_HEADER_VERB_RE = re.compile(
    r'(υποχρεού|οφείλ|πρέπει|υποβάλλ|διαβιβ|κοινοποι|γνωστοποι|'
    r'αποστέλλ|ενημερ|αναφέρ|καταρτίζ|δηλών)', re.I)


def strip_headers_from_sent(text: str) -> str:
    """
    Αφαιρεί αρχικές γραμμές-θόρυβο: δομικές επικεφαλίδες, υπολείμματα (παρ./άρθ.), παρενθέσεις παραπομπής, και τίτλους άρθρων. Ο τίτλος
    αφαιρείται μόνο αν προηγήθηκε επικεφαλίδα "Άρθρο N" και η γραμμή δεν περιέχει ρήμα-δείκτη υποχρέωσης/αναφοράς (ώστε να μη χαθεί σύντομη RO).
    """
    lines = text.split('\n')
    first_content = 0
    prev_was_article = False
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            first_content = i + 1
            continue
        # Αφαίρεση αρχικού marker που κόλλησε μπροστά από επικεφαλίδα
        # (π.χ. "1. Άρθρο 26" -> ελέγχεται ως "Άρθρο 26").
        demarked = re.sub(r'^(\d{1,3}[.)]|[α-ω]{1,4}[.)]|\([α-ω]{1,4}\))\s+',
                          '', stripped)
        is_noise = (
            _HEADER_LINE_RE.match(stripped)
            or _HEADER_LINE_RE.match(demarked)
            or _LEADING_FRAGMENT_RE.match(stripped)
            or _LEADING_MARKER_RE.match(stripped)
            or _REF_PAREN_RE.match(stripped)
            or (prev_was_article
                and _TITLE_SHAPE_RE.match(stripped)
                and not _HEADER_VERB_RE.search(stripped))
        )
        if is_noise:
            first_content = i + 1
            prev_was_article = bool(_ARTICLE_HEADER_RE.match(stripped)
                                    or _ARTICLE_HEADER_RE.match(demarked))
        else:
            break

    if first_content == 0:
        return text

    remaining = '\n'.join(lines[first_content:]).strip()
    return remaining if remaining else text


# ======================================================
# Post-processing 5: Αφαίρεση standalone markers
# ======================================================
def remove_standalone_markers(sentences: list[str]) -> list[str]:
    return [s for s in sentences if not _STANDALONE_MARKER_RE.match(s.strip())]


# ======================================================
# Post-processing 6: Αφαίρεση boilerplate τέλους νόμου
# ======================================================
def remove_boilerplate(sentences: list[str]) -> list[str]:
    return [s for s in sentences if not _BOILERPLATE_RE.search(s)]


def strip_junk_prefix(sentences: list[str]) -> list[str]:
    """Αφαιρεί θορυβώδη προθέματα (ΕΕ), ΔΕ., διπλός αριθμός) από την αρχή."""
    return [_JUNK_PREFIX_RE.sub('', s, count=1).strip() for s in sentences]


# ======================================================
# Build pipeline
# ======================================================
def build_legal_nlp_gr():
    nlp = spacy.load("el_core_news_lg", disable=["parser", "ner"])

    dotted_acronym_re = re.compile(
        r"(?:[Α-ΩA-Zα-ωa-z]{1,4}\.){1,}[Α-ΩA-Zα-ωa-z]{0,4}\.?"
    )
    old_token_match = nlp.tokenizer.token_match

    def custom_token_match(text):
        if dotted_acronym_re.fullmatch(text):
            return True
        if old_token_match is not None:
            return old_token_match(text)
        return False

    nlp.tokenizer.token_match = custom_token_match

    nlp.add_pipe("sentencizer")
    nlp.add_pipe("merge_multilevel_numbers_gr", last=True)
    nlp.add_pipe("block_numbering_gr", last=True)
    nlp.add_pipe("legal_fix_gr", last=True)

    return nlp


# ======================================================
# Regex: Απομόνωση επικεφαλίδας πριν το spaCy
# ======================================================
# Εισάγει όριο πρότασης (τελεία) πριν από επικεφαλίδα που βρίσκεται μόνη σε γραμμή χωρίς να προηγείται τελική στίξη, ώστε το spaCy να τη σπάσει σωστά
# και να μην κολλήσει με την προηγούμενη διάταξη.
_ISOLATE_HEADER_RE = re.compile(
    r'(?<=[^\n.·;:!])\n(\s*)('
    r'(?:Ά|Α)ρθρο\s+\d+[Α-ΩA-Zα-ω]?'
    r'|ΑΡΘΡΟ\s+\d+[Α-ΩA-Zα-ω]?'
    r'|ΚΕΦΑΛΑΙΟ\s+[Α-ΩΆ-Ώ\d]'
    r'|ΜΕΡΟΣ\s+[Α-ΩΆ-Ώ\d]'
    r'|ΤΜΗΜΑ\s+[Α-ΩΆ-Ώ\d]'
    r'|ΤΙΤΛΟΣ\s+[Α-ΩΆ-Ώ\d]'
    r')',
    re.UNICODE,
)


def isolate_headers(text: str) -> str:
    """Εισάγει τελεία-όριο πριν από δομικές επικεφαλίδες μόνες σε γραμμή."""
    return _ISOLATE_HEADER_RE.sub(lambda m: '.\n' + m.group(1) + m.group(2), text)


# ======================================================
# Public API
# ======================================================
def split_and_clean(text: str, nlp, chunk_size: int = 300_000,
                    isolate_structural_headers: bool = True) -> list[str]:
    """
    Πλήρης διάσπαση και καθαρισμός ενός νομικού κειμένου: chunked spaCy
    split και στη συνέχεια τα post-processing βήματα.

    Τα CRLF και τα non-breaking spaces κανονικοποιούνται ώστε η λογική
    διάσπασης να λειτουργεί σωστά. Αν isolate_structural_headers=True,
    οι δομικές επικεφαλίδες (Άρθρο N, ΚΕΦΑΛΑΙΟ κ.λπ.) απομονώνονται πριν
    το spaCy, ώστε να μην κολλάνε με τις γειτονικές διατάξεις.
    """
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = text.replace('\xa0', ' ').replace('\u2009', ' ').replace('\u202f', ' ')
    if isolate_structural_headers:
        text = isolate_headers(text)
    sentences = _spacy_split(text, nlp, chunk_size)
    sentences = fix_dangling_suffixes(sentences)
    sentences = split_on_paragraph_starts(sentences)
    sentences = fix_trailing_markers(sentences)
    sentences = strip_leading_headers(sentences)
    sentences = remove_standalone_markers(sentences)
    sentences = remove_boilerplate(sentences)
    sentences = strip_junk_prefix(sentences)
    return sentences


def _spacy_split(text: str, nlp, chunk_size: int = 300_000) -> list[str]:
    """
    Διάσπαση μεγάλων κειμένων σε chunks (default 300K χαρακτήρες) πριν
    το spaCy, με το όριο κάθε chunk σε φυσικό σημείο στίξης.
    """
    sentences = []
    start = 0
    length = len(text)

    while start < length:
        end = min(start + chunk_size, length)
        if end < length:
            cut = max(
                text.rfind('.', start, end),
                text.rfind(';', start, end),
                text.rfind(':', start, end)
            )
            if cut != -1:
                end = cut + 1

        doc = nlp(text[start:end])
        sentences.extend(
            sent.text.strip()
            for sent in doc.sents
            if sent.text.strip()
        )
        start = end

    return sentences
