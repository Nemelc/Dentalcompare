from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "data" / "dentalcompare.sqlite3"
EXPORT_PATH = BASE_DIR / "data" / "dentalcompare-data.js"

REQUEST_TIMEOUT = 25
REQUEST_DELAY_SECONDS = 1.2
USER_AGENT = (
    "DentalCompareCatalogBot/0.1 (+catalog comparison; contact: admin@dentalcompare.invalid)"
)

# Conservative thresholds: false merges are much worse than missed merges.
AUTO_MATCH_THRESHOLD = 0.93
REVIEW_MATCH_THRESHOLD = 0.80
