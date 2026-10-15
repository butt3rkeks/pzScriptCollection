"""Item extraction from the player data blob.

Parses the inventory section to extract individual items with their
types, conditions, quantities, equipment slots, and container contents.
"""

import re
from pathlib import Path

from .reader import BlobReader
from .kahlua import read_lua_table
from .log import vlog


# ---------------------------------------------------------------------------
# Registry loader
# ---------------------------------------------------------------------------

def load_registry(save_dir) -> dict:
    """Parse WorldDictionaryReadable.lua and return {registryID: fulltype}."""
    save_dir = Path(save_dir)
    lua_path = save_dir / "WorldDictionaryReadable.lua"
    if not lua_path.exists():
        raise FileNotFoundError(
            f"WorldDictionaryReadable.lua not found in {save_dir}\n"
            "Use --save-dir to specify the save directory."
        )

    text = lua_path.read_text(encoding="utf-8", errors="replace")

    registry = {}
    # Match each entry block: { registryID = N, fulltype = "...", ... }
    for m in re.finditer(
        r'registryID\s*=\s*(\d+)\s*,\s*fulltype\s*=\s*"([^"]*)"', text
    ):
        reg_id = int(m.group(1))
        fulltype = m.group(2)
        registry[reg_id] = fulltype

    if not registry:
        raise ValueError(f"No registry entries found in {lua_path}")

    return registry


# ---------------------------------------------------------------------------
# ItemVisual skip (mirrors parsers.parse_item_visual)
# ---------------------------------------------------------------------------

def _skip_item_visual(reader: BlobReader):
    """Skip past an ItemVisual block."""
    flags1 = reader.get_byte()
    reader.read_string()  # fullType
    reader.read_string()  # alternateModelName
    reader.read_string()  # clothingItemName
    if flags1 & 1:
        reader.skip(3)
    if flags1 & 2:
        reader.skip(1)
    if flags1 & 4:
        reader.skip(1)
    if flags1 & 8:
        reader.skip(4)
    if flags1 & 16:
        reader.read_string()
    for _ in range(6):
        arr_len = reader.get_byte()
        if arr_len > 0:
            reader.skip(arr_len)


def _skip_entity_data(reader: BlobReader):
    """Skip entity component data (ByteBlock-wrapped components)."""
    component_count = reader.get_byte()
    for _ in range(component_count):
        block_size = reader.get_int()
        reader.skip(block_size)


def _skip_animal_tracks(reader: BlobReader):
    """Skip AnimalTracks data."""
    reader.read_string()  # animalType
    reader.read_string()  # trackType
    reader.skip(8)  # x (int) + y (int)
    has_dir = reader.get_byte()
    if has_dir == 1:
        reader.skip(4)  # dir ordinal (int)
    reader.skip(8)  # addedTime (long)
    reader.skip(1)  # addedToWorld (byte)


# ---------------------------------------------------------------------------
# Single item parser
# ---------------------------------------------------------------------------

def parse_single_item(data: bytes, world_version: int, registry: dict) -> dict:
    """Parse a single item from its data_len byte block.

    Returns a dict with item info. On parse failure, returns partial info
    with an 'error' key.
    """
    reader = BlobReader(data)
    info = {}

    try:
        # Registry ID → type name
        reg_id = reader.get_short()
        info["registryId"] = reg_id
        info["type"] = registry.get(reg_id, f"Unknown({reg_id})")

        # Save type marker (always -1)
        reader.get_signed_byte()

        # Item ID
        info["id"] = reader.get_int()

        # --- Byte header flags ---
        header = reader.get_byte()

        if header & 0x01:  # currentUses
            info["uses"] = reader.get_int()

        # bit 1 (0x02) reserved/old format — no data in worldVersion >= 220

        if header & 0x04:  # condition
            info["condition"] = reader.get_byte()

        if header & 0x08:  # ItemVisual
            _skip_item_visual(reader)

        if header & 0x10:  # custom color RGBA
            reader.skip(4)

        if header & 0x20:  # itemCapacity
            info["capacity"] = reader.get_float()

        # --- Extended flags (int) ---
        if header & 0x40:
            ext = reader.get_int()

            if ext & 0x01:  # KahluaTable
                read_lua_table(reader)

            # 0x02: activated — no data

            if ext & 0x04:  # haveBeenRepaired
                reader.get_short()

            if ext & 0x08:  # custom name
                info["name"] = reader.read_string()

            if ext & 0x10:  # byteData
                bd_len = reader.get_int()
                reader.skip(bd_len)

            if ext & 0x20:  # extraItems
                count = reader.get_int()
                reader.skip(count * 2)

            # 0x40: isCustomName — no data

            if ext & 0x80:  # customWeight
                info["weight"] = reader.get_float()

            if ext & 0x100:  # keyId
                reader.get_int()

            # 0x200: unused

            if ext & 0x400:  # remoteControl
                reader.skip(8)  # 2 ints

            if ext & 0x800:  # color RGB
                reader.skip(3)

            if ext & 0x1000:  # worker
                reader.read_string()

            if ext & 0x2000:  # wetCooldown
                reader.get_float()

            # 0x4000: isFavorite — no data
            if ext & 0x4000:
                info["favorite"] = True

            if ext & 0x8000:  # stashMap
                reader.read_string()

            # 0x10000: isInfected — no data

            if ext & 0x20000:  # currentAmmoCount
                info["ammo"] = reader.get_int()

            if ext & 0x40000:  # attachedSlot
                info["attachedSlot"] = reader.get_int()

            if ext & 0x80000:  # attachedSlotType
                info["attachedSlotType"] = reader.read_string()

            if ext & 0x100000:  # attachedToModel
                reader.read_string()

            if ext & 0x200000:  # maxCapacity
                info["maxCapacity"] = reader.get_int()

            if ext & 0x400000:  # recordedMediaIndex
                reader.get_short()

            # 0x800000: old worldZRotation (worldVersion < 232 only)
            if world_version < 232 and ext & 0x800000:
                reader.get_int()

            if ext & 0x1000000:  # worldScale
                reader.get_float()

            # 0x2000000: isInitialised — no data

            if ext & 0x4000000:  # entity data
                _skip_entity_data(reader)

            if ext & 0x8000000:  # animalTracks
                _skip_animal_tracks(reader)

            if ext & 0x10000000:  # custom texture
                reader.read_string()

            if ext & 0x20000000:  # modelIndex
                reader.get_int()

            if ext & 0x40000000 and world_version >= 232:  # world rotation
                reader.skip(12)  # 3 floats

        # --- Subclass data: try InventoryContainer ---
        remaining = len(data) - reader.pos
        if remaining >= 12:
            _try_parse_container(reader, data, world_version, registry, info)

    except Exception as e:
        info["error"] = str(e)

    return info


