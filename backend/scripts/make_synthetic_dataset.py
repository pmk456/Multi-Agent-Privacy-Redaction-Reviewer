"""Generate backend/tests/fixtures/synthetic_cross_document.json.

    python scripts/make_synthetic_dataset.py          (from backend/)

Seeded and deterministic: running it twice gives byte-identical output.
Everything is FICTIONAL: invented people and organisations, emails @example.com/.org/.net,
phones +1-202-555-01xx, SSN-like numbers with area 900-999.

Design
------
* Text and offsets are built together (`Doc.s(...)` appends a sentence and records spans).
  No offset is ever counted by hand.
* RISKY targets: each of their documents shows fewer than three quasi-identifier types, kept
  out of the sentence that names them, so the first-pass policy keeps them readable. Only
  the combination across documents is unique (k = 1). That is the case Agent 5 exists for.
* CONTROL targets: even the union of everything their documents reveal matches >= 3 registry
  people, so nothing should be flagged.
* expected_strategies are derived here from policies.json with an implementation written
  from the rule definitions. tests/test_synthetic_dataset.py cross-checks every one against
  the knowledge base's PolicyEngine, so the two derivations must agree.
"""

from __future__ import annotations

import json
import random
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from privacy_review.datasets.synthetic_schema import (  # noqa: E402
    ATTRIBUTE_FIELD,
    EdgeCase,
    ExpectedStrategy,
    Mention,
    PlantedRisk,
    RegistryPerson,
    SyntheticDataset,
    SyntheticDocument,
)
from privacy_review.schemas.policy import RiskLevel, Strategy  # noqa: E402

SEED = 247
BACKEND = Path(__file__).resolve().parents[1]
OUT = BACKEND / "tests" / "fixtures" / "synthetic_cross_document.json"
KB_PATH = BACKEND / "privacy_review" / "knowledge_base" / "policies.json"

THREAT_MODEL = (
    "The attacker sees a release in which direct identifiers are replaced but PERSON "
    "pseudonyms are batch-consistent (policies.json: PERSON pseudonym_scope = batch), so "
    "documents about the same person can be linked. The attacker knows the registry (the "
    "outside world) and matches the quasi-identifiers visible across a person's linked "
    "documents against it. anonymity_set_size (k) is computed over the attributes as "
    "written in the source documents; anonymity_set_size_after_first_pass over only those "
    "still readable after the expected first-pass strategies (kept values, plus age bands, "
    "since generalising an age to a 10-year band preserves the band). expected_strategies "
    "are Agent 2's first-pass decisions under policies.json, before any Agent 4/5 "
    "remediation. A planted risk that is reidentifiable and survives_first_pass must be "
    "flagged by Agent 5; a control (k >= 3) must not be."
)

# ============================================================================ registry

WIRF, WINS = "Western India Radiology Forum 2025", "Western India Nursing Summit 2025"
QFD, DAIC = "Quillon Founders' Day 2025", "Deccan AI Conference 2025"
IBS, CFF = "Indus Bioinformatics Symposium 2025", "Coastal Finance Forum 2024"
MARLOW, QUILLON = "Marlow Bay Hospital", "Quillon Analytics"
KESTREL, FERN, VELL = "Kestrelmoor University", "Fernhollow Biolabs", "Velloran Finance Ltd"

TARGETS = [
    ("T01", "Ananya Rao", "consultant radiologist", MARLOW, "Radiology", "Mumbai", "40-49", "female", [WIRF]),
    ("T02", "Vikram Rao", "customer support engineer", QUILLON, "Customer Support", "Pune", "20-29", "male", [QFD]),
    ("T03", "Meghna Iyer", "assistant warden", KESTREL, "Girls' Hostel", "Bengaluru", "30-39", "female", []),
    ("T04", "Rohan Mehta", "data science manager", QUILLON, "Data Science", "Pune", "40-49", "male", [QFD]),
    ("T05", "Lukas Brenner", "solutions architect", QUILLON, "Platform Engineering", "Pune", "30-39", "male", [QFD, DAIC]),
    ("T06", "Kavya Menon", "events coordinator", VELL, "Corporate Communications", "Chennai", "30-39", "female", [CFF]),
    ("T07", "Priya Nair", "staff nurse", MARLOW, "Nursing", "Mumbai", "30-39", "female", [WINS]),
    ("T08", "Sandeep Kulkarni", "assistant professor", KESTREL, "Computer Science", "Bengaluru", "30-39", "male", [DAIC]),
    ("T09", "Neha Joshi", "research scientist", FERN, "Genomics", "Hyderabad", "20-29", "female", [IBS]),
]

