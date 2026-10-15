#!/usr/bin/env python3
"""
Project Zomboid Player Blob Patcher - Revive a Dead Player

Parses the binary `data` blob from the `networkPlayers` SQLite table,
patches health/infection/death fields, and writes it back.

Usage:
    python revive_player.py db <path_to_db> <username_or_steamid> [options]
    python revive_player.py blob <input.bin> [options]
    python revive_player.py verify db <path_to_db> <username_or_steamid> [options]
    python revive_player.py verify blob <input.bin> [options]
    python revive_player.py edit db <path_to_db> <username_or_steamid> [options]
    python revive_player.py edit blob <input.bin> [options]

Options:
    -v, --verbose     Show detailed parse logging with hex offsets
    --dry-run         Parse and show what would change, but don't write anything
"""

import argparse

from pz_blob.log import set_verbose
from pz_blob.commands import (
    cmd_patch_db,
    cmd_patch_blob,
    cmd_verify,
    cmd_edit_db,
    cmd_edit_blob,
    cmd_items_db,
)


def main():
    parser = argparse.ArgumentParser(
        description="Project Zomboid Player Revival Tool - Patch dead player data blobs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Verify player state (read-only diagnostic):
    python revive_player.py verify db players.db "PlayerName" -v

  Dry-run (see what would change, no writes):
    python revive_player.py db players.db "PlayerName" --dry-run -v

  Revive player in database:
    python revive_player.py db players.db "PlayerName"

  Patch standalone blob:
    python revive_player.py blob player_data.bin --out patched.bin

  Edit player via JSON:
    python revive_player.py edit db players.db "PlayerName"
"""
    )
    # Shared flags added to every subparser so -v works anywhere
    verbose_args = ["-v", "--verbose"]
    verbose_kwargs = {"action": "store_true", "help": "Show detailed parse logging with hex offsets"}
    dry_run_kwargs = {"action": "store_true", "help": "Show what would change without writing"}

    parser.add_argument(*verbose_args, **verbose_kwargs)

    subparsers = parser.add_subparsers(dest="mode", help="Operation mode")

    # --- db mode ---
    db_parser = subparsers.add_parser("db", help="Patch player directly in SQLite database")
    db_parser.add_argument("db_path", help="Path to the networkPlayers SQLite database")
    db_parser.add_argument("identifier", help="Player username or Steam ID")
    db_parser.add_argument("--player-index", type=int, default=0,
                           help="Player index (0-3, default 0)")
    db_parser.add_argument("--world-version", type=int, default=0,
                           help="Override world version (0 = use value from DB)")
    db_parser.add_argument("--dry-run", **dry_run_kwargs)
    db_parser.add_argument(*verbose_args, **verbose_kwargs)

    # --- blob mode ---
    blob_parser = subparsers.add_parser("blob", help="Patch a standalone binary blob file")
    blob_parser.add_argument("input", help="Path to input blob file")
    blob_parser.add_argument("--out", help="Path to output patched blob file")
    blob_parser.add_argument("--world-version", type=int, default=241,
                             help="World version number (default 241 for B42)")
    blob_parser.add_argument("--dry-run", **dry_run_kwargs)
    blob_parser.add_argument(*verbose_args, **verbose_kwargs)

    # --- verify mode ---
    verify_sub = subparsers.add_parser("verify", help="Read-only diagnostic report")
    verify_sub.add_argument(*verbose_args, **verbose_kwargs)
    verify_source = verify_sub.add_subparsers(dest="source")

    verify_db = verify_source.add_parser("db", help="Verify from database")
    verify_db.add_argument("db_path", help="Path to the networkPlayers SQLite database")
    verify_db.add_argument("identifier", help="Player username or Steam ID")
    verify_db.add_argument("--player-index", type=int, default=0)
    verify_db.add_argument("--world-version", type=int, default=0)
    verify_db.add_argument(*verbose_args, **verbose_kwargs)

    verify_blob = verify_source.add_parser("blob", help="Verify from blob file")
    verify_blob.add_argument("input", help="Path to blob file")
    verify_blob.add_argument("--world-version", type=int, default=241)
    verify_blob.add_argument(*verbose_args, **verbose_kwargs)

    # --- edit mode ---
    edit_sub = subparsers.add_parser("edit", help="Export to JSON, edit, and import back")
    edit_sub.add_argument(*verbose_args, **verbose_kwargs)
    edit_source = edit_sub.add_subparsers(dest="edit_source")

    edit_db = edit_source.add_parser("db", help="Edit player in database via JSON")
    edit_db.add_argument("db_path", help="Path to the networkPlayers SQLite database")
    edit_db.add_argument("identifier", help="Player username or Steam ID")
    edit_db.add_argument("--player-index", type=int, default=0)
    edit_db.add_argument("--world-version", type=int, default=0)
    edit_db.add_argument("--json-path", help="Custom path for the JSON file")
    edit_db.add_argument(*verbose_args, **verbose_kwargs)

    edit_blob = edit_source.add_parser("blob", help="Edit blob file via JSON")
    edit_blob.add_argument("input", help="Path to input blob file")
    edit_blob.add_argument("--out", help="Path to output patched blob file")
    edit_blob.add_argument("--world-version", type=int, default=241)
    edit_blob.add_argument("--json-path", help="Custom path for the JSON file")
    edit_blob.add_argument(*verbose_args, **verbose_kwargs)

    # --- items mode ---
    items_sub = subparsers.add_parser("items", help="Extract and display player inventory items")
    items_sub.add_argument(*verbose_args, **verbose_kwargs)
    items_source = items_sub.add_subparsers(dest="items_source")

    items_db = items_source.add_parser("db", help="Extract items from database")
    items_db.add_argument("db_path", help="Path to the networkPlayers SQLite database")
    items_db.add_argument("identifier", help="Player username or Steam ID")
    items_db.add_argument("--player-index", type=int, default=0)
    items_db.add_argument("--world-version", type=int, default=0)
    items_db.add_argument("--save-dir", help="Path to save directory (for WorldDictionaryReadable.lua)")
    items_db.add_argument("--out", help="Output file path (.json for JSON, anything else for text)")
    items_db.add_argument(*verbose_args, **verbose_kwargs)

    args = parser.parse_args()

    set_verbose(args.verbose)

    if args.mode == "db":
        cmd_patch_db(args)
    elif args.mode == "blob":
        cmd_patch_blob(args)
    elif args.mode == "verify":
        if args.source == "db":
            cmd_verify(args)
        elif args.source == "blob":
            cmd_verify(args)
        else:
            verify_sub.print_help()
    elif args.mode == "edit":
        if hasattr(args, 'edit_source') and args.edit_source == "db":
            cmd_edit_db(args)
        elif hasattr(args, 'edit_source') and args.edit_source == "blob":
            cmd_edit_blob(args)
        else:
            edit_sub.print_help()
    elif args.mode == "items":
        if hasattr(args, 'items_source') and args.items_source == "db":
            cmd_items_db(args)
        else:
            items_sub.print_help()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
