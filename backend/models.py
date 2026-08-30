from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MerchantProduct:
    merchant: str
    url: str
    name: str
    price: Optional[float] = None
    currency: str = "EUR"
    merchant_reference: Optional[str] = None
    manufacturer_reference: Optional[str] = None
    ean: Optional[str] = None
    brand: Optional[str] = None
    category: Optional[str] = None
    variant: Optional[str] = None
    packaging: Optional[str] = None
    image_url: Optional[str] = None
    availability: Optional[str] = None
    attributes: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        return f"{self.merchant}:{self.merchant_reference or self.url}"
