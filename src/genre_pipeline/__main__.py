"""CLI entry for the genre pipeline.

Usage:
  python3 -m src.genre_pipeline --new-genre <id> [--name X --genre Y --era Z --tone W]
  python3 -m src.genre_pipeline --fill-genre <id>
  python3 -m src.genre_pipeline --audit-genre <id>
  python3 -m src.genre_pipeline --extract-from-novel <id> --sources a.txt,b.txt [--with-trial]
  python3 -m src.genre_pipeline --extract-from-novel <id> --sources a.txt --dry-run
  python3 -m src.genre_pipeline --extract-only <id>
  python3 -m src.genre_pipeline --merge-only <id>
  python3 -m src.genre_pipeline --draft-only <id>
  python3 -m src.genre_pipeline --validate-only <id> [--with-trial]
"""
from __future__ import annotations

import argparse
import json
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description="Novelforge Genre Pipeline")
    grp = parser.add_mutually_exclusive_group(required=True)
    grp.add_argument("--new-genre", metavar="ID", help="scaffold a new genre pack")
    grp.add_argument("--fill-genre", metavar="ID", help="fill missing files in an existing genre")
    grp.add_argument("--audit-genre", metavar="ID", help="run Validator stages 1+2 on an existing genre")
    grp.add_argument("--extract-from-novel", metavar="ID", help="extract a genre from source novels")
    # Intent Router — rerun individual phases without full pipeline
    grp.add_argument("--extract-only", metavar="ID", help="(Intent: extract) rerun extract phase only")
    grp.add_argument("--merge-only", metavar="ID", help="(Intent: merge) rerun merge phase only")
    grp.add_argument("--draft-only", metavar="ID", help="(Intent: draft) rerun draft phase only")
    grp.add_argument("--validate-only", metavar="ID", help="(Intent: validate) rerun validate phase only")

    parser.add_argument("--sources", default="", help="comma-separated novel file paths")
    parser.add_argument("--name", default="", help="display name (for --new-genre)")
    parser.add_argument("--genre", default="", help="genre label (for --new-genre)")
    parser.add_argument("--era", default="", help="era label (for --new-genre)")
    parser.add_argument("--tone", default="", help="tone label (for --new-genre)")
    parser.add_argument("--with-trial", action="store_true", help="also run 3-chapter trial book validation")
    parser.add_argument("--dry-run", action="store_true", help="don't call any LLM; just exercise the plumbing")

    args = parser.parse_args()

    from src.genre_pipeline import pipeline

    if args.new_genre:
        out = pipeline.new_genre(
            args.new_genre,
            display_name=args.name,
            genre=args.genre,
            era=args.era,
            tone=args.tone,
        )
    elif args.fill_genre:
        out = pipeline.fill_genre(args.fill_genre)
    elif args.audit_genre:
        out = pipeline.audit_genre(args.audit_genre)
    elif args.extract_from_novel:
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        if not sources:
            print("error: --extract-from-novel requires --sources a.txt,b.txt", file=sys.stderr)
            return 2
        out = pipeline.extract_from_novel(
            args.extract_from_novel,
            sources=sources,
            with_trial=args.with_trial,
            dry_run=args.dry_run,
        )
    elif args.extract_only:
        out = pipeline.run_phase(args.extract_only, phase="extract")
    elif args.merge_only:
        out = pipeline.run_phase(args.merge_only, phase="merge")
    elif args.draft_only:
        out = pipeline.run_phase(args.draft_only, phase="draft")
    elif args.validate_only:
        out = pipeline.run_phase(args.validate_only, phase="validate", with_trial=args.with_trial)
    else:
        parser.print_help()
        return 2

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