# (occupation, organization, department, city, age_band, gender, events) - C01..C31 in order
CROWD = [
    ("consultant radiologist", MARLOW, "Radiology", "Mumbai", "30-39", "male", []),               # C01
    ("consultant radiologist", MARLOW, "Radiology", "Mumbai", "50-59", "female", [WIRF]),         # C02
    *[("staff nurse", MARLOW, "Nursing", "Mumbai", "30-39", "female", [WINS])] * 4,               # C03-C06
    ("staff nurse", MARLOW, "Nursing", "Mumbai", "30-39", "male", [WINS]),                        # C07
    ("staff nurse", MARLOW, "Nursing", "Mumbai", "20-29", "female", []),                          # C08
    ("receptionist", MARLOW, "Front Office", "Mumbai", "20-29", "female", []),                    # C09
    *[("customer support engineer", QUILLON, "Customer Support", "Pune", "20-29", "male", [QFD])] * 3,  # C10-C12
    ("customer support engineer", QUILLON, "Customer Support", "Pune", "20-29", "female", []),    # C13
    ("solutions architect", QUILLON, "Platform Engineering", "Pune", "40-49", "female", [QFD, DAIC]),  # C14
    ("data science manager", QUILLON, "Data Science", "Hyderabad", "30-39", "female", []),        # C15
    ("data analyst", QUILLON, "Data Science", "Pune", "20-29", "female", [QFD]),                  # C16
    ("HR manager", QUILLON, "People Operations", "Pune", "30-39", "female", [QFD]),               # C17
    ("assistant warden", KESTREL, "Boys' Hostel", "Bengaluru", "30-39", "male", []),              # C18
    ("warden", KESTREL, "Girls' Hostel", "Bengaluru", "50-59", "female", []),                     # C19
    *[("assistant professor", KESTREL, "Computer Science", "Bengaluru", "30-39", "male", [DAIC])] * 3,  # C20-C22
    ("assistant professor", KESTREL, "Computer Science", "Bengaluru", "30-39", "female", [DAIC]), # C23
    ("librarian", KESTREL, "Central Library", "Bengaluru", "40-49", "female", []),                # C24
    *[("research scientist", FERN, "Genomics", "Hyderabad", "20-29", "female", [IBS])] * 3,       # C25-C27
    ("lab technician", FERN, "Genomics", "Hyderabad", "20-29", "male", []),                       # C28
    ("events coordinator", VELL, "Corporate Communications", "Kochi", "20-29", "female", [CFF]),  # C29
    ("accountant", VELL, "Finance", "Chennai", "30-39", "male", []),                              # C30
    ("accountant", VELL, "Finance", "Chennai", "40-49", "female", [CFF]),                         # C31
]

FIRST = {
    "female": ["Aditi", "Bhavana", "Charu", "Deepa", "Esha", "Gauri", "Harini", "Isha", "Jaya",
               "Kriti", "Lavanya", "Madhuri", "Nandini", "Pallavi", "Rhea", "Ritika", "Shalini",
               "Sneha", "Tanvi", "Uma", "Varsha", "Yamini", "Zoya", "Mitali"],
    "male": ["Aarav", "Abhay", "Arjun", "Bharat", "Chirag", "Dev", "Farhan", "Gautam", "Harish",
             "Imran", "Jatin", "Karan", "Kunal", "Manish", "Naveen", "Nikhil", "Omkar", "Pranav",
             "Rahul", "Ritesh", "Siddharth", "Tarun", "Varun", "Yash"],
}
# Target surnames are excluded so that the only shared surname is the planted one.
SURNAMES = ["Banerjee", "Bhat", "Chawla", "Desai", "Dutta", "Gill", "Gupta", "Hegde", "Jain",
            "Kamath", "Kapoor", "Khanna", "Malhotra", "Mishra", "Naidu", "Patil", "Pillai",
            "Reddy", "Saxena", "Sethi", "Shah", "Shetty", "Sinha", "Thakur", "Tiwari", "Varma",
            "Wagh", "Zaveri"]


def build_registry(rng: random.Random) -> list[RegistryPerson]:
    people = [
        RegistryPerson(person_id=pid, name=name, is_target=True, occupation=occ, organization=org,
                       department=dept, city=city, age_band=band, gender=g, events=list(ev))
        for pid, name, occ, org, dept, city, band, g, ev in TARGETS
    ]
    used = {p.name for p in people}
    for i, (occ, org, dept, city, band, g, ev) in enumerate(CROWD, start=1):
        while True:
            name = f"{rng.choice(FIRST[g])} {rng.choice(SURNAMES)}"
            if name not in used:
                used.add(name)
                break
        people.append(RegistryPerson(person_id=f"C{i:02d}", name=name, is_target=False,
                                     occupation=occ, organization=org, department=dept, city=city,
                                     age_band=band, gender=g, events=list(ev)))
    return people


