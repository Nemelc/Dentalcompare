// Gestion du panier — partagée entre toutes les pages du site.
// Stockage dans localStorage pour que le panier survive à la navigation entre pages.
// (Ne fonctionne pas dans l'aperçu de chat, uniquement une fois le site réellement déployé.)

const CART_KEY = 'dentacompare_cart_v1';

function cartSafeGet(){
  try{
    const raw = localStorage.getItem(CART_KEY);
    return raw ? JSON.parse(raw) : [];
  }catch(e){
    return [];
  }
}

function cartSafeSet(items){
  try{
    localStorage.setItem(CART_KEY, JSON.stringify(items));
  }catch(e){
    // Stockage indisponible (ex: aperçu en sandbox) — le panier ne persistera pas, sans planter la page.
  }
}

function getCart(){
  return cartSafeGet();
}

// Ajoute un produit au panier. product = { id, name, tag, sub, prices: [{merchant, value}, ...] }
function addToCart(product){
  const cart = getCart();
  const existing = cart.find(i => i.id === product.id);
  if(existing){
    existing.qty += 1;
  } else {
    cart.push({ ...product, qty: 1 });
  }
  cartSafeSet(cart);
  updateCartBadge();
}

function removeFromCart(id){
  let cart = getCart();
  cart = cart.filter(i => i.id !== id);
  cartSafeSet(cart);
  updateCartBadge();
}

function updateCartQty(id, qty){
  const cart = getCart();
  const item = cart.find(i => i.id === id);
  if(item){
    item.qty = Math.max(1, qty);
    cartSafeSet(cart);
  }
}

function clearCart(){
  cartSafeSet([]);
  updateCartBadge();
}

function cartItemCount(){
  return getCart().reduce((sum, i) => sum + i.qty, 0);
}

// Met à jour le badge numérique sur l'icône panier, sur toutes les pages qui en ont une.
function updateCartBadge(){
  const badge = document.getElementById('cart-badge');
  if(!badge) return;
  const count = cartItemCount();
  badge.textContent = count;
  badge.style.display = count > 0 ? 'flex' : 'none';
}

document.addEventListener('DOMContentLoaded', updateCartBadge);
