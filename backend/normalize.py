import html
import re
import unicodedata
from typing import Optional

BRAND_ALIASES = {
    "3m espe": "solventum",
    "3m oral care": "solventum",
    "3m": "solventum",
    "dentsply": "dentsply sirona",
    "micro mega": "micro-mega",
    "micro-mega": "micro-mega",
}


def clean_text(value: Optional[str]) -> str:
    if not value:
        return ""
    value = html.unescape(str(value)).replace("\xa0", " ")
    return re.sub(r"\s+", " ", value).strip()


def fold(value: Optional[str]) -> str:
    value = clean_text(value).lower()
    value = unicodedata.normalize("NFKD", value)
    value = "".join(c for c in value if not unicodedata.combining(c))
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_reference(value: Optional[str]) -> str:
    """Reference comparison form; punctuation/case are ignored."""
    if not value:
        return ""
    return re.sub(r"[^A-Z0-9]", "", clean_text(value).upper())


def normalize_brand(value: Optional[str]) -> str:
    b = fold(value)
    return BRAND_ALIASES.get(b, b)


def parse_price(text: Optional[str]):
    if not text:
        return None
    # French price styles: 1 234,56 € / 1234.56 EUR
    m = re.search(r"(\d[\d\s\u202f.]*(?:[,.]\d{1,2})?)\s*(?:€|eur)?", clean_text(text), re.I)
    if not m:
        return None
    raw = m.group(1).replace("\u202f", "").replace(" ", "")
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def normalize_stock(text: Optional[str]) -> Optional[str]:
    s = fold(text)
    if not s:
        return None
    if "en stock" in s or "disponible" in s:
        return "in_stock"
    if "sur commande" in s:
        return "on_order"
    if "reappro" in s or "rupture" in s:
        return "backorder"
    if "arrete" in s or "indisponible" in s or "discontinued" in s:
        return "discontinued"
    return "unknown"


def extract_packaging(name: str) -> str:
    """Extract useful quantity/packaging hints without pretending to understand every dental SKU."""
    s = fold(name)
    patterns = [
        r"\bboite de \d+\b",
        r"\bcoffret de \d+\b",
        r"\b(\d+)\s*(?:x|×)\s*\d+(?:[.,]\d+)?\s*(?:g|mg|ml|mm)\b",
        r"\b\d+\s*(?:capsules?|seringues?|blocs?|instruments?|fraises?|limes?|aiguilles?|gants?)\b",
        r"\b\d+(?:[.,]\d+)?\s*(?:g|mg|ml)\b",
    ]
    found = []
    for p in patterns:
        found.extend(re.findall(p, s, re.I))
    return " ".join(x if isinstance(x, str) else " ".join(x) for x in found).strip()


def extract_variant_tokens(name: str) -> set[str]:
    """Tokens whose mismatch should strongly discourage a merge."""
    s = clean_text(name).upper()
    tokens = set()
    patterns = [
        r"\bA[1-4](?:\.5)?\b", r"\bB[1-4]\b", r"\bC[1-4]\b", r"\bD[2-4]\b",
        r"\bN°?\s*\d{1,3}\b", r"\bISO\s*\d{2,3}\b",
        r"\b\d+(?:[.,]\d+)?\s*MM\b", r"\b\d+(?:[.,]\d+)?\s*ML\b",
        r"\b\d+(?:[.,]\d+)?\s*G\b", r"\b\d+\s*(?:PCS|PIECES|CAPSULES?|SERINGUES?|BLOCS?)\b",
        r"\b(?:XS|S|M|L|XL)\b",
    ]
    for p in patterns:
        tokens.update(re.findall(p, s))
    return {re.sub(r"\s+", "", t) for t in tokens}