# ============================================================================ text building

@dataclass
class M:
    text: str
    entity_type: str
    person_id: Optional[str]
    value_kind: str
    attribute: Optional[str] = None
    attribute_value: Optional[str] = None
    contradicts: bool = False


class Doc:
    def __init__(self, doc_id: str, doc_type: str):
        self.doc_id, self.doc_type = doc_id, doc_type
        self.text = ""
        self.sentences = 0
        self.mentions: list[Mention] = []

    def s(self, *parts, sep: str = " ") -> "Doc":
        """Append one sentence (or list line). Mentions are recorded with their spans."""
        if self.sentences:
            self.text += sep
        for part in parts:
            if isinstance(part, str):
                self.text += part
                continue
            start = len(self.text)
            self.text += part.text
            self.mentions.append(Mention(
                doc_id=self.doc_id, start=start, end=len(self.text), entity_type=part.entity_type,
                person_id=part.person_id, value_kind=part.value_kind,
                sentence_index=self.sentences, attribute=part.attribute,
                attribute_value=part.attribute_value, contradicts_registry=part.contradicts,
            ))
        self.sentences += 1
        return self

    def line(self, *parts) -> "Doc":
        return self.s(*parts, sep="\n")


def band_of(age: int) -> str:
    lo = age // 10 * 10
    return f"{lo}-{lo + 9}"


# mention helpers -------------------------------------------------------------
def name(text, pid, kind="full_name"):
    return M(text, "PERSON", pid, kind)


def occ(text, pid):
    return M(text, "OCCUPATION", pid, "job_title", "OCCUPATION", text)


def org(text, pid, kind="employer"):
    return M(text, "ORGANIZATION", pid, kind, "ORGANIZATION" if pid else None, text if pid else None)


def dept(text, pid, value=None):
    return M(text, "ORGANIZATION", pid, "department", "DEPARTMENT", value or text)


def city(text, pid, contradicts=False):
    return M(text, "LOCATION", pid, "city", "LOCATION" if pid else None, text if pid else None, contradicts)


def age(text, pid, band, kind="exact_age"):
    return M(text, "AGE", pid, kind, "AGE", band)


def event(text, pid, kind="named_event", in_registry=True):
    attr = pid is not None and in_registry
    return M(text, "EVENT", pid, kind, "EVENT" if attr else None, text if attr else None)


def date(text, pid, kind):
    return M(text, "DATE", pid, kind)


def email(text, pid):
    return M(text, "EMAIL_ADDRESS", pid, "email")


def phone(text, pid):
    return M(text, "PHONE_NUMBER", pid, "phone")


# ============================================================================ documents

