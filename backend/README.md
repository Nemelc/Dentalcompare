# DentalCompare backend v0.1

Première base de collecte/matching pour GACD + Mega Dental, conçue pour **ne pas modifier le design du site existant**.

## Ce que fait cette version

- un scraper séparé par marchand (`scrapers/gacd.py`, `scrapers/mega_dental.py`)
- respect de `robots.txt` avant crawl automatique
- temporisation entre requêtes
- collecte des SKU/variantes quand les données sont présentes dans la page
- conservation de la catégorie source du marchand
- SQLite avec produits canoniques, produits marchands, offres et historique de prix
- matching fort via EAN/GTIN ou référence fabricant
- matching prudent par marque + nom + conditionnement quand la référence fabricant manque
- mise en file `match_review` pour les rapprochements ambigus
- export JS conservant la forme `prices: [{ merchant, value, ... }]` déjà utilisée par le frontend

## Installation

```bash
python -m venv .venv
# Windows
.venv\\Scripts\\activate
# macOS/Linux
# source .venv/bin/activate
pip install -r requirements.txt
```

## Test limité avant un crawl complet

```bash
python run.py scrape --merchant gacd --limit 10
python run.py scrape --merchant mega --limit 10
python run.py export
```

Le fichier généré est :

`data/dentalcompare-data.js`

## Intégration sans refaire la mise en page

Dans `dental-comparator.html`, charger le fichier généré avant le script qui crée les cartes :

```html
<script src="data/dentalcompare-data.js"></script>
<script src="frontend-integration.js"></script>
```

Puis remplacer uniquement la source hard-codée :

```js
const CATEGORIES = { ...énorme catalogue manuel... };
```

par :

```js
const CATEGORIES = dentalCompareProductsByCategory(
  window.DENTALCOMPARE_PRODUCTS || []
);
```

Le CSS, les cartes, la navigation et la mise en page restent inchangés.

## Matching

Ordre de décision :

1. EAN/GTIN identique -> match automatique.
2. Référence fabricant normalisée identique -> match automatique.
3. Deux références fabricant explicites mais différentes -> **pas de fusion**.
4. Sans identifiant fort : score sur nom, marque, conditionnement et variantes.
5. Score intermédiaire -> `match_review`, jamais fusionné silencieusement.

C'est volontairement conservateur : un faux doublon A1/A2 ou 20/50 unités est plus grave que deux fiches temporairement séparées.

## Important avant production

Les sélecteurs HTML des marchands peuvent changer. Commencer par `--limit 10`, inspecter les lignes collectées, puis élargir. Le système ne tente pas de contourner CAPTCHA, connexion ou protection anti-bot. Si un marchand fournit une API/CSV/XML officiel, il faut privilégier ce flux.

Le User-Agent dans `config.py` contient actuellement une adresse de contact factice (`admin@dentalcompare.invalid`) : remplace-la par une adresse de contact réelle avant tout crawl de production.
