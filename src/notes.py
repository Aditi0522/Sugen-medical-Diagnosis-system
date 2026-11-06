"""Phase 2: deterministic note parsing. No API, no heavy dependencies.

parse(text) -> NoteView(text, style, lang, span, cues)
  text   NFC-normalised, control characters stripped, capped (original wording kept)
  style  typed_consult | short_consult | ambient_transcript
  lang   en | fr | es | sw | pt | hi | ar   (rough; used for metrics and hints)
  span   the part of the note that states the diagnosis (assessment lines, or the doctor's
         concluding turns, or the best sentence); '' when nothing was found
  cues   {"negated": [...], "uncertain": [...], "history": [...], "family": [...]} snippets
Never ASCII-fold: Swahili, French, Spanish and Hindi text must stay intact.
"""
import re, unicodedata
from dataclasses import dataclass, field

MAX_CHARS = 8000
_CTRL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


def normalise(text):
    t = unicodedata.normalize("NFC", text or "")
    t = _CTRL.sub(" ", t).replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t\u00a0]+", " ", t)
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:MAX_CHARS]


# ---------- labelled lines ("Label: text") ----------
_LABELLED = re.compile(r"^\s*([^:：\n\d]{1,30}?)\s*[:：]\s*(.*)$")

# typed-note section markers (lower-case, no dots/slashes)
_MARKERS = {"s", "o", "a", "p", "subjective", "objective", "assessment", "plan", "imp", "impression",
            "dx", "diagnosis", "diagnoses", "hx", "history", "pe", "exam", "examination", "c/o", "co",
            "rx", "ix", "investigations", "findings", "ros", "hpi", "pmh",
            "diagnostic", "diagnóstico", "tathmini", "utambuzi", "निदान", "योजना"}
_ASSESS = {"a", "assessment", "imp", "impression", "dx", "diagnosis", "diagnoses",
           "diagnostic", "diagnóstico", "tathmini", "utambuzi", "निदान", "मूल्यांकन"}
_DOCTOR = {"doctor", "dr", "doc", "clinician", "physician", "daktari", "médecin", "medecin", "docteur",
           "médico", "medico", "doctora", "डॉक्टर", "चिकित्सक", "d"}


def _label(line):
    m = _LABELLED.match(line)
    if not m:
        return None, line
    lab = m.group(1).strip()
    if len(lab.split()) > 2:
        return None, line
    return lab, m.group(2)


def _key(lab):
    return lab.lower().strip(" .").replace(".", "")


def _turns(text):
    """[(label_or_None, text)] with unlabelled lines appended to the previous turn."""
    turns = []
    for ln in text.split("\n"):
        if not ln.strip():
            continue
        lab, rest = _label(ln)
        if lab is not None:
            turns.append([lab, rest.strip()])
        elif turns:
            turns[-1][1] += " " + ln.strip()
        else:
            turns.append([None, ln.strip()])
    return turns


def detect_style(text):
    labelled = [l for l in (_label(x)[0] for x in text.split("\n")) if l]
    counts = {}
    for l in labelled:
        counts[_key(l)] = counts.get(_key(l), 0) + 1
    speakers = [k for k, c in counts.items() if c >= 2 and k not in _MARKERS]
    if len(labelled) >= 4 and len(speakers) >= 2:
        return "ambient_transcript"
    if any(_key(l) in _MARKERS for l in labelled):
        return "typed_consult"
    if len(text) > 600 and text.count("\n") >= 3:
        return "typed_consult"
    return "short_consult"


# ---------- assessment span ----------
_STRONG = re.compile(
    r"diagnos|you have|you've got|you are having|this is|we call|consistent with|shows? |suggests?|"
    r"what we have|looks like|vous avez|il s'agit|on appelle|diagnostic|usted tiene|tiene |se trata|"
    r"se llama|utambuzi|una ugonjwa|ni ugonjwa|tunauita|निदान|आपको|कहते हैं", re.I)
_WEAK = re.compile(r"\bit is\b|\bit's\b|\bi think\b|likely|probabl|c'est|parece|inaonekana|huenda", re.I)
_SENT_CUE = re.compile(r"diagnos|impression|\bdx\b|consistent with|\bc/w\b|likely|probable|suspect|"
                       r"presents? with|diagnostic|diagnóstico|utambuzi", re.I)


def _doctor_label(turns):
    labs = {}
    for lab, txt in turns:
        if lab:
            labs[lab] = labs.get(lab, 0) + len(txt)
    for lab in labs:
        if _key(lab) in _DOCTOR:
            return lab
    return max(labs, key=labs.get) if labs else None


def assessment_span(text, style):
    if style == "ambient_transcript":
        turns = _turns(text)
        doc = _doctor_label(turns)
        mine = [t for lab, t in turns if lab == doc]
        strong = [t for t in mine if _STRONG.search(t)]
        pick = strong or [t for t in mine if _WEAK.search(t)]
        return " ".join(pick[:4])[:700]
    if style == "typed_consult":
        out, grab = [], False
        for ln in text.split("\n"):
            lab, rest = _label(ln)
            if lab is not None:
                grab = _key(lab) in _ASSESS
                if grab and rest.strip():
                    out.append(rest.strip())
            elif grab and ln.strip():
                out.append(ln.strip())
            elif not ln.strip():
                grab = False
        if out:
            return " ".join(out)[:700]
    # short note, or a typed note with no recognised marker: inline marker, then best sentences
    m = re.search(r"\b(?:Imp|Impression|Dx|Diagnosis|Assessment)\b\s*[:\-]\s*([^\n]{3,300})", text, re.I)
    if m:
        return m.group(1).strip()
    sents = [s.strip() for s in re.split(r"(?<=[.;!?])\s+|\n", text) if s.strip()]
    pick = [s for s in sents if _SENT_CUE.search(s)]
    return " ".join(pick[:2])[:500]