def _try_parse_container(reader, data, world_version, registry, info):
    """Attempt to parse remaining bytes as InventoryContainer subclass data."""
    saved_pos = reader.pos
    try:
        container_id = reader.get_int()
        weight_reduction = reader.get_int()

        # Now try to parse the embedded ItemContainer
        container_items = _parse_item_container(reader, world_version, registry)
        info["containerId"] = container_id
        info["weightReduction"] = weight_reduction
        info["items"] = container_items
    except Exception:
        # Not a container — reset and ignore remaining bytes
        reader.pos = saved_pos


# ---------------------------------------------------------------------------
# Container parser (ItemContainer format)
# ---------------------------------------------------------------------------

def _parse_item_container(reader: BlobReader, world_version: int,
                          registry: dict) -> list:
    """Parse an ItemContainer's contents (containerType + items + footer)."""
    container_type = reader.read_string()
    explored = reader.get_byte()
    vlog(f"        container type={container_type}, explored={explored}")

    item_count = reader.get_short()
    items = []

    for _ in range(item_count):
        identical = reader.get_int()
        data_len = reader.get_int()
        item_bytes = reader.get_bytes(data_len)

        item_info = parse_single_item(item_bytes, world_version, registry)
        item_info["count"] = identical

        if identical > 1:
            reader.skip((identical - 1) * 4)  # extra IDs

        items.append(item_info)

    _has_been_looted = reader.get_byte()
    _capacity = reader.get_int()

    return items


# ---------------------------------------------------------------------------
# Top-level inventory extraction
# ---------------------------------------------------------------------------

