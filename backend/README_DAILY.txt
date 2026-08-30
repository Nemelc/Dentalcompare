DentalCompare — socle de mise à jour quotidienne

Fichiers :
- database_v2.py : base SQLite + historique des prix/disponibilités.
- import_seed.py : importe le catalogue CSV sans dupliquer les produits.
- export_gacd_current.py : génère un JSON courant pour le frontend/backend.
- daily-data.yml : workflow GitHub Actions quotidien à 04:15 UTC.

Important :
Ce socle automatise la persistance, l'historique et l'export.
Il NE contourne pas les restrictions de GACD et ne prétend pas actualiser
le prix à partir d'une source qui n'est pas encore disponible automatiquement.
Quand une source publique/autorisee est ajoutée, elle appellera simplement
upsert_product(..., source="nom_source") et l'historique fonctionnera sans
modifier l'architecture.
