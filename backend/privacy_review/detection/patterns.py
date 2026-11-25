"""Deterministic pattern detectors for formats Presidio does not cover, or covers only with
checksum validation that synthetic and real-world-but-mistyped values fail.

Each PatternSpec yields Candidates. `group` selects a capture group when the regex includes
a context keyword (e.g. "password: <value>") - only the value is redacted, not the keyword.
Context words within `context_window` characters before the match raise the score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Callable, Optional

from privacy_review.detection.candidates import Candidate
from privacy_review.schemas.entities import DetectionSource, EntityType as E


@dataclass
class PatternSpec:
    name: str
    entity_type: E
    regex: re.Pattern
    score: float
    group: int = 0
    context: tuple[str, ...] = ()
    context_boost: float = 0.3
    context_window: int = 40
    validator: Optional[Callable[[str], bool]] = None


def _digits(s: str) -> int:
    return sum(c.isdigit() for c in s)


def _phone_ok(s: str) -> bool:
    d = _digits(s)
    if not 7 <= d <= 15:
        return False
    return not re.fullmatch(r"\d{4}[-/.]\d{1,2}[-/.]\d{1,2}|\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}", s.strip())


def _mixed_alnum(s: str) -> bool:
    return sum(c.isalpha() for c in s) >= 2 and _digits(s) >= 2


def _password_like(s: str) -> bool:
    if "@" in s or "://" in s or s.lower().startswith("www."):
        return False
    classes = sum([any(c.islower() for c in s), any(c.isupper() for c in s),
                   any(c.isdigit() for c in s), any(not c.isalnum() for c in s)])
    return classes >= 3 and not re.fullmatch(r"[0-9A-Fa-f-]+", s)


def _has_digit(s: str) -> bool:
    return _digits(s) >= 1


C = re.compile
I = re.IGNORECASE

# USPS / faker street suffixes. The un-numbered street pattern uses only SAFE ones, because
# "Data Point" or "Key Union" would otherwise read as addresses.
STREET_ALL = ("Alley|Annex|Arcade|Avenue|Ave|Bayou|Beach|Bend|Bluffs?|Bottom|Boulevard|Blvd|Branch|Bridge|Brooks?|Burgs?|"
              "Bypass|Camp|Canyon|Cape|Causeway|Centers?|Centre|Circles?|Cir|Cliffs?|Club|Common|Corners?|Course|Courts?|Ct|"
              "Coves?|Creek|Crescent|Crest|Crossing|Crossroad|Curve|Dale|Dam|Divide|Drives?|Dr|Estates?|Expressway|Extensions?|"
              "Falls?|Ferry|Fields?|Flats?|Fords?|Forest|Forges?|Forks?|Fort|Freeway|Gardens?|Gateway|Glens?|Greens?|Groves?|"
              "Harbors?|Harbour|Haven|Heights|Highway|Hwy|Hills?|Hollow|Inlet|Islands?|Isle|Junctions?|Keys?|Knolls?|Lakes?|"
              "Landing|Lane|Ln|Lights?|Loaf|Locks?|Lodge|Loop|Mall|Manors?|Meadows?|Mews|Mills?|Mission|Motorway|Mount|"
              "Mountains?|Neck|Orchard|Oval|Overpass|Parks?|Parkways?|Pkwy|Pass|Passage|Path|Pike|Pines?|Place|Pl|Plains?|"
              "Plaza|Points?|Ports?|Prairie|Radial|Ramp|Ranch|Rapids?|Rest|Ridges?|River|Roads?|Rd|Route|Row|Rue|Run|"
              "Shoals?|Shores?|Skyway|Springs?|Spurs?|Squares?|Sq|Station|Stravenue|Stream|Streets?|St|Summit|Terrace|Ter|"
              "Throughway|Trace|Track|Trafficway|Trail|Tunnel|Turnpike|Underpass|Unions?|Valleys?|Viaduct|Views?|Villages?|"
              "Ville|Vista|Walks?|Wall|Ways?|Wells?|Nagar|Marg|Main|Cross|Layout|Colony|Sector")
STREET_SAFE = ("Street|Avenue|Road|Lane|Drive|Boulevard|Viaduct|Camp|Court|Crescent|Terrace|Plaza|Parkway|Highway|"
               "Expressway|Turnpike|Stravenue|Trafficway|Throughway|Underpass|Overpass|Mews|Alley|Junction|Crossing|"
               "Heights|Gardens|Estates|Meadows|Ridge|Hollow|Harbor|Grove|Glen|Manor|Square|Circle|Loop|Pike|Shoals|"
               "Rapids|Springs|Ferry|Bypass|Causeway|Ranch|Inlet|Knoll|Branch|Nagar|Marg|Layout|Colony")

ROLE_TAIL = r"(?:Specialist|Coordinator|Engineer|Manager|Officer|Designer|Consultant|Analyst|Strategist|Producer|Developer|Architect|Agent|Assistant|Associate|Director|Executive|Facilitator|Liaison|Orchestrator|Planner|Representative|Supervisor|Technician|Administrator|Scientist|Nurse|Professor|Lecturer|Warden|Accountant|Auditor|Lawyer|Surgeon|Physician|Pharmacist|Researcher|Teacher|Editor|Writer|Programmer)"
DESCRIPTOR = r"(?:Senior|Junior|Lead|Principal|Chief|Head|Staff|Associate|Assistant|Deputy|Regional|Global|District|Central|Corporate|Dynamic|Direct|Forward|Future|Human|International|Internal|Investor|Legacy|National|Product|Customer|Senior|Clinical|Medical|Research|Data|Software|Security|Marketing|Sales|Finance|Financial|Legal|Operations|Program|Project|Quality|Network|Systems|Cloud)"

SPECS: list[PatternSpec] = [
    # --- device / vehicle
    PatternSpec("imei_dashed", E.DEVICE_IDENTIFIER, C(r"\b\d{2}-\d{6}-\d{6}-\d\b"), 0.85),
    PatternSpec("imei_ctx", E.DEVICE_IDENTIFIER, C(r"\bIMEI\b[:#\s]*(\d[\d -]{13,17}\d)", I), 0.9, group=1),
    PatternSpec("vin", E.DEVICE_IDENTIFIER, C(r"\b[A-HJ-NPR-Z0-9]{17}\b"), 0.6, validator=_mixed_alnum,
                context=("vin", "vehicle", "chassis")),
    PatternSpec("plate_ctx", E.DEVICE_IDENTIFIER,
                C(r"\b(?:licen[cs]e plate|number plate|plate(?: number)?|vehicle registration|VRM|registration number)\b[:#\s]*([A-Z0-9][A-Z0-9 -]{3,9}[A-Z0-9])", I), 0.85, group=1, validator=_has_digit),
    PatternSpec("uk_vrm", E.DEVICE_IDENTIFIER, C(r"\b[A-Z]{2}\d{2}\s?[A-Z]{3}\b"), 0.55, context=("vehicle", "car", "plate", "registration")),
    PatternSpec("device_id_ctx", E.DEVICE_IDENTIFIER,
                C(r"\b(?:device|serial)\s*(?:id|identifier|number|no\.?|#)\b[:#\s]*([A-Za-z0-9][A-Za-z0-9:-]{5,40})", I), 0.8, group=1, validator=_has_digit),

    # --- phone numbers Presidio's region list misses. Bare digit groups need context.
    PatternSpec("phone_intl", E.PHONE_NUMBER, C(r"(?<![\w+])\+\d{1,3}[\s.-]?(?:\(\d{1,4}\)[\s.-]?)?\d{1,5}(?:[\s.-]\d{1,5}){1,4}(?!\w)"), 0.7,
                validator=_phone_ok),
    PatternSpec("phone_paren", E.PHONE_NUMBER, C(r"(?<!\w)\(\d{2,5}\)[\s.-]?\d{2,5}(?:[\s.-]\d{2,5}){0,3}(?!\w)"), 0.65, validator=_phone_ok),
    PatternSpec("phone_generic", E.PHONE_NUMBER, C(r"(?<![\w+/.-])\d{2,5}(?:[\s.-]\d{2,5}){1,4}(?![\w/])"), 0.3,
                validator=_phone_ok, context=("phone", "tel", "call", "mobile", "cell", "contact", "fax", "whatsapp", "reach", "dial"),
                context_boost=0.35),

    # --- financial
    PatternSpec("ethereum", E.FINANCIAL_ACCOUNT, C(r"\b0x[a-fA-F0-9]{40}\b"), 0.9),
    PatternSpec("btc_legacy", E.FINANCIAL_ACCOUNT, C(r"\b[13][a-zA-Z0-9]{25,40}\b"), 0.55, validator=_mixed_alnum,
                context=("bitcoin", "btc", "wallet", "crypto")),
    PatternSpec("btc_bech32", E.FINANCIAL_ACCOUNT, C(r"\bbc1[a-z0-9]{25,59}\b"), 0.85),
    PatternSpec("litecoin", E.FINANCIAL_ACCOUNT, C(r"\b[LM][a-zA-Z0-9]{26,40}\b"), 0.55, validator=_mixed_alnum,
                context=("litecoin", "ltc", "wallet", "crypto")),
    PatternSpec("iban_loose", E.FINANCIAL_ACCOUNT, C(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,4})?\b"), 0.6,
                validator=lambda s: _digits(s) >= 8, context=("iban", "account", "bank", "transfer")),
    PatternSpec("card_ctx", E.FINANCIAL_ACCOUNT, C(r"\b(?:\d{4}[ -]?){3}\d{1,7}\b"), 0.45,
                context=("card", "visa", "mastercard", "amex", "credit", "debit"), validator=lambda s: 13 <= _digits(s) <= 19),
    PatternSpec("masked_card", E.FINANCIAL_ACCOUNT, C(r"(?<![\w*])(?:[\d*Xx]{4}[ -]?){3}[\d*Xx]{1,4}(?![\w*])"), 0.6,
                validator=lambda s: ("*" in s or "x" in s.lower()) and _digits(s) >= 4),
    PatternSpec("cvv", E.FINANCIAL_ACCOUNT, C(r"\b(?:CVV2?|CVC|CSC|card security code|security code)\b[:\s#]*(\d{3,4})\b", I), 0.9, group=1),
    PatternSpec("account_ctx", E.FINANCIAL_ACCOUNT,
                C(r"\b(?:account|acct|a/c|routing|ABA|sort code)\b(?:\s*(?:number|no\.?|#|code))?[:\s#]*([A-Z]{0,4}\d[\d -]{4,24}\d)", I), 0.8, group=1),
    PatternSpec("swift_ctx", E.FINANCIAL_ACCOUNT, C(r"\b(?:SWIFT|BIC)\b(?:\s*(?:code|number))?[:\s#]*([A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?)\b", I), 0.9, group=1),
    PatternSpec("bic_shape", E.FINANCIAL_ACCOUNT, C(r"\b[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"), 0.3,
                validator=lambda s: _digits(s) >= 1, context=("bic", "swift", "bank")),

    # --- government
    PatternSpec("ssn_shape", E.GOVERNMENT_ID, C(r"\b\d{3}-\d{2}-\d{4}\b"), 0.65, context=("ssn", "social security", "tax")),
    PatternSpec("ssn_ctx", E.GOVERNMENT_ID,
                C(r"\b(?:SSN|social security(?: number)?|AHV(?: number)?|NI number|national insurance(?: number)?|SIN)\b[:\s#]*(\d[\d. -]{7,16}\d)", I),
                0.9, group=1),
    PatternSpec("aadhaar", E.GOVERNMENT_ID, C(r"\b[2-9]\d{3}\s?\d{4}\s?\d{4}\b"), 0.4, context=("aadhaar", "aadhar", "uid", "uidai")),
    PatternSpec("pan_india", E.GOVERNMENT_ID, C(r"\b[A-Z]{5}\d{4}[A-Z]\b"), 0.65, context=("pan",)),
    PatternSpec("gov_id_ctx", E.GOVERNMENT_ID,
                C(r"\b(?:passport|driver'?s? licen[cs]e|driving licen[cs]e|licen[cs]e number|national id|tax id|TIN|ITIN|voter id|NHS number|certificate number)\b(?:\s*(?:number|no\.?|#))?[:\s#]*([A-Z0-9][A-Z0-9 -]{4,18}[A-Z0-9])", I),
                0.85, group=1, validator=_has_digit),

    # --- record identifiers (customer / employee / medical record numbers)
    PatternSpec("record_ctx", E.RECORD_IDENTIFIER,
                C(r"\b(?:MRN|medical record(?: number)?|patient (?:id|number)|customer (?:id|number|no\.?)|client (?:id|number)|employee (?:id|number|no\.?)|emp(?:loyee)? ?id|staff id|member (?:id|number)|beneficiary (?:id|number)|health plan (?:id|number)|policy (?:number|no\.?)|case (?:id|number|no\.?)|ticket (?:id|number|no\.?)|reference (?:id|number|no\.?)|user id|record (?:id|number))\b[:\s#-]*([A-Z0-9][A-Z0-9_-]{3,24})", I),
                0.85, group=1, validator=_has_digit),
    PatternSpec("id_ctx", E.RECORD_IDENTIFIER, C(r"\b(?:ID|identifier)\b(?:\s*(?:number|no\.?|#))?[:\s#]*([A-Z0-9][A-Z0-9.-]{5,24})"), 0.7,
                group=1, validator=lambda s: _digits(s) >= 4),
    PatternSpec("prefixed_id", E.RECORD_IDENTIFIER, C(r"\b[A-Z]{2,5}[-_]\d{4,12}\b"), 0.55,
                context=("id", "number", "record", "employee", "customer", "patient", "member")),

    # --- credentials
    PatternSpec("password_ctx", E.CREDENTIAL,
                C(r"\b(?:password|passwd|pwd|passcode|passphrase|api[ _-]?key|secret key|access token|auth token|token)\b(?:\s+(?:is|was|=))?\s*[:=]?\s*[\"'`]?([^\s\"'`,;]{6,128})", I),
                0.9, group=1),
    PatternSpec("pin_ctx", E.CREDENTIAL, C(r"\bPIN\b(?:\s*(?:code|number|no\.?))?[:\s#]*(\d{4,8})\b"), 0.85, group=1),
    PatternSpec("password_shape", E.CREDENTIAL, C(r"(?<![\w@./:-])[A-Za-z0-9!@#$%^&*_+=?~-]{8,32}(?!\.?[\w@/:-])"), 0.42,
                validator=_password_like, context=("password", "credentials", "login", "key", "token")),

    # --- online identifiers
    PatternSpec("user_agent", E.ONLINE_IDENTIFIER,
                C(r"\b(?:Mozilla|Opera|Chrome|Safari|AppleWebKit)/\d[\w.]*(?:\s+(?:\([^)]{1,200}\)|[\w.]+/[\w.]+))*"), 0.9),
    PatternSpec("username_ctx", E.ONLINE_IDENTIFIER,
                C(r"\b(?:user ?name|login(?: id)?|handle|screen name|account name)\b[:\s]*@?([A-Za-z0-9][A-Za-z0-9_.-]{2,30})", I), 0.85, group=1),
    PatternSpec("at_handle", E.ONLINE_IDENTIFIER, C(r"(?<![\w@.])@[A-Za-z0-9_]{3,30}\b"), 0.6),
    PatternSpec("ipv6_loose", E.ONLINE_IDENTIFIER, C(r"\b(?:[0-9a-fA-F]{1,4}:){4,7}[0-9a-fA-F]{1,4}\b"), 0.7),

    # --- location-ish
    PatternSpec("gps", E.GPS_COORDINATE, C(r"\[?\(?\s*-?\d{1,3}\.\d{3,}\s*,\s*-?\d{1,3}\.\d{3,}\s*\)?\]?"), 0.85),
    PatternSpec("zip_us", E.POSTAL_CODE, C(r"\b\d{5}(?:-\d{4})?\b"), 0.35,
                context=("zip", "postal", "postcode", "post code", "pin code", "address", "street", "avenue", "suite", "apt")),
    PatternSpec("pin_in", E.POSTAL_CODE, C(r"\b[1-9]\d{5}\b"), 0.25, context=("pin code", "pincode", "postal", "zip")),
    PatternSpec("postcode_uk", E.POSTAL_CODE, C(r"\b[A-Z]{1,2}\d[A-Z\d]?\s\d[A-Z]{2}\b"), 0.6),
    PatternSpec("street", E.STREET_ADDRESS,
                C(rf"\b\d{{1,6}}[A-Za-z]?,?\s*(?:[A-Z][A-Za-z'.-]+\s+){{1,4}}(?:{STREET_ALL})\b\.?(?:,?\s*(?:Apt|Apartment|Suite|Ste|Unit|Floor|Flat|Room)\.?\s*#?\s*\w+)?"),
                0.8),
    PatternSpec("street_unnumbered", E.STREET_ADDRESS, C(rf"\b(?:[A-Z][a-z]+\s){{1,2}}(?:{STREET_SAFE})\b"), 0.55),
    PatternSpec("building_ctx", E.STREET_ADDRESS, C(r"\b(?:building|bldg|house|plot|door)\.?\s*(?:number|no\.?|#)?\s*(\d{1,6}[A-Z]?)\b", I),
                0.75, group=1),
    PatternSpec("secondary_addr", E.STREET_ADDRESS, C(r"\b(?:Apt|Apartment|Suite|Ste|Unit|Flat)\.?\s*#?\s*\d+[A-Za-z]?\b"), 0.7),

    # --- dates and ages
    PatternSpec("date_numeric", E.DATE, C(r"\b(?:\d{1,2}[/.-]\d{1,2}[/.-](?:19|20)?\d{2}|(?:19|20)\d{2}[/.-]\d{1,2}[/.-]\d{1,2})\b"), 0.7),
    PatternSpec("age_ctx", E.AGE, C(r"\b(?:aged?|age:)\s*(\d{1,3})\b", I), 0.85, group=1, validator=lambda s: 0 <= int(s) < 120),
    PatternSpec("age_years_old", E.AGE, C(r"\b(\d{1,3})(?:[ -]years?[ -]old|[ -]year-old|[ -]yrs?[ -]old|\s+years? of age)\b", I), 0.85, group=1,
                validator=lambda s: 0 <= int(s) < 120),
    PatternSpec("age_bare_years", E.AGE, C(r"\b(\d{1,3})\s+years?\b(?!\s+(?:ago|later|before|after|of experience|experience|in))", I), 0.5, group=1,
                validator=lambda s: 0 <= int(s) < 120, context=("age", "aged", "old", "patient", "born")),

    # --- people
    PatternSpec("greeting_name", E.PERSON,
                C(r"\b(?:Dear|Hi|Hello|Hey|Greetings|Attn:?|Attention:?)\s+([A-Z][\w'*-]+(?:[ _][A-Z][\w'-]+)?)"), 0.7, group=1),
    PatternSpec("name_cue", E.PERSON,
                C(r"\b(?:[Mm]y name is|[Ii] am|[Ii]'m|[Tt]his is|[Nn]ame:|[Rr]egards,|[Ss]incerely,|[Ss]igned:?|[Ff]rom:|[Pp]atient:|[Cc]lient:)\s+([A-Z][a-z'-]+(?:\s[A-Z][a-z'-]+){0,2})"),
                0.9, group=1),
    PatternSpec("name_digits_username", E.ONLINE_IDENTIFIER, C(r"\b[A-Z][a-z]{2,}\d{2,4}\b"), 0.5),

    # --- people descriptors
    PatternSpec("gender", E.DEMOGRAPHIC,
                C(r"\b(?:male|female|non-?binary|transgender|trans (?:wo)?man|trans (?:fe)?male|cis(?:gender)? (?:wo)?man|cis(?:gender)? (?:fe)?male|genderqueer|genderfluid|agender|bigender|intersex|two-spirit)\b", I), 0.6),
    PatternSpec("gender_person", E.DEMOGRAPHIC, C(r"(?<!\w)(?:Trans|Cis|Two\*?|T\*|Agender|Bigender|Demi)\s+(?:person|man|woman|boy|girl)\b"), 0.6),
    PatternSpec("height", E.DEMOGRAPHIC, C(r"\b\d{2,3}\s?(?:cm|centimet(?:er|re)s)\b|\b\d'\s?\d{1,2}(?:\"|'')"), 0.6),
    PatternSpec("eyes", E.DEMOGRAPHIC, C(r"\b(?:blue|brown|green|hazel|grey|gray|amber)(?=\s+eyes?\b)", I), 0.6),
    PatternSpec("blood_type", E.MEDICAL_CONDITION, C(r"\b(?:A|B|AB|O)[+-](?=\W|$)"), 0.45, context=("blood",)),
    PatternSpec("medical_terms", E.MEDICAL_CONDITION,
                C(r"\b(?:diabetes|type [12] diabetes|hypertension|asthma|cancer|leukaemia|leukemia|HIV|AIDS|hepatitis [ABC]?|depression|anxiety disorder|bipolar disorder|schizophrenia|epilepsy|tuberculosis|dementia|alzheimer'?s|parkinson'?s|COVID-19|pregnan(?:t|cy)|chemotherapy|dialysis|cardiac arrest|stroke|migraine|arthritis|autism|ADHD)\b", I), 0.7),

    # --- occupation
    PatternSpec("job_title_shape", E.OCCUPATION, C(rf"\b(?:{DESCRIPTOR}\s+){{0,2}}(?:[A-Z][a-z]+\s+)?{ROLE_TAIL}\b"), 0.55,
                validator=lambda s: len(s.split()) >= 2),
    # lowercase titles after an explicit cue: "works as a data science manager", "the role is events
    # coordinator", "Vikram Rao, customer support engineer"
    PatternSpec("job_title_cued", E.OCCUPATION,
                C(r"(?:\b(?:works as|working as|employed as|joined as|hired as|serves as|appointed|is|was|as|post is|role is|"
                  r"position is|title is|job title:?|role:?|designation:?)\s+(?:an?\s+|the\s+)?|,\s+)"
                  r"((?:[a-z][a-z-]+\s){0,3}(?:engineer|manager|coordinator|architect|scientist|analyst|consultant|specialist|"
                  r"officer|director|administrator|developer|designer|technician|supervisor|executive|assistant|associate|"
                  r"nurse|radiologist|pharmacist|physician|surgeon|therapist|professor|lecturer|teacher|accountant|auditor|"
                  r"lawyer|advocate|librarian|researcher|warden|planner|strategist|editor|writer|programmer|clerk|"
                  r"receptionist|paramedic|dentist|lead|head|dean|registrar|counsellor|counselor))\b"),
                0.6, group=1),
    PatternSpec("role_noun", E.OCCUPATION, C(rf"(?<=[a-z,] ){ROLE_TAIL}\b"), 0.45),
    PatternSpec("dept_area", E.OCCUPATION, C(r"\b([A-Z][a-z]{3,})\s+(?:department|team|division|dept\.?|unit|practice)\b"), 0.5, group=1,
                validator=lambda s: s.lower() not in {"hello", "dear", "team", "your", "this", "that", "whole", "entire", "every", "each", "same", "sales"}),
]


# Structured data (SQL, JSON, logs): the field name says what the value is.
_FIELD_TYPES = [
    (r"(?:first|last|full|middle|given|family|sur|user_?full|customer|patient|employee|contact)_?name|^name$|^surname$", E.PERSON),
    (r"e_?mail", E.EMAIL_ADDRESS), (r"phone|mobile|tel(?:ephone)?|fax|cell", E.PHONE_NUMBER),
    (r"street|address(?:_?line)?|addr", E.STREET_ADDRESS), (r"city|town|state|county|country|region", E.LOCATION),
    (r"zip|postal|post_?code|pin_?code", E.POSTAL_CODE), (r"ssn|social_?security|national_?id|passport|tax_?id|licen[cs]e", E.GOVERNMENT_ID),
    (r"dob|birth", E.DATE_OF_BIRTH), (r"user_?name|login|handle|screen_?name", E.ONLINE_IDENTIFIER),
    (r"pass(?:word|wd)?|pwd|secret|token|api_?key", E.CREDENTIAL), (r"ip_?(?:addr|address)?$|mac_?addr", E.ONLINE_IDENTIFIER),
    (r"iban|account_?(?:no|num|number)|card_?(?:no|num|number)|routing|swift|bic", E.FINANCIAL_ACCOUNT),
    (r"customer_?id|employee_?id|patient_?id|member_?id|mrn|record_?id", E.RECORD_IDENTIFIER),
    (r"^age$", E.AGE), (r"gender|^sex$", E.DEMOGRAPHIC), (r"company|employer|organi[sz]ation", E.ORGANIZATION),
    (r"job_?title|occupation|profession|designation", E.OCCUPATION), (r"lat(?:itude)?$|lon(?:gitude)?$|coord", E.GPS_COORDINATE),
]
_FIELD_VALUE = re.compile(r"""[`'"]?([A-Za-z][A-Za-z0-9_]{1,40})[`'"]?\s*(?:=|:|<>|!=|=>)\s*(['"])([^'"\n]{1,120})\2""")


def _field_type(key: str) -> E | None:
    k = re.sub(r"(?<=[a-z])(?=[A-Z])", "_", key).lower()        # camelCase -> snake_case
    for pat, et in _FIELD_TYPES:
        if re.search(pat, k):
            return et
    return None


def find_field_values(text: str) -> list[Candidate]:
    out = []
    for m in _FIELD_VALUE.finditer(text):
        et = _field_type(m.group(1))
        v = m.group(3)
        if et is None or not v.strip() or v.strip().lower() in ("null", "none", "n/a", "true", "false"):
            continue
        out.append(Candidate(m.start(3), m.end(3), et, 0.75, DetectionSource.PATTERN, f"field:{m.group(1)}"))
    return out


def find_patterns(text: str) -> list[Candidate]:
    out: list[Candidate] = []
    low = text.lower()
    for spec in SPECS:
        for m in spec.regex.finditer(text):
            start, end = m.span(spec.group)
            if start < 0 or end <= start:
                continue
            value = text[start:end]
            # trim trailing punctuation the regex may have eaten
            while end > start and text[end - 1] in ".,;:)]}\"'" and spec.entity_type not in (E.GPS_COORDINATE,):
                end -= 1
            if end <= start:
                continue
            value = text[start:end]
            if spec.validator and not spec.validator(value):
                continue
            score = spec.score
            if spec.context:
                window = low[max(0, m.start() - spec.context_window): m.start()]
                if any(w in window for w in spec.context):
                    score = min(0.99, score + spec.context_boost)
            out.append(Candidate(start, end, spec.entity_type, score, DetectionSource.PATTERN, spec.name))
    return out + find_field_values(text)
