import argparse, sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

def main():
    ap = argparse.ArgumentParser(description="DentalCompare - snapshot catalogue")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import-gacd", help="Importer des captures navigateur GACD")
    p.add_argument("path")

    p = sub.add_parser("import-mega", help="Importer des captures navigateur Mega Dental")
    p.add_argument("path")

    sub.add_parser("export", help="Exporter le dernier état")
    args = ap.parse_args()

    if args.cmd == "import-gacd":
        from adapters.gacd_import import main as gacd_main
        sys.argv = ["gacd_import.py", args.path]
        gacd_main()
    elif args.cmd == "import-mega":
        from adapters.mega_import import main as mega_main
        sys.argv = ["mega_import.py", args.path]
        mega_main()
    elif args.cmd == "export":
        from export_frontend import main as export_main
        export_main()

if __name__ == "__main__":
    main()
