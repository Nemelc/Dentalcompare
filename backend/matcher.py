from dataclasses import dataclass
from rapidfuzz.fuzz import token_set_ratio
from .models import MerchantProduct
from .normalize import (
    fold, normalize_brand, normalize_reference, extract_variant_tokens, extract_packaging
)


@dataclass
class MatchResult:
    score: float
    decision: str  # auto_match | review | no_match
    reasons: list[str]


def _similarity(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    return token_set_ratio(fold(a), fold(b)) / 100.0


def compare(a: MerchantProduct, b: MerchantProduct, auto_threshold=.93, review_threshold=.80) -> MatchResult:
    reasons = []

    # Hard identifiers first.
    ean_a, ean_b = normalize_reference(a.ean), normalize_reference(b.ean)
    if ean_a and ean_b:
        if ean_a == ean_b:
            return MatchResult(1.0, "auto_match", ["EAN/GTIN identique"])
        return MatchResult(0.0, "no_match", ["EAN/GTIN contradictoire"])

    ref_a = normalize_reference(a.manufacturer_reference)
    ref_b = normalize_reference(b.manufacturer_reference)
    brand_a, brand_b = normalize_brand(a.brand), normalize_brand(b.brand)

    if ref_a and ref_b:
        if ref_a == ref_b:
            if brand_a and brand_b and brand_a != brand_b:
                return MatchResult(0.82, "review", ["Référence fabricant identique mais marque différente"])
            return MatchResult(0.99, "auto_match", ["Référence fabricant identique"])
        # Two explicit manufacturer refs that differ should almost never be merged.
        return MatchResult(0.08, "no_match", ["Références fabricant différentes"])

    variants_a = extract_variant_tokens(" ".join(filter(None, [a.name, a.variant, a.packaging])))
    variants_b = extract_variant_tokens(" ".join(filter(None, [b.name, b.variant, b.packaging])))
    if variants_a and variants_b and variants_a.isdisjoint(variants_b):
        # Avoid A1/A2, 20/50 units, 21/25 mm etc. false merges.
        reasons.append("Variantes/conditionnements incompatibles")
        variant_penalty = 0.28
    else:
        variant_penalty = 0.0

    name_score = _similarity(a.name, b.name)
    brand_score = 1.0 if brand_a and brand_b and brand_a == brand_b else (0.0 if brand_a and brand_b else 0.5)
    pack_a = a.packaging or extract_packaging(a.name)
    pack_b = b.packaging or extract_packaging(b.name)
    packaging_score = _similarity(pack_a, pack_b) if pack_a and pack_b else 0.5

    score = 0.58 * name_score + 0.24 * brand_score + 0.18 * packaging_score - variant_penalty
    score = max(0.0, min(1.0, score))
    reasons += [
        f"Nom {name_score:.2f}", f"Marque {brand_score:.2f}", f"Conditionnement {packaging_score:.2f}"
    ]

    if score >= auto_threshold:
        decision = "auto_match"
    elif score >= review_threshold:
        decision = "review"
    else:
        decision = "no_match"
    return MatchResult(score, decision, reasons)