def build_documents(reg: dict[str, RegistryPerson], rng: random.Random) -> list[Doc]:
    C = lambda n: reg[f"C{n:02d}"]                                       # noqa: E731
    docs: list[Doc] = []

    def add(d: Doc) -> Doc:
        docs.append(d)
        return d

    # --- T01 Ananya Rao (risky) -------------------------------------------------------
    add(Doc("hr-001", "hr_record")
        .s("Staff record update.")
        .s(name("Dr. Ananya Rao", "T01", "titled_full_name"), " has joined the imaging team.")
        .s("She works as a ", occ("consultant radiologist", "T01"), " at ", org(MARLOW, "T01"), ".")
        .s("Contact: ", email("ananya.rao@example.org", "T01"), ", ", phone("+1-202-555-0111", "T01"), ".")
        .s("Employee ID: ", M("EMP-40112", "RECORD_IDENTIFIER", "T01", "employee_id"), "."))
    add(Doc("bio-001", "speaker_bio")
        .s("Speaker profile: ", name("A. Rao", "T01", "initial_surname"), ".")
        .s("The speaker is ", age("in her forties", "T01", "40-49", "age_decade_phrase"),
           " and lives in ", city("Mumbai", "T01"), ".")
        .s("Her talk covers low-dose CT screening."))
    add(Doc("news-001", "news_item")
        .s("Imaging award announced.")
        .s(name("Dr. Rao", "T01", "titled_surname"), " received this year's ",
           event("Silver Lens award", "T01", "award", in_registry=False), " for her screening research."))

    # --- alumni newsletter: T01 + T02 share a surname; T08 ------------------------------
    add(Doc("alumni-001", "alumni_newsletter")
        .s(org(KESTREL, None, "publisher"), " alumni notes.")
        .s(name("Ananya Rao", "T01"), " (MBBS, class of ", date("2008", "T01", "graduation_year"),
           ") sent greetings to her classmates.")
        .s(name("Vikram Rao", "T02"), " (BTech, class of ", date("2021", "T02", "graduation_year"),
           ") has joined a software company.")
        .s(name("Sandeep Kulkarni", "T08"), ", now ", age("in his thirties", "T08", "30-39", "age_decade_phrase"),
           ", has returned to campus as faculty."))

    # --- T02 Vikram Rao (control) + T04 shared ticket ----------------------------------
    add(Doc("tkt-001", "support_ticket")
        .s("Ticket QA-5521.")
        .s("Raised by ", email("rohan.mehta@example.com", "T04"), ": VPN access fails from the ",
           city("Pune", "T04"), " office.")
        .s("Assigned to ", name("Vikram Rao", "T02"), ", ", occ("customer support engineer", "T02"), "."))

    rota = Doc("memo-001", "internal_memo").s("Support rota for next week.")
    members = [reg["T02"], *(C(n) for n in (10, 11, 12, 13))]
    rng.shuffle(members)
    for p in members:
        rota.line(name(p.name, p.person_id), " - ", occ(p.occupation, p.person_id), ", ",
                  dept(p.department, p.person_id), ", ", org(p.organization, p.person_id), ", ",
                  city(p.city, p.person_id))
    add(rota)

    founders = Doc("att-001", "attendee_list").s("Attendance record.")
    members = [reg["T02"], *(C(n) for n in (10, 11, 12, 14, 16, 17))]
    rng.shuffle(members)
    for p in members:
        years = 24 if p.person_id == "T02" else rng.randint(int(p.age_band[:2]), int(p.age_band[:2]) + 9)
        founders.line(name(p.name, p.person_id), ", ", age(str(years), p.person_id, band_of(years)),
                      ", attended ", event(QFD, p.person_id), ".")
    add(founders)

    # --- T03 Meghna Iyer (risky through a document with no name) -----------------------
    add(Doc("hr-002", "hr_record")
        .s("Staff record.")
        .s(name("Meghna Iyer", "T03"), " is an ", occ("assistant warden", "T03"), " in the ",
           dept("Girls' Hostel", "T03"), " at ", org(KESTREL, "T03"), ".")
        .s("Age: ", age("36", "T03", "30-39"), ".")
        .s("Phone: ", phone("+1-202-555-0123", "T03"), "."))
    add(Doc("leave-001", "leave_note")
        .s("Leave note.")
        .s(name("Meghna Iyer", "T03"), " is on approved leave from ",
           date("10 to 14 June 2025", "T03", "leave_period"), ".")
        .s("Cover will be arranged by the housing office."))
    add(Doc("memo-002", "internal_memo")
        .s("Housing office memo.")
        .s("The only ", occ("assistant warden", "T03"), " of the ", dept("girls' hostel", "T03", "Girls' Hostel"),
           " at ", org(KESTREL, "T03"), ", who joined in ", date("March 2024", "T03", "join_date"),
           ", has asked to move to day shifts.")
        .s("Please send replies to the housing office."))

    # --- T04 Rohan Mehta (risky; shared email; DOB + postcode + gender) ----------------
    add(Doc("hr-003", "hr_record")
        .s("New appointment.")
        .s(name("Rohan Mehta", "T04"), " has been appointed to lead the analytics group.")
        .s("The post is ", occ("data science manager", "T04"), " at ", org(QUILLON, "T04"), ".")
        .s("Email: ", email("rohan.mehta@example.com", "T04"), ".")
        .s("Employee ID: ", M("EMP-30418", "RECORD_IDENTIFIER", "T04", "employee_id"), "."))
    add(Doc("leave-002", "leave_note")
        .s("Benefits enrolment form.")
        .line("Employee ID: ", M("EMP-30418", "RECORD_IDENTIFIER", "T04", "employee_id"))
        .line("Date of birth: ", M("14 August 1981", "DATE_OF_BIRTH", "T04", "date_of_birth"))
        .line("Postcode: ", M("411045", "POSTAL_CODE", "T04", "postcode"))
        .line("Gender: ", M("male", "DEMOGRAPHIC", "T04", "gender", "DEMOGRAPHIC", "male"))
        .line("SSN: ", M("912-55-0148", "GOVERNMENT_ID", "T04", "ssn_like")))
    add(Doc("news-005", "news_item")
        .s("Town hall summary.")
        .s(name("Rohan Mehta", "T04"), " spoke to staff about the data roadmap.")
        .s("The speaker, who is ", age("in his forties", "T04", "40-49", "age_decade_phrase"),
           ", is based in ", city("Pune", "T04"), "."))

    # --- T05 Lukas Brenner (risky; nationality) ----------------------------------------
    add(Doc("news-002", "news_item")
        .s("Welcome note.")
        .s(name("Lukas Brenner", "T05"), ", a ", M("German", "DEMOGRAPHIC", "T05", "nationality"),
           " national, has joined the ", city("Pune", "T05"), " office."))
    add(Doc("bio-002", "speaker_bio")
        .s("Conference keynote speaker: ", name("Lukas Brenner", "T05"), ".")
        .s("The speaker is a ", occ("solutions architect", "T05"), " at ", org(QUILLON, "T05"), ".")
        .s("The talk is about streaming data platforms."))
    add(Doc("news-003", "news_item")
        .s("Innovation award.")
        .s("This year's innovation award went to ", name("L. Brenner", "T05", "initial_surname"), ".")
        .s("The winner, aged ", age("34", "T05", "30-39"), ", led the data platform redesign."))

    conf = Doc("att-003", "attendee_list").s("Conference attendance.")
    members = [reg["T08"], reg["T05"], *(C(n) for n in (14, 20, 21, 22, 23))]
    rng.shuffle(members)
    for p in members:
        conf.line(name(p.name, p.person_id), ", ", org(p.organization, p.person_id),
                  ", attended the ", event(DAIC, p.person_id), ".")
    add(conf)

    # --- T06 Kavya Menon (risky; conflicting city) -------------------------------------
    add(Doc("hr-004", "hr_record")
        .s("Personnel note.")
        .s(name("Kavya Menon", "T06"), " has moved to the events team.")
        .s("The role is ", occ("events coordinator", "T06"), " at ", org(VELL, "T06"), ".")
        .s("Contact: ", email("kavya.menon@example.net", "T06"), "."))
    add(Doc("leave-004", "leave_note")
        .s("Leave request.")
        .s(name("Kavya Menon", "T06"), " has applied for a week of annual leave.")
        .s("She is ", age("31", "T06", "30-39"), " and works from the ", city("Chennai", "T06"), " office."))
    add(Doc("news-004", "news_item")
        .s("Forum recap.")
        .s("The ", event(CFF, "T06"), " was organised by ", name("Kavya Menon", "T06"),
           ", who is based in ", city("Kochi", "T06", contradicts=True), "."))

    # --- T07 Priya Nair (control; medical condition with name) -------------------------
    add(Doc("leave-003", "leave_note")
        .s("Medical leave note.")
        .s(name("Priya Nair", "T07"), ", ", occ("staff nurse", "T07"), ", is on medical leave until ",
           date("28 February 2025", "T07", "leave_end"), ".")
        .s("She has been diagnosed with a ", M("herniated disc", "MEDICAL_CONDITION", "T07", "diagnosis"), ".")
        .s("Record: ", M("MRN-0012345", "RECORD_IDENTIFIER", "T07", "mrn"), "."))

    roster = Doc("memo-003", "internal_memo").s("Night roster for the coming week.")
    members = [reg["T07"], *(C(n) for n in (3, 4, 5, 6, 7))]
    rng.shuffle(members)
    for p in members:
        roster.line(name(p.name, p.person_id), " - ", occ(p.occupation, p.person_id), ", ",
                    org(p.organization, p.person_id), ", ", city(p.city, p.person_id))
    add(roster)

    summit = Doc("att-002", "attendee_list").s("Delegate confirmations.")
    members = [reg["T07"], *(C(n) for n in (3, 4, 5, 6, 7))]
    rng.shuffle(members)
    for p in members:
        summit.line(name(p.name, p.person_id), " (", org(p.organization, p.person_id), ", ",
                    age("30s", p.person_id, "30-39", "age_decade_phrase"), ") will attend the ",
                    event(WINS, p.person_id), ".")
    add(summit)

    # --- T08 Sandeep Kulkarni (control) -------------------------------------------------
    add(Doc("bio-003", "speaker_bio")
        .s("Conference speaker: ", name("Sandeep Kulkarni", "T08"), ".")
        .s(name("Sandeep Kulkarni", "T08"), " is an ", occ("assistant professor", "T08"), " of ",
           dept("Computer Science", "T08"), " at ", org(KESTREL, "T08"), " in ", city("Bengaluru", "T08"), ".")
        .s("He will speak at the ", event(DAIC, "T08"), "."))

    # --- T09 Neha Joshi (control; isolated dateline) ------------------------------------
    add(Doc("hr-005", "hr_record")
        .s("Staff record.")
        .s(name("Neha Joshi", "T09"), " is a ", occ("research scientist", "T09"), " in the ",
           dept("Genomics", "T09"), " group at ", org(FERN, "T09"), ", ", city("Hyderabad", "T09"), ".")
        .s("Age: ", age("27", "T09", "20-29"), "."))
    add(Doc("memo-004", "internal_memo")
        .s("Report date: ", date("3 February 2025", None, "dateline"), ".")
        .s("Group update.")
        .s(name("Neha Joshi", "T09"), ", aged ", age("27", "T09", "20-29"), ", will present a poster at the ",
           event(IBS, "T09"), "."))
    add(Doc("tkt-002", "support_ticket")
        .s("Ticket IT-0193.")
        .s(name("Neha Joshi", "T09"), " reports that her lab laptop will not boot.")
        .s("Contact: ", email("neha.joshi@example.net", "T09"), ", ", phone("+1-202-555-0164", "T09"), "."))

    # --- organisation-only document: nobody is described --------------------------------
    add(Doc("news-006", "news_item")
        .s(org(MARLOW, None, "subject_organisation"), " opens a cardiac wing.")
        .s("Release date: ", date("12 January 2025", None, "release_date"), ".")
        .s("Location: ", city("Mumbai", None), ".")
        .s("The new wing adds forty beds."))

    return docs


