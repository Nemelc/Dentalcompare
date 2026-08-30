/*
  Minimal bridge for the existing DentalCompare frontend.
  1) Load data/dentalcompare-data.js before your current comparator script.
  2) Keep your rendering/CSS unchanged.
  3) Replace only the hard-coded product source with window.DENTALCOMPARE_PRODUCTS.
*/

function dentalCompareProductsByCategory(products) {
  const groups = {};
  for (const p of products || []) {
    const key = p.category || "non-classe";
    if (!groups[key]) {
      groups[key] = { title: key === "non-classe" ? "Non classé" : key, sub: "", products: [] };
    }
    // Preserve the shape already used by the current cards/cart.
    groups[key].products.push({
      id: p.id,
      name: p.name,
      sub: p.brand || "",
      tag: p.category || "Produit",
      image_url: p.image_url,
      manufacturer_reference: p.manufacturer_reference,
      prices: (p.prices || []).filter(x => typeof x.value === "number")
    });
  }
  return groups;
}

// Intended replacement for the current hard-coded `const CATEGORIES = {...}`:
// const CATEGORIES = dentalCompareProductsByCategory(window.DENTALCOMPARE_PRODUCTS || []);
