# Catalogue Mega Dental — stratégie sitemap d'abord

Objectif : construire un catalogue Mega Dental exploitable dans DentalCompare sans modifier le frontend et sans contourner les protections du site.

Le test Playwright a montré que Mega Dental peut répondre en HTTP 403 après quelques fiches. Le collecteur local reste disponible pour de petits contrôles manuels, mais il ne doit pas être utilisé pour tenter de contourner une protection.

## Méthode recommandée : catalogue depuis les sitemaps locaux

Les deux sitemaps Mega Dental permettent de constituer la base du catalogue sans ouvrir les fiches produit. Le script `build_mega_catalog_from_sitemaps.py` :

- lit un ou plusieurs fichiers sitemap XML déjà sauvegardés localement ;
- conserve par défaut les URL de priorité `1.0` ;
- déduplique les URL ;
- crée un nom lisible à partir du slug de l'URL ;
- extrait la référence Mega quand elle est présente à la fin de l'URL, par exemple `900-8818` ;
- fusionne automatiquement les données plus riches déjà présentes dans `data/mega_bulk_checkpoint.jsonl` ;
- n'ouvre aucune fiche produit.

Depuis `backend/snapshot` :

```bash
python build_mega_catalog_from_sitemaps.py sitemap_14-1-1.xml sitemap_14-1-2.xml
```

Le résultat est écrit dans :

```text
data/mega_catalog_sitemap.json
```

Ce JSON est directement compatible avec l'import Mega du snapshot :

```bash
python snapshot.py import-mega data/mega_catalog_sitemap.json
```

Le frontend n'est pas modifié par cette opération.

## Enrichissement progressif

La base sitemap fournit surtout nom dérivé, URL et souvent référence Mega. Les champs qui ne sont pas présents dans le sitemap restent à `null` : prix, disponibilité, marque, référence fabricant, EAN, catégorie, image, etc.

Les données déjà collectées légitimement par le checkpoint local remplacent automatiquement les valeurs dérivées lors de la construction du catalogue. D'autres sources publiques ou flux autorisés pourront être fusionnés ultérieurement sans reconstruire toute l'architecture.

## Collecteur Playwright — usage secondaire seulement

Le script `bulk_mega_local.py` conserve son checkpoint et s'arrête sur une vraie protection HTTP 403/429 ou une page de challenge. Il ne tente aucun contournement. Pour un petit contrôle :

```bash
python bulk_mega_local.py data/mega_urls.txt --limit 20
```

Résultats :

- `data/mega_bulk_checkpoint.jsonl`
- `data/mega_catalog_latest.json`

La relance reprend automatiquement les produits déjà enregistrés, mais cette méthode n'est plus la stratégie recommandée pour parcourir les 12 517 URL.