# ============================================================================ first-pass policy

RANKS = ["low", "medium", "high", "critical"]


class Policy:
    """Expected first-pass risk and strategy, written from the rule definitions in policies.json."""

    def __init__(self, kb: dict):
        self.kb = kb
        self.policies = {p["entity_type"]: p for p in kb["entity_policies"]}
        self.forbidden = defaultdict(set)
        for c in kb["policy_constraints"]:
            for et in c["entity_types"]:
                self.forbidden[et] |= set(c["forbidden_strategies"])

    def participants(self, rule_id: str) -> set[str]:
        rule = next(r for r in self.kb["context_rules"] if r["rule_id"] == rule_id)
        return {*rule["trigger_types"], *rule["requires_all"], *rule["applies_to"]}

    def decide(self, mentions: list[Mention]) -> list[tuple[RiskLevel, Strategy, list[str], str]]:
        raised: dict[int, tuple[str, list[str]]] = {}
        for rule in self.kb["context_rules"]:
            if rule["scope"] == "document":
                groups = [list(range(len(mentions)))]
            else:
                by_sentence = defaultdict(list)
                for i, m in enumerate(mentions):
                    by_sentence[m.sentence_index].append(i)
                groups = list(by_sentence.values())
            for group in groups:
                present = {mentions[i].entity_type for i in group}
                if len(present & set(rule["trigger_types"])) < rule["min_distinct_types"]:
                    continue
                if not set(rule["requires_all"]) <= present:
                    continue
                for i in group:
                    if mentions[i].entity_type in rule["applies_to"]:
                        level, rules = raised.get(i, ("low", []))
                        raised[i] = (max(level, rule["escalate_to"], key=RANKS.index),
                                     rules + [rule["rule_id"]])
        fired_in_doc = {r for _, rules in raised.values() for r in rules}

        out = []
        for i, m in enumerate(mentions):
            policy = self.policies[m.entity_type]
            base = policy["sensitivity"]
            level, rules = raised.get(i, (base, []))
            final = max(base, level, key=RANKS.index)
            fired = list(rules)
            notes = [f"{m.entity_type} base risk {base}"]
            for rid in rules:
                notes.append(f"{rid} raises it to at least {self._escalation(rid)}")
            for exc in self.kb["exceptions"]:
                if exc["entity_type"] != m.entity_type:
                    continue
                if any(r in fired_in_doc and m.entity_type in self.participants(r) for r in exc["unless_rules"]):
                    continue
                isolated = not any(o.sentence_index == m.sentence_index for j, o in enumerate(mentions) if j != i)
                if exc["condition"] == "isolated_in_sentence" and isolated and \
                        RANKS.index(exc["value"]) < RANKS.index(final):
                    final = exc["value"]
                    fired.append(exc["exception_id"])
                    notes.append(f"{exc['exception_id']} caps it at {exc['value']} (alone in its sentence)")
            strategy = Strategy(policy["strategy_by_risk"][final])
            assert strategy.value in policy["allowed_strategies"]
            assert strategy.value not in self.forbidden[m.entity_type]
            scope = " with a batch-consistent pseudonym" if m.entity_type == "PERSON" else ""
            why = "; ".join(notes) + f"; final risk {final} -> {strategy.value}{scope}."
            out.append((RiskLevel(final), strategy, fired, why))
        return out

    def _escalation(self, rule_id: str) -> str:
        return next(r["escalate_to"] for r in self.kb["context_rules"] if r["rule_id"] == rule_id)


