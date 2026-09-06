// Intégration locale/test du catalogue Mega Dental dans le comparateur existant.
// Le fichier mega_catalog_visible_test.json doit être présent à la racine du site.
// Si le fichier n'est pas disponible, le comparateur d'origine reste inchangé.
(function(){
  'use strict';

  const DATA_URL = 'mega_catalog_visible_test.json';
  const PAGE_SIZE = 60;
  let megaProducts = [];
  let filteredProducts = [];
  let currentMegaCategory = 'all';
  let visibleCount = PAGE_SIZE;
  let currentSearch = '';
  let currentSort = 'default';

  function esc(value){
    return String(value == null ? '' : value)
      .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
      .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
  }

  function formatPrice(value){
    const n = Number(value);
    return Number.isFinite(n) ? n.toFixed(2).replace('.', ',') + ' €' : '';
  }

  function normalizeProduct(raw){
    return {
      id: raw.id || raw.merchant_reference || raw.source_url || raw.name,
      name: raw.name || '',
      brand: raw.brand || '',
      category: raw.dental_category || raw.category || 'Autres',
      price: raw.price_eur != null ? Number(raw.price_eur) : null,
      image: raw.image_url || '',
      availability: raw.availability || '',
      merchantReference: raw.merchant_reference || '',
      manufacturerReference: raw.manufacturer_reference || '',
      ean: raw.ean || '',
      url: raw.source_url || raw.url || '',
      raw
    };
  }

  function qualityVisible(p){
    return !!(p.name && Number.isFinite(p.price) && p.image && p.availability);
  }

  function productHaystack(p){
    return [p.name,p.brand,p.category,p.merchantReference,p.manufacturerReference,p.ean]
      .filter(Boolean).join(' ').toLowerCase();
  }

  function buildNav(){
    const nav = document.querySelector('.subnav');
    if(!nav) return;
    const counts = new Map();
    megaProducts.forEach(p => counts.set(p.category, (counts.get(p.category)||0)+1));
    const cats = [...counts.keys()].sort((a,b)=>a.localeCompare(b,'fr'));
    nav.innerHTML = '<div class="subnav-label">Catégories</div>';

    const addButton = (label,key) => {
      const btn = document.createElement('button');
      btn.textContent = label;
      btn.dataset.cat = key;
      if(key === currentMegaCategory) btn.classList.add('active');
      btn.addEventListener('click',()=>{
        currentMegaCategory = key;
        currentSearch = '';
        const input = document.getElementById('site-search');
        if(input) input.value = '';
        visibleCount = PAGE_SIZE;
        buildNav();
        applyFilters();
      });
      nav.appendChild(btn);
    };

    addButton('Toutes les catégories', 'all');
    cats.forEach(c => addButton(c, c));
  }

  function optionalMeta(p){
    const parts = [];
    if(p.brand) parts.push('<span><strong>Marque :</strong> '+esc(p.brand)+'</span>');
    if(p.manufacturerReference) parts.push('<span><strong>Réf. fabricant :</strong> '+esc(p.manufacturerReference)+'</span>');
    if(p.ean) parts.push('<span><strong>EAN :</strong> '+esc(p.ean)+'</span>');
    return parts.length ? '<div class="prod-sub" style="display:flex;flex-wrap:wrap;gap:6px 12px;margin-top:7px;">'+parts.join('')+'</div>' : '';
  }

  function renderMegaCard(p){
    const cartPayload = {
      id: String(p.id),
      name: p.name,
      tag: p.category,
      sub: p.brand || '',
      prices: [{merchant:'Mega Dental', value:p.price}]
    };
    const image = esc(p.image);
    const target = p.url ? `onclick="window.open('${esc(p.url)}','_blank','noopener')"` : '';
    const availability = p.availability ? `<div class="prod-sub" style="margin-top:6px;">${esc(p.availability)}</div>` : '';

    return `
      <div class="card">
        <div class="card-top">
          <div class="prod-photo" style="height:180px;padding:10px;overflow:hidden;">
            <img src="${image}" alt="${esc(p.name)}" loading="lazy" style="max-width:100%;max-height:100%;object-fit:contain;" onerror="this.style.display='none'">
          </div>
          <span class="tag">${esc(p.category)}</span>
          <p class="prod-name">${esc(p.name)}</p>
          ${optionalMeta(p)}
          ${availability}
        </div>

        <div class="price-hero">
          <div class="from">Prix chez Mega Dental</div>
          <div class="amount">${formatPrice(p.price)}</div>
        </div>

        <div>
          <div class="rank-label">Offre disponible</div>
          <div class="rank-list">
            <div class="rank-row best">
              <span class="num">1</span>
              <span class="merch">Mega Dental</span>
              <span class="rank-bar-track"><span class="rank-bar-fill" style="width:100%;"></span></span>
              <span class="price">${formatPrice(p.price)}</span>
            </div>
          </div>
        </div>

        <div class="cta-row">
          <button class="cta-btn" ${target}>Voir chez Mega Dental &nbsp;→</button>
          <div class="cta-note">Ouvre la fiche du marchand</div>
        </div>
        <button class="add-cart-btn" onclick='addProductToCart(this)' data-product='${JSON.stringify(cartPayload).replace(/'/g,"&#39;")}'>
          + Ajouter au panier
        </button>
      </div>`;
  }

  function drawMega(){
    const grid = document.getElementById('grid');
    if(!grid) return;
    const shown = filteredProducts.slice(0, visibleCount);
    if(!shown.length){
      grid.innerHTML = '<div class="empty-state">Aucune référence trouvée.</div>';
      return;
    }
    grid.innerHTML = shown.map(renderMegaCard).join('');
    if(visibleCount < filteredProducts.length){
      const more = document.createElement('div');
      more.style.gridColumn = '1 / -1';
      more.style.textAlign = 'center';
      more.innerHTML = '<button class="cta-btn" style="display:inline-flex;flex:none;padding:11px 22px;">Afficher 60 de plus</button>';
      more.querySelector('button').addEventListener('click',()=>{ visibleCount += PAGE_SIZE; drawMega(); });
      grid.appendChild(more);
    }
  }

  function applyFilters(){
    let list = megaProducts;
    if(currentMegaCategory !== 'all') list = list.filter(p => p.category === currentMegaCategory);
    if(currentSearch){
      const q = currentSearch.toLowerCase();
      list = list.filter(p => productHaystack(p).includes(q));
    }
    list = [...list];
    if(currentSort === 'price-asc') list.sort((a,b)=>a.price-b.price);
    filteredProducts = list;

    const title = document.getElementById('page-title');
    const sub = document.getElementById('page-sub');
    if(title){
      title.textContent = currentSearch
        ? `Résultats pour « ${currentSearch} »`
        : currentMegaCategory === 'all' ? 'Catalogue dentaire' : currentMegaCategory;
    }
    if(sub){
      sub.textContent = `${filteredProducts.length.toLocaleString('fr-FR')} référence(s) Mega Dental avec prix, image et disponibilité`;
    }
    drawMega();
  }

  function installOverrides(){
    window.handleSearch = function(e){
      if(e.key === 'Escape'){
        e.target.value = '';
        currentSearch = '';
        visibleCount = PAGE_SIZE;
        applyFilters();
        return;
      }
      currentSearch = e.target.value.trim();
      visibleCount = PAGE_SIZE;
      applyFilters();
    };

    window.closeSearchSoon = function(){};
    window.closeSearch = function(){};
    window.sortCards = function(mode){
      currentSort = mode;
      visibleCount = PAGE_SIZE;
      applyFilters();
    };
    window.switchCategory = function(key){
      currentMegaCategory = key || 'all';
      currentSearch = '';
      visibleCount = PAGE_SIZE;
      buildNav();
      applyFilters();
    };

    const panel = document.getElementById('search-results');
    if(panel){ panel.classList.remove('open'); panel.innerHTML = ''; }
    const input = document.getElementById('site-search');
    if(input) input.placeholder = 'Rechercher un produit, une marque, une référence…';

    const sort = document.getElementById('sort');
    if(sort){
      const savings = sort.querySelector('option[value="savings"]');
      if(savings) savings.remove();
      sort.value = 'default';
    }
  }

  async function initMegaCatalog(){
    if(!document.getElementById('grid')) return;
    try{
      const res = await fetch(DATA_URL, {cache:'no-store'});
      if(!res.ok) return;
      const payload = await res.json();
      const rows = Array.isArray(payload) ? payload : (payload.products || []);
      megaProducts = rows.map(normalizeProduct).filter(qualityVisible);
      if(!megaProducts.length) return;
      filteredProducts = megaProducts;
      installOverrides();
      buildNav();
      applyFilters();
    }catch(err){
      console.info('Catalogue Mega non chargé :', err && err.message ? err.message : err);
    }
  }

  initMegaCatalog();
})();