def extract_inventory(reader: BlobReader, world_version: int,
                      registry: dict) -> dict:
    """Parse the inventory section fully, extracting all items.

    Uses the same format as parse_inventory_full but decodes items.
    """
    inv_type = reader.read_string()
    explored = reader.get_byte()
    item_count = reader.get_short()

    items = []
    for _ in range(item_count):
        identical = reader.get_int()
        data_len = reader.get_int()
        item_bytes = reader.get_bytes(data_len)

        item_info = parse_single_item(item_bytes, world_version, registry)
        item_info["count"] = identical

        if identical > 1:
            reader.skip((identical - 1) * 4)

        items.append(item_info)

    has_been_looted = reader.get_byte()
    capacity = reader.get_int()

    return {
        "type": inv_type,
        "explored": explored,
        "capacity": capacity,
        "hasBeenLooted": has_been_looted,
        "items": items,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def print_item_tree(inventory: dict, worn_items: list, hand_left: int,
                    hand_right: int):
    """Print the extracted inventory as a readable tree."""
    items = inventory["items"]
    total = sum(it.get("count", 1) for it in items)
    print(f"\nInventory ({total} items, capacity={inventory['capacity']}):")

    # Build worn-item location map: item index → location name
    worn_map = {}
    for w in worn_items:
        worn_map[w["index"]] = w["location"]

    for idx, item in enumerate(items):
        slot = _get_slot_label(item, idx, worn_map, hand_left, hand_right)
        _print_item(item, indent=1, slot=slot)


def _get_slot_label(item, idx, worn_map, hand_left, hand_right):
    """Determine the display slot label for an item."""
    if idx == hand_left:
        return "LeftHand"
    if idx == hand_right:
        return "RightHand"
    if idx in worn_map:
        return worn_map[idx]
    attached = item.get("attachedSlot")
    if attached is not None and attached >= 0:
        slot_type = item.get("attachedSlotType", "")
        return slot_type if slot_type else f"Slot{attached}"
    return None


def _print_item(item, indent=0, slot=None, is_last=False, prefix=""):
    """Print a single item with optional tree connectors."""
    pad = "  " * indent
    parts = []

    # Slot label
    if slot:
        parts.append(f"[{slot}]")

    # Type name or custom name
    name = item.get("name") or item.get("type", "???")
    parts.append(name)

    # Show type if custom name differs
    if item.get("name") and item.get("type"):
        parts.append(f"({item['type']})")

    # Count
    count = item.get("count", 1)
    if count > 1:
        parts.append(f"x{count}")

    # Details
    details = []
    if "condition" in item:
        details.append(f"cond:{item['condition']}")
    if "uses" in item:
        details.append(f"uses:{item['uses']}")
    if "ammo" in item:
        details.append(f"ammo:{item['ammo']}")
    if item.get("favorite"):
        details.append("fav")
    if "weight" in item:
        details.append(f"wt:{item['weight']:.1f}")
    if "error" in item:
        details.append(f"ERROR: {item['error']}")

    if details:
        parts.append(f"({', '.join(details)})")

    print(f"{pad}{' '.join(parts)}")

    # Nested container items
    sub_items = item.get("items", [])
    for i, sub in enumerate(sub_items):
        is_last_sub = (i == len(sub_items) - 1)
        _print_item(sub, indent=indent + 1, is_last=is_last_sub)


# ---------------------------------------------------------------------------
# File output
# ---------------------------------------------------------------------------

def _item_to_dict(item, slot=None):
    """Convert a parsed item to a clean JSON-serializable dict."""
    d = {}
    if slot:
        d["slot"] = slot
    d["type"] = item.get("type", "???")
    if item.get("name"):
        d["name"] = item["name"]
    d["count"] = item.get("count", 1)
    if "condition" in item:
        d["condition"] = item["condition"]
    if "uses" in item:
        d["uses"] = item["uses"]
    if "ammo" in item:
        d["ammo"] = item["ammo"]
    if item.get("favorite"):
        d["favorite"] = True
    if "weight" in item:
        d["weight"] = item["weight"]
    if "error" in item:
        d["error"] = item["error"]

    sub_items = item.get("items", [])
    if sub_items:
        d["items"] = [_item_to_dict(sub) for sub in sub_items]

    return d


def inventory_to_json(inventory: dict, worn_items: list, hand_left: int,
                       hand_right: int, player_name: str = "") -> dict:
    """Convert extracted inventory to a JSON-serializable dict."""
    worn_map = {}
    for w in worn_items:
        worn_map[w["index"]] = w["location"]

    items_out = []
    for idx, item in enumerate(inventory["items"]):
        slot = _get_slot_label(item, idx, worn_map, hand_left, hand_right)
        items_out.append(_item_to_dict(item, slot))

    result = {
        "player": player_name,
        "capacity": inventory["capacity"],
        "totalItems": sum(it.get("count", 1) for it in inventory["items"]),
        "items": items_out,
    }
    return result


def _format_item_line(item, indent, slot=None):
    """Format a single item as a text line (same as _print_item but returns str)."""
    pad = "  " * indent
    parts = []

    if slot:
        parts.append(f"[{slot}]")

    name = item.get("name") or item.get("type", "???")
    parts.append(name)

    if item.get("name") and item.get("type"):
        parts.append(f"({item['type']})")

    count = item.get("count", 1)
    if count > 1:
        parts.append(f"x{count}")

    details = []
    if "condition" in item:
        details.append(f"cond:{item['condition']}")
    if "uses" in item:
        details.append(f"uses:{item['uses']}")
    if "ammo" in item:
        details.append(f"ammo:{item['ammo']}")
    if item.get("favorite"):
        details.append("fav")
    if "weight" in item:
        details.append(f"wt:{item['weight']:.1f}")
    if "error" in item:
        details.append(f"ERROR: {item['error']}")
    if details:
        parts.append(f"({', '.join(details)})")

    lines = [f"{pad}{' '.join(parts)}"]

    for sub in item.get("items", []):
        lines.extend(_format_item_line(sub, indent + 1))

    return lines


def format_item_tree_text(inventory: dict, worn_items: list, hand_left: int,
                           hand_right: int, player_name: str = "") -> str:
    """Format the full inventory as a text string."""
    worn_map = {}
    for w in worn_items:
        worn_map[w["index"]] = w["location"]

    total = sum(it.get("count", 1) for it in inventory["items"])
    lines = [
        f"Player: {player_name}",
        f"Inventory ({total} items, capacity={inventory['capacity']}):",
    ]

    for idx, item in enumerate(inventory["items"]):
        slot = _get_slot_label(item, idx, worn_map, hand_left, hand_right)
        lines.extend(_format_item_line(item, indent=1, slot=slot))

    return "\n".join(lines) + "\n"