# ============================================================================ planted risks

def anonymity_set(registry: list[RegistryPerson], attrs: dict[str, str]) -> int:
    def matches(p: RegistryPerson) -> bool:
        for key, value in attrs.items():
            field = getattr(p, ATTRIBUTE_FIELD[key])
            if (value not in field) if key == "EVENT" else (field != value):
                return False
        return True
    return sum(matches(p) for p in registry)


RISKS = [
    # (risk_id, person_id, doc_ids, why)
    ("R01", "T01", ["hr-001", "bio-001"],
     "Each document shows two quasi-identifier types away from the name, so first-pass policy "
     "keeps them. Combined: the only consultant radiologist at Marlow Bay Hospital in Mumbai "
     "aged 40-49. Linking needs 'Dr. Ananya Rao' and 'A. Rao' to share a pseudonym."),
    ("R02", "T04", ["hr-003", "news-005"],
     "Job title and employer in one document, age band and city in another. Two data science "
     "managers work at Quillon Analytics; only one is in Pune and in his forties."),
    ("R03", "T05", ["bio-002", "news-003"],
     "Job title and employer in the speaker bio, exact age in the award item. Quillon has two "
     "solutions architects; only one is 30-39."),
    ("R04", "T06", ["hr-004", "leave-004"],
     "Velloran has two events coordinators (Chennai and Kochi), both at the Coastal Finance "
     "Forum. Job title and employer in the personnel note; age 31 and Chennai, away from her "
     "name, in the leave request. Either the age band or the city separates them."),
    ("R05", "T03", ["memo-002"],
     "No name anywhere, yet 'the only assistant warden of the girls' hostel' at Kestrelmoor "
     "is one person. The document has three quasi-identifier types, so CTX-01 generalises "
     "them in the first pass; the risk is caught by policy rather than by linkage."),
    ("R06", "T07", ["leave-003", "memo-003", "att-002"],
     "CONTROL. Everything her documents reveal (staff nurse, Marlow Bay Hospital, Mumbai, "
     "30-39, Western India Nursing Summit 2025) is shared by six registry people."),
    ("R07", "T02", ["tkt-001", "memo-001", "att-001", "alumni-001"],
     "CONTROL. Customer support engineer, Customer Support, Quillon Analytics, Pune, 20-29 "
     "and Quillon Founders' Day 2025 together still match four people."),
    ("R08", "T08", ["bio-003", "alumni-001", "att-003"],
     "CONTROL. Assistant professor of Computer Science at Kestrelmoor, Bengaluru, 30-39, "
     "Deccan AI Conference 2025: five registry people share all of it."),
    ("R09", "T09", ["hr-005", "memo-004", "tkt-002"],
     "CONTROL. Research scientist, Genomics, Fernhollow Biolabs, Hyderabad, 20-29, Indus "
     "Bioinformatics Symposium 2025: four registry people share all of it."),
]


