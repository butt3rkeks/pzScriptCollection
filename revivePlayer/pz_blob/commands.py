"""CLI command handlers for all modes: db, blob, verify, edit, items."""

import json
import shutil
from pathlib import Path

from .blob import parse_blob, parse_blob_full
from .patch import apply_patches, print_verify_report
from .json_edit import export_sections_to_json, apply_json_edits, BlobJSONEncoder
from .db import load_player_from_db


# ---------------------------------------------------------------------------
# Revive commands
# ---------------------------------------------------------------------------

def cmd_patch_db(args):
    """Patch a player directly in the SQLite database."""
    conn, row = load_player_from_db(args.db_path, args.identifier, args.player_index)
    sql_id, x, y, z, data, wv, is_dead, name = row
    world_version = args.world_version if args.world_version else wv

    print(f"[OK] Found player: name={name}, pos=({x:.0f}, {y:.0f}, {z:.0f}), "
          f"isDead={is_dead}, worldVersion={world_version}, blob={len(data)} bytes")

    if not is_dead and not args.dry_run:
        print("WARNING: Player is not marked as dead in the database.")
        resp = input("Continue anyway? (y/n): ").strip().lower()
        if resp != 'y':
            conn.close()
            return

    print("\nParsing blob...")
    reader, patch = parse_blob(data, world_version)

    if args.dry_run:
        print("\n[DRY-RUN] Showing what would change (no writes):")
        apply_patches(reader, patch, dry_run=True)
        conn.close()
        return

    print("\nApplying patches...")
    changes = apply_patches(reader, patch, dry_run=False)

    if changes == 0:
        print("\nNo changes needed - player data already looks alive.")
        conn.close()
        return

    # Backup
    db_path = Path(args.db_path)
    backup_path = db_path.with_suffix('.db.bak')
    if not backup_path.exists():
        shutil.copy2(db_path, backup_path)
        print(f"[OK] Backup created: {backup_path}")
    else:
        print(f"[OK] Backup already exists: {backup_path}")

    # Write
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE networkPlayers SET isDead=0, data=? WHERE id=?",
        (bytes(reader.data), sql_id)
    )
    conn.commit()
    conn.close()
    print(f"\n[OK] Player '{name}' revived! isDead set to 0 and blob patched.")
    print("\nIMPORTANT: The player's inventory is on their corpse in the world.")
    print("           They will respawn alive but with an empty inventory.")
    print("           You may want to use admin commands to return their items.")


def cmd_patch_blob(args):
    """Patch a standalone blob file."""
    input_path = Path(args.input)
    if not input_path.exists():
        import sys
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    data = input_path.read_bytes()
    print(f"[OK] Read {len(data)} bytes from {input_path}")

    print("\nParsing blob...")
    reader, patch = parse_blob(data, args.world_version)

    if args.dry_run:
        print("\n[DRY-RUN] Showing what would change (no writes):")
        apply_patches(reader, patch, dry_run=True)
        return

    print("\nApplying patches...")
    changes = apply_patches(reader, patch, dry_run=False)

    if args.out:
        out = Path(args.out)
    else:
        out = input_path.with_suffix('.patched.bin')
    out.write_bytes(bytes(reader.data))
    print(f"\n[OK] Patched blob written to {out}")


# ---------------------------------------------------------------------------
# Verify command
# ---------------------------------------------------------------------------

def cmd_verify(args):
    """Parse and display diagnostic report without modifying anything."""
    if hasattr(args, 'db_path') and args.db_path:
        conn, row = load_player_from_db(args.db_path, args.identifier, args.player_index)
        sql_id, x, y, z, data, wv, is_dead, name = row
        world_version = args.world_version if args.world_version else wv

        print(f"[OK] Found player: name={name}, pos=({x:.0f}, {y:.0f}, {z:.0f}), "
              f"isDead={is_dead}, worldVersion={world_version}, blob={len(data)} bytes")

        print("\nParsing blob...")
        reader, patch = parse_blob(data, world_version)
        print_verify_report(patch)
        conn.close()
    else:
        input_path = Path(args.input)
        if not input_path.exists():
            import sys
            print(f"ERROR: File not found: {input_path}")
            sys.exit(1)
        data = input_path.read_bytes()
        print(f"[OK] Read {len(data)} bytes from {input_path}")
        print("\nParsing blob...")
        reader, patch = parse_blob(data, args.world_version)
        print_verify_report(patch)


# ---------------------------------------------------------------------------
# Edit commands
# ---------------------------------------------------------------------------

_EDIT_WARNING = (
    "Only edit fields with '\"editable\": true'. "
    "Fields prefixed with _ are read-only. "
    "DO NOT change guard bytes (_bandaged, _infectedWound, _hasSplint) — "
    "toggling them corrupts all subsequent offsets. "
    "String values and array lengths cannot be changed in-place."
)


