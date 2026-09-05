# Collecte locale en masse — Mega Dental

Objectif : traiter automatiquement une liste de fiches produit Mega Dental depuis l'ordinateur local, sans modifier le frontend DentalCompare.

Le collecteur n'essaie pas de contourner Cloudflare ou un CAPTCHA. Si une protection est détectée (403, 429, page "Just a moment", CAPTCHA, etc.), il s'arrête et conserve le checkpoint.

## 1. Préparer Python

Depuis le dossier `backend/snapshot` :

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

## 2. Obtenir la liste des URL produit

Le collecteur prend un fichier texte contenant une URL Mega Dental par ligne.

Si un sitemap XML ou une page sitemap/HTML est accessible normalement dans votre navigateur, sauvegardez-la sur le PC puis lancez :

```bash
python extract_mega_urls.py "CHEMIN_DU_FICHIER_SAUVE" --output data/mega_urls.txt
```

Le script extrait les URL Mega Dental terminant en `.html` et écarte les chemins de compte, panier, recherche, médias et sitemap.

## 3. Faire un petit test

Toujours depuis `backend/snapshot` :

```bash
python bulk_mega_local.py data/mega_urls.txt --limit 20
```

Une fenêtre Chromium s'ouvre et les fiches sont traitées automatiquement.

Les résultats intermédiaires sont écrits au fur et à mesure dans :

- `data/mega_bulk_checkpoint.jsonl`
- `data/mega_catalog_latest.json`

## 4. Lancer le catalogue complet

Quand le test de 20 fiches est propre :

```bash
python bulk_mega_local.py data/mega_urls.txt
```

Par défaut, le script attend 2,5 secondes entre les pages.

Pour ralentir davantage :

```bash
python bulk_mega_local.py data/mega_urls.txt --delay 5
```

## 5. Reprise automatique

La même commande peut être relancée après une coupure. Le script lit `data/mega_bulk_checkpoint.jsonl` et ignore les URL déjà enregistrées.

## 6. Import dans le snapshot DentalCompare

Le fichier final `data/mega_catalog_latest.json` peut être importé par :

```bash
python snapshot.py import-mega data/mega_catalog_latest.json
```

Le frontend n'est pas modifié par cette opération.