def revealed(person_id: str, doc_ids: list[str], mentions: list[Mention],
             strategies: dict[tuple, Strategy] | None = None) -> dict[str, str]:
    """Attributes revealed about a person in doc_ids. With `strategies`, only those still
    readable after the first pass (kept, or an age generalised to its band)."""
    out: dict[str, str] = {}
    for m in mentions:
        if m.person_id != person_id or m.doc_id not in doc_ids or m.attribute is None or m.contradicts_registry:
            continue
        if strategies is not None:
            s = strategies[(m.doc_id, m.start, m.end)]
            if not (s is Strategy.KEEP or (m.attribute == "AGE" and s is Strategy.GENERALIZE)):
                continue
        assert out.get(m.attribute, m.attribute_value) == m.attribute_value, (person_id, m.attribute)
        out[m.attribute] = m.attribute_value
    return out


# ============================================================================ edge cases

EDGE_CASES = [
    ("name_variants_same_person", ["hr-001", "bio-001", "news-001", "alumni-001"],
     "'Dr. Ananya Rao', 'A. Rao', 'Dr. Rao' and 'Ananya Rao' are all T01. Agent 1 should cluster "
     "them as one entity so they receive one batch pseudonym."),
    ("shared_surname_different_people", ["alumni-001"],
     "'Ananya Rao' (T01) and 'Vikram Rao' (T02) share a surname but are different people. A "
     "surname match alone must not merge them or give them the same pseudonym."),
    ("same_email_two_documents", ["hr-003", "tkt-001"],
     "rohan.mehta@example.com appears in both documents (T04). It links them in the raw text; it "
     "must be masked in both, which also breaks that link in the release."),
    ("no_name_still_identifying", ["memo-002"],
     "No PERSON mention, but role + place + join date single out T03 (k = 1). CTX-01 should fire "
     "on the document and generalise the occupation, organisation, department and date."),
    ("dob_postcode_gender", ["leave-002"],
     "Date of birth, postcode and gender in one document: CTX-03 raises all three to high, so the "
     "DOB is generalised and the postcode and gender masked; the SSN-like number is suppressed."),
    ("medical_condition_with_name", ["leave-003"],
     "A diagnosis in a document that names the person (T07): CTX-05 raises it to critical, so it "
     "is suppressed, not just masked."),
    ("demographic_about_named_person", ["news-002"],
     "Nationality stated about a named person (T05) in the same sentence: CTX-06 raises it to "
     "high and it is masked."),
    ("isolated_dateline", ["memo-004", "news-006"],
     "'3 February 2025' and '12 January 2025' stand alone in their sentences and are about nobody. "
     "CTX-01 fires on both documents, but EXC-01 caps these dates at low, so they are kept."),
    ("conflicting_city", ["leave-004", "news-004"],
     "Kavya Menon (T06) works from Chennai (registry) but news-004 says Kochi, where a different "
     "Velloran events coordinator (C29) is based. The conflict must not be resolved by merging her "
     "with C29 or by trusting either city; the Kochi mention is marked contradicts_registry."),
    ("organisation_only_document", ["news-006"],
     "A press release about an organisation that describes no person. Mentions have no person_id; "
     "the isolated date and location stay readable (EXC-01, EXC-02); there is nobody to re-identify."),
]


