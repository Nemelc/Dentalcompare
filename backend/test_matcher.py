from core.models import MerchantProduct
from core.matcher import compare


def P(**kw):
    base = dict(merchant="x", url="https://x", name="Produit")
    base.update(kw)
    return MerchantProduct(**base)


def test_same_manufacturer_reference():
    a = P(name="Filtek One Bulk Fill A2", brand="3M", manufacturer_reference="4867-A2")
    b = P(name="Filtek One capsules teinte A2", brand="Solventum", manufacturer_reference="4867A2")
    assert compare(a,b).decision == "auto_match"


def test_different_explicit_refs_do_not_merge():
    a = P(name="Filtek One A1", manufacturer_reference="4867A1")
    b = P(name="Filtek One A2", manufacturer_reference="4867A2")
    assert compare(a,b).decision == "no_match"


def test_variant_mismatch_penalty():
    a = P(name="Composite Universal A1 20 capsules", brand="X")
    b = P(name="Composite Universal A2 20 capsules", brand="X")
    assert compare(a,b).decision != "auto_match"
