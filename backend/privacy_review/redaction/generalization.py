"""Generalisation: keep the useful part of a value, drop the identifying precision.

Every function returns None when it cannot produce something *strictly less specific* than
the input, and the caller falls back to masking. A "generalisation" equal to the original
would be a silent leak.
"""

from __future__ import annotations

import re
from typing import Optional

from privacy_review.schemas.entities import EntityType

_MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december"]
_MONTH_RE = re.compile(r"\b(" + "|".join(m[:3] for m in _MONTHS) + r")[a-z]*\.?", re.I)
_YEAR_RE = re.compile(r"\b(1[89]\d{2}|20\d{2})\b")


def age_band(value: str, width: int) -> Optional[str]:
    m = re.search(r"\d{1,3}", value)
    if not m:
        return None
    age = int(m.group())
    lo = (age // width) * width
    band = f"{lo}-{lo + width - 1}"
    return value[:m.start()] + band + value[m.end():]          # "34 years old" -> "30-39 years old"


def _year(value: str) -> Optional[int]:
    m = _YEAR_RE.search(value)
    if m:
        return int(m.group())
    m = re.search(r"\b\d{1,2}[/.-]\d{1,2}[/.-](\d{2})\b", value)        # 12/03/89
    if m:
        yy = int(m.group(1))
        return 1900 + yy if yy > 30 else 2000 + yy
    return None


def _month(value: str) -> Optional[int]:
    m = _MONTH_RE.search(value)
    if m:
        return [x[:3] for x in _MONTHS].index(m.group(1).lower()[:3]) + 1
    m = re.search(r"\b(\d{4})[/.-](\d{1,2})[/.-]\d{1,2}\b", value)                 # 2024-03-12
    if m:
        return int(m.group(2))
    m = re.search(r"\b(\d{1,2})[/.-](\d{1,2})[/.-]\d{2,4}\b", value)               # ambiguous d/m vs m/d
    if m:
        a, b = int(m.group(1)), int(m.group(2))
        return b if a > 12 else a if b > 12 else None
    return None


def decade(value: str) -> Optional[str]:
    y = _year(value)
    return f"the {y // 10 * 10}s" if y else None


def month_year(value: str) -> Optional[str]:
    y, mth = _year(value), _month(value)
    if not y:
        return None
    return f"{_MONTHS[mth - 1].capitalize()} {y}" if mth else str(y)


def year(value: str) -> Optional[str]:
    y = _year(value)
    return str(y) if y else None


def prefix(value: str, keep: int) -> Optional[str]:
    chars = [c for c in value if c.isalnum()]
    if len(chars) <= keep:
        return None
    return "".join(chars[:keep]) + "x" * (len(chars) - keep)


def round_coords(value: str, decimals: int) -> Optional[str]:
    nums = re.findall(r"-?\d+\.\d+", value)
    if len(nums) != 2:
        return None
    a, b = (round(float(n), decimals) for n in nums)
    fmt = f"{{:.{decimals}f}}" if decimals else "{:.0f}"
    return f"{fmt.format(a)}, {fmt.format(b)}"


def region_map(value: str, level: str, regions: dict[str, list[str]]) -> Optional[str]:
    hit = regions.get(value.strip().lower())
    if not hit:
        return None
    return hit[0] if level == "region" else hit[1]


def keyword_family(value: str, families: list[dict], key: str) -> Optional[str]:
    low = value.lower()
    for fam in families:
        if any(re.search(rf"\b{re.escape(k)}\b", low) for k in fam["keywords"]):
            return fam[key]
    return None


def generalize(value: str, entity_type: EntityType, level: int, rules: dict, reference: dict) -> Optional[str]:
    """Apply the KB generalisation rule for (type, level). None = cannot generalise safely."""
    spec = (rules.get(entity_type) or {}).get(str(level)) or (rules.get(entity_type) or {}).get("1")
    if not spec:
        return None
    m = spec["method"]
    if m == "age_band":
        out = age_band(value, spec["width"])
    elif m == "decade":
        out = decade(value)
    elif m == "month_year":
        out = month_year(value)
        if out and out.strip().lower() == value.strip().lower():      # already month-year
            out = year(value)
    elif m == "year":
        out = year(value)
    elif m == "prefix":
        out = prefix(value, spec["keep"])
    elif m == "round":
        out = round_coords(value, spec["decimals"])
    elif m == "region_map":
        out = region_map(value, spec["level"], reference.get("location_regions", {}))
    elif m == "occupation_family":
        out = keyword_family(value, reference.get("occupation_families", []), "family")
    elif m == "organization_sector":
        out = keyword_family(value, reference.get("organization_sectors", []), "sector")
    elif m == "constant":
        out = spec["value"]
    else:                                   # "mask" or unknown method
        out = None
    if out is None or out.strip().lower() == value.strip().lower() or value.strip().lower() in out.lower():
        return None
    return out