# ============================================================================ assemble

def build() -> SyntheticDataset:
    rng = random.Random(SEED)
    registry = build_registry(rng)
    by_id = {p.person_id: p for p in registry}
    docs = build_documents(by_id, rng)
    policy = Policy(json.loads(KB_PATH.read_text(encoding="utf-8")))

    mentions: list[Mention] = []
    expected: list[ExpectedStrategy] = []
    for d in docs:
        mentions += d.mentions
        for m, (risk, strategy, fired, why) in zip(d.mentions, policy.decide(d.mentions)):
            expected.append(ExpectedStrategy(
                doc_id=m.doc_id, start=m.start, end=m.end, entity_type=m.entity_type,
                expected_strategy=strategy, risk=risk, fired_rules=fired, why=why,
            ))
    strategies = {(e.doc_id, e.start, e.end): e.expected_strategy for e in expected}

    planted = []
    for risk_id, pid, doc_ids, why in RISKS:
        attrs = revealed(pid, doc_ids, mentions)
        visible = revealed(pid, doc_ids, mentions, strategies)
        k, k_after = anonymity_set(registry, attrs), anonymity_set(registry, visible)
        planted.append(PlantedRisk(
            risk_id=risk_id, person_id=pid, doc_ids=doc_ids,
            combined_attribute_types=sorted(attrs), combined_attributes=dict(sorted(attrs.items())),
            anonymity_set_size=k, reidentifiable=k == 1,
            anonymity_set_size_after_first_pass=k_after, survives_first_pass=k_after == 1, why=why,
        ))

    return SyntheticDataset(
        version="1.0", seed=SEED, threat_model=THREAT_MODEL, registry=registry,
        documents=[SyntheticDocument(doc_id=d.doc_id, doc_type=d.doc_type, text=d.text) for d in docs],
        mentions=mentions, expected_strategies=expected, planted_risks=planted,
        edge_cases=[EdgeCase(case=c, doc_ids=ids, expected_behaviour=b) for c, ids, b in EDGE_CASES],
    )


def render() -> str:
    return json.dumps(build().model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"


if __name__ == "__main__":
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(), encoding="utf-8", newline="\n")
    ds = build()
    risky = sum(r.reidentifiable for r in ds.planted_risks)
    print(f"wrote {OUT}")
    print(f"  {len(ds.documents)} documents, {len(ds.registry)} registry people "
          f"({sum(p.is_target for p in ds.registry)} targets), {len(ds.mentions)} mentions")
    print(f"  planted risks: {risky} re-identifiable, {len(ds.planted_risks) - risky} control")
    for r in ds.planted_risks:
        print(f"  {r.risk_id} {r.person_id} k={r.anonymity_set_size} k_after={r.anonymity_set_size_after_first_pass} "
              f"{sorted(r.combined_attributes)}")