# ---------- cues ----------
_CUES = {
    "negated": re.compile(r"\b(ruled out|rule out|r/o|excluded|denies|denied|negative for|neg for|unlikely|"
                          r"not (?:consistent|suggestive) with)\b", re.I),
    "uncertain": re.compile(r"\b(possible|probable|probably|suspected|suspect|query|likely|maybe|may be)\b|\?", re.I),
    "history": re.compile(r"\b(h/o|hx of|history of|previously|known|past|prior)\b", re.I),
    "family": re.compile(r"\b(family history|fh|mother|father|sibling|brother|sister)\b", re.I),
}


def find_cues(text, per_kind=4, width=35):
    out = {}
    for kind, rx in _CUES.items():
        snips = []
        for m in rx.finditer(text):
            a, b = max(0, m.start() - width), min(len(text), m.end() + width)
            snips.append(text[a:b].replace("\n", " ").strip())
            if len(snips) >= per_kind:
                break
        out[kind] = snips
    return out


def hints(view):
    """Short text block for the LLM, or '' when there is nothing to say."""
    lines = []
    for kind, label in (("negated", "ruled out / negated"), ("uncertain", "uncertain"),
                        ("history", "history"), ("family", "family history")):
        if view.cues.get(kind):
            lines.append(f"- {label}: " + " | ".join(view.cues[kind][:3]))
    return "HINTS (cue words found by a simple scan; may be wrong):\n" + "\n".join(lines) if lines else ""


# ---------- language (rough) ----------
_STOPS = {
    "en": "the and with of for has is was patient pain fever since no days".split(),
    "fr": "le la les des est avec pas pour une depuis patient douleur fièvre je vous".split(),
    "es": "el los las del con para una desde dolor fiebre paciente tiene usted".split(),
    "sw": "na ya wa kwa ni la hii huyu mgonjwa siku homa kikohozi anaumwa ana amekuwa".split(),
    "pt": "o os as do da com para uma desde dor febre paciente tem você não".split(),
}


def detect_lang(text):
    sample = text[:2000]
    if re.search(r"[\u0900-\u097F]", sample):
        return "hi"
    if re.search(r"[\u0600-\u06FF]", sample):
        return "ar"
    words = re.findall(r"[^\W\d_]+", sample.lower())
    score = {k: sum(w in set(v) for w in words) for k, v in _STOPS.items()}
    best = max(score, key=score.get)
    return best if score[best] >= 3 and score[best] > score["en"] else "en"


# ---------- abbreviations (used on the search query only) ----------
ABBREV = {
    "HTN": "hypertension", "DM": "diabetes mellitus", "T2DM": "type 2 diabetes mellitus",
    "T1DM": "type 1 diabetes mellitus", "GDM": "gestational diabetes mellitus",
    "URTI": "upper respiratory tract infection", "LRTI": "lower respiratory tract infection",
    "UTI": "urinary tract infection", "TB": "tuberculosis", "PTB": "pulmonary tuberculosis",
    "PID": "pelvic inflammatory disease", "COPD": "chronic obstructive pulmonary disease",
    "GERD": "gastro-oesophageal reflux disease", "PUD": "peptic ulcer disease",
    "CKD": "chronic kidney disease", "AKI": "acute kidney injury", "CCF": "congestive cardiac failure",
    "CHF": "congestive heart failure", "MI": "myocardial infarction", "CVA": "stroke cerebrovascular accident",
    "TIA": "transient ischaemic attack", "DVT": "deep vein thrombosis", "OA": "osteoarthritis",
    "RA": "rheumatoid arthritis", "BPH": "benign prostatic hyperplasia", "IBS": "irritable bowel syndrome",
    "STI": "sexually transmitted infection", "PCOS": "polycystic ovary syndrome",
    "PIH": "pregnancy induced hypertension", "AGE": "acute gastroenteritis", "AOM": "acute otitis media",
    "LBP": "low back pain", "BV": "bacterial vaginosis", "VVC": "vulvovaginal candidiasis",
    "PUO": "pyrexia of unknown origin", "SAM": "severe acute malnutrition", "ARI": "acute respiratory infection",
    "IDA": "iron deficiency anaemia", "RTI": "respiratory tract infection", "HIV": "human immunodeficiency virus",
}
_ABBR_RX = re.compile(r"\b(" + "|".join(sorted(ABBREV, key=len, reverse=True)) + r")\b")


def expand_abbrev(s):
    return _ABBR_RX.sub(lambda m: f"{m.group(1)} {ABBREV[m.group(1)]}", s or "")


# ---------- main ----------
@dataclass
class NoteView:
    text: str
    style: str
    lang: str
    span: str
    cues: dict = field(default_factory=dict)


def parse(raw):
    text = normalise(raw)
    style = detect_style(text)
    return NoteView(text=text, style=style, lang=detect_lang(text),
                    span=assessment_span(text, style), cues=find_cues(text))