def cmd_edit_db(args):
    """Edit a player's data via JSON export/import on a SQLite database."""
    conn, row = load_player_from_db(args.db_path, args.identifier, args.player_index)
    sql_id, x, y, z, data, wv, is_dead, name = row
    world_version = args.world_version if args.world_version else wv

    print(f"[OK] Found player: name={name}, pos=({x:.0f}, {y:.0f}, {z:.0f}), "
          f"isDead={is_dead}, worldVersion={world_version}, blob={len(data)} bytes")

    print("\nParsing blob...")
    reader, sections = parse_blob_full(data, world_version)

    # Export to JSON
    meta = {
        "tool": "revive_player.py",
        "mode": "edit",
        "blob_size": len(data),
        "world_version": world_version,
        "player_name": name,
        "is_dead": is_dead,
        "_WARNING": _EDIT_WARNING,
    }
    json_data = export_sections_to_json(sections, meta)

    json_path = Path(args.db_path).parent / f"{name.replace(' ', '_')}_edit.json"
    if args.json_path:
        json_path = Path(args.json_path)

    json_path.write_text(json.dumps(json_data, indent=2, cls=BlobJSONEncoder), encoding='utf-8')
    print(f"\n[OK] Exported to: {json_path}")
    print(f"     Edit the file, save it, then press Enter to apply changes...")
    input()

    # Read back edited JSON
    edited = json.loads(json_path.read_text(encoding='utf-8'))

    # Re-parse original blob for fresh offsets
    reader2, sections2 = parse_blob_full(data, world_version)

    print("\nApplying edits...")
    changes = apply_json_edits(reader2, sections2, edited)

    if changes == 0:
        print("\nNo changes detected.")
        conn.close()
        return

    # Backup
    db_path = Path(args.db_path)
    backup_path = db_path.with_suffix('.db.bak')
    if not backup_path.exists():
        shutil.copy2(db_path, backup_path)
        print(f"[OK] Backup created: {backup_path}")
    else:
        print(f"[OK] Backup already exists: {backup_path}")

    # Write
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE networkPlayers SET data=? WHERE id=?",
        (bytes(reader2.data), sql_id)
    )
    conn.commit()
    conn.close()
    print(f"\n[OK] Player '{name}' updated! {changes} field(s) changed.")


def cmd_edit_blob(args):
    """Edit a standalone blob file via JSON export/import."""
    input_path = Path(args.input)
    if not input_path.exists():
        import sys
        print(f"ERROR: File not found: {input_path}")
        sys.exit(1)

    data = input_path.read_bytes()
    print(f"[OK] Read {len(data)} bytes from {input_path}")

    print("\nParsing blob...")
    reader, sections = parse_blob_full(data, args.world_version)

    # Export to JSON
    meta = {
        "tool": "revive_player.py",
        "mode": "edit",
        "blob_size": len(data),
        "world_version": args.world_version,
        "_WARNING": _EDIT_WARNING,
    }
    json_data = export_sections_to_json(sections, meta)

    json_path = input_path.with_suffix('.edit.json')
    if args.json_path:
        json_path = Path(args.json_path)

    json_path.write_text(json.dumps(json_data, indent=2, cls=BlobJSONEncoder), encoding='utf-8')
    print(f"\n[OK] Exported to: {json_path}")
    print(f"     Edit the file, save it, then press Enter to apply changes...")
    input()

    # Read back edited JSON
    edited = json.loads(json_path.read_text(encoding='utf-8'))

    # Re-parse original blob for fresh offsets
    reader2, sections2 = parse_blob_full(data, args.world_version)

    print("\nApplying edits...")
    changes = apply_json_edits(reader2, sections2, edited)

    if changes == 0:
        print("\nNo changes detected.")
        return

    if args.out:
        out = Path(args.out)
    else:
        out = input_path.with_suffix('.patched.bin')
    out.write_bytes(bytes(reader2.data))
    print(f"\n[OK] Patched blob written to {out} ({changes} field(s) changed)")


# ---------------------------------------------------------------------------
# Items command
# ---------------------------------------------------------------------------

def cmd_items_db(args):
    """Extract and display player inventory items from the database."""
    from .reader import BlobReader
    from .items import (
        load_registry, extract_inventory, print_item_tree,
        inventory_to_json, format_item_tree_text,
    )

    conn, row = load_player_from_db(args.db_path, args.identifier, args.player_index)
    sql_id, x, y, z, data, wv, is_dead, name = row
    world_version = args.world_version if args.world_version else wv

    print(f"[OK] Found player: name={name}, pos=({x:.0f}, {y:.0f}, {z:.0f}), "
          f"isDead={is_dead}, worldVersion={world_version}, blob={len(data)} bytes")

    # Load registry
    save_dir = Path(args.save_dir) if args.save_dir else Path(args.db_path).parent
    registry = load_registry(save_dir)
    print(f"[OK] Loaded {len(registry)} item types from registry")

    # Full parse to get inventory byte range, worn items, and hand items
    print("\nParsing blob...")
    reader, sections = parse_blob_full(data, world_version)

    # Get worn items and hand item indices
    player = sections.get("Player", {})
    worn_items = player.get("_wornItems", {}).get("value", [])
    hand_left = player.get("leftHandIdx", {}).get("value", -1)
    hand_right = player.get("rightHandIdx", {}).get("value", -1)

    # Re-parse inventory section with item extraction
    inv_range = sections["Inventory"].get("_byte_range")
    if not inv_range:
        print("ERROR: Could not locate inventory section in blob")
        conn.close()
        return

    inv_start, inv_end = inv_range
    inv_reader = BlobReader(data[inv_start:inv_end])
    inventory = extract_inventory(inv_reader, world_version, registry)

    # Output
    print_item_tree(inventory, worn_items, hand_left, hand_right)

    if args.out:
        out_path = Path(args.out)
        if out_path.suffix.lower() == ".json":
            json_data = inventory_to_json(inventory, worn_items, hand_left,
                                          hand_right, name)
            out_path.write_text(
                json.dumps(json_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        else:
            text = format_item_tree_text(inventory, worn_items, hand_left,
                                         hand_right, name)
            out_path.write_text(text, encoding="utf-8")
        print(f"\n[OK] Output written to {out_path}")

    conn.close()
