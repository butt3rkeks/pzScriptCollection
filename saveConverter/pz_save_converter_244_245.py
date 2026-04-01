#!/usr/bin/env python3
"""
Project Zomboid Save Converter: World Version 244 (42.15.3) -> 245 (42.16.0)

Run from inside the save folder on a Linux dedicated server:
    cd server-data/Saves/Multiplayer/<saveName>
    python3 pz_save_converter_244_245.py [--dry-run] [--force] [-v]

What it does:
  1. Bumps version int (244->245) in ~25 binary file types, 2 SQLite DBs
  2. Inserts 1-byte `wild=false` into each IsoAnimal in apop/ files
  3. Converts SandboxOption FirearmUseDamageChance from boolean to enum
  4. Clears stale isLoaded flags in WorldDictionary.bin ScriptsDictionary
     (prevents client crash on removed scripts like Base.Log_Stack_01)
  5. Recomputes chunk CRC32 checksums

Caveats:
  - Animals in player inventories (AnimalInventoryItem) are embedded inline
    and won't get the wild byte. Use --force to bypass the pre-flight check.
  - Native C++ save files (zombie population, collision data) are opaque
    and assumed unchanged between these versions.
"""

import struct
import sqlite3
import re
import sys
import logging
from pathlib import Path
from zlib import crc32 as _zlib_crc32

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)

OLD_VERSION = 244
NEW_VERSION = 245

# Wool condition: breed.woolType != null AND adef.maxWool > 0
# Only adult sheep (ewe/ram) have maxWool > 0; lambs inherit the breed but not maxWool.
WOOL_BREEDS = {"suffolk", "rambouillet", "friesian"}
WOOL_TYPES = {"ewe", "ram"}
# Egg condition: adef.eggsPerDay > 0
EGG_TYPES = {"hen", "turkeyhen"}

# Files with version int at offset 0 (no magic prefix)
SIMPLE_VERSION_FILES = [
    "map_ver.bin", "map_visited.bin", "global_mod_data.bin",
    "id_manager_data.bin", "iTrack.bin", "metadata.bin",
    "reanimated.bin", "important_area_data.bin",
]
# Files with 4-byte magic prefix then version int at offset 4
MAGIC_VERSION_FILES = {
    "map_t.bin": b"GMTM", "map_meta.bin": b"META",
    "map_zone.bin": b"ZONE", "map_animals.bin": b"ZONE",
    "map_sand.bin": b"SAND", "map_worldgen.bin": b"WGEN",
    "map_basements.bin": b"BSMT", "map_symbols.bin": b"WMSY",
    "servermap_symbols.bin": b"WMSY",
}
# Combined set for skip-detection in named player file scan
_HANDLED_FILES = set(SIMPLE_VERSION_FILES) | set(MAGIC_VERSION_FILES)


# ---------------------------------------------------------------------------
# Binary helpers (big-endian, matching Java's ByteBuffer default)
# ---------------------------------------------------------------------------

def _reader(fmt):
    size = struct.calcsize(fmt)
    def read(buf, pos):
        return struct.unpack_from(fmt, buf, pos)[0], pos + size
    return read

read_byte   = _reader(">b")
read_ubyte  = _reader(">B")
read_short  = _reader(">h")
read_int    = _reader(">i")
read_float  = _reader(">f")

def read_pz_string(buf, pos):
    """PZ ByteBuffer string: short numBytes + UTF-8 data."""
    num_bytes, pos = read_short(buf, pos)
    if num_bytes <= 0:
        return "", pos
    return buf[pos:pos + num_bytes].decode("utf-8", errors="replace"), pos + num_bytes

def skip_pz_string(buf, pos):
    num_bytes, pos = read_short(buf, pos)
    return pos + max(0, num_bytes)

def write_pz_string(s):
    if not s:
        return struct.pack(">h", 0)
    encoded = s.encode("utf-8")
    return struct.pack(">h", len(encoded)) + encoded

def skip_kahlua_table(buf, pos):
    """Skip a KahluaTableImpl blob (type markers: 0=STR, 1=DBL, 2=TBL, 3=BOOL)."""
    count, pos = read_int(buf, pos)
    for _ in range(count):
        pos = _skip_kahlua_value(buf, pos)  # key
        pos = _skip_kahlua_value(buf, pos)  # value
    return pos

def _skip_kahlua_value(buf, pos):
    marker, pos = read_byte(buf, pos)
    if marker == 0:   return skip_pz_string(buf, pos)
    if marker == 1:   return pos + 8
    if marker == 2:   return skip_kahlua_table(buf, pos)
    if marker == 3:   return pos + 1
    raise ValueError(f"Unknown KahluaTable type marker {marker} at offset {pos - 1}")

def java_crc32(data):
    return _zlib_crc32(data) & 0xFFFFFFFF


# ---------------------------------------------------------------------------
# IsoAnimal parser
# ---------------------------------------------------------------------------

def parse_iso_animal(buf, pos):
    """Parse an IsoAnimal record AFTER the 2-byte header (serialize + classID).
    Returns (type, breed, end_pos, info). end_pos is right after petTimer."""
    start = pos
    dbg = {}

    def mark(name):
        dbg[name] = pos

    try:
        return _parse_iso_animal_body(buf, pos, dbg, mark)
    except (struct.error, IndexError, ValueError) as e:
        raise RuntimeError(
            f"IsoAnimal parse failed near offset {dbg.get('_last', pos)}: {e}\n  dbg={dbg}"
        ) from e


def _parse_iso_animal_body(buf, pos, dbg, mark):
    start = pos

    # Zone UUID (2x long) + position (3x float) + direction (int) + stats (24x float)
    mark("zone"); dbg["_last"] = pos
    pos += 16 + 12 + 4 + 96

    mark("strings"); dbg["_last"] = pos
    animal_type, pos = read_pz_string(buf, pos)
    breed_name, pos = read_pz_string(buf, pos)
    custom_name, pos = read_pz_string(buf, pos)

    mark("moddata"); dbg["_last"] = pos
    pos = skip_kahlua_table(buf, pos)

    # itemId(int) + isFemale(byte) + animalId(int)
    pos += 4
    _, pos = read_ubyte(buf, pos)
    animal_id, pos = read_int(buf, pos)

    # Genome
    mark("genome"); dbg["_last"] = pos
    gene_count, pos = read_int(buf, pos)
    for _ in range(gene_count):
        pos += 4                         # gene id
        pos = skip_pz_string(buf, pos)   # gene name
        for _ in range(2):               # 2 alleles
            pos = skip_pz_string(buf, pos)  # allele name
            pos += 4 + 4 + 1               # currentValue + trueRatioValue + dominant
            pos = skip_pz_string(buf, pos)  # geneticDisorder

    # Attached tree: byte flag [+ 2x int]
    mark("post_genome"); dbg["_last"] = pos
    flag, pos = read_ubyte(buf, pos)
    if flag: pos += 8

    # age(int) + hoursSurvived(double) + calendar(long) + size(float) + attachBackToMother(int)
    pos += 4 + 8 + 8 + 4 + 4

    # Mother: byte [+ int]
    flag, pos = read_ubyte(buf, pos)
    if flag: pos += 4

    # Pregnant: byte [+ int]
    pregnant, pos = read_ubyte(buf, pos)
    if pregnant: pos += 4

    # canHaveMilk(byte) + milkQty(float) + maxMilkActual(float) + milkRemoved(int) + hutchPos(byte)
    pos += 1 + 4 + 4 + 4 + 1

    # Conditional wool (only wool breeds on adult sheep types)
    mark("wool"); dbg["_last"] = pos
    has_wool = breed_name.lower() in WOOL_BREEDS and animal_type.lower() in WOOL_TYPES
    if has_wool: pos += 4

    # fertilizedTime(int) + fertilized(byte)
    pos += 4 + 1

    # Conditional eggs
    has_eggs = animal_type.lower() in EGG_TYPES
    if has_eggs: pos += 4

    # stressLevel(float)
    pos += 4

    # Player acceptance map: int count + count * (short + float)
    mark("acceptance"); dbg["_last"] = pos
    accept_count, pos = read_int(buf, pos)
    pos += accept_count * 6

    # weight(float) + lastPregnancyTime(long) + lastMilkTimer(long) +
    # lastImpregnateTime(int) + health(float) + virtualId(double)
    pos += 4 + 8 + 8 + 4 + 4 + 8
    # migrationGroup(string) + clutchSize(int)
    pos = skip_pz_string(buf, pos)
    pos += 4

    # Hook: byte [+ 3x int]
    mark("hook"); dbg["_last"] = pos
    flag, pos = read_ubyte(buf, pos)
    if flag: pos += 12

    # petTimer(float) — target
    pet_timer, pos = read_float(buf, pos)

    info = {
        "type": animal_type, "breed": breed_name, "animalId": animal_id,
        "genes": gene_count, "wool": has_wool, "eggs": has_eggs,
        "acceptanceEntries": accept_count, "petTimer": pet_timer,
        "bytesConsumed": pos - start,
    }
    return animal_type, breed_name, pos, info


# ---------------------------------------------------------------------------
# apop file: validate (dry-run) and patch (real run)
# ---------------------------------------------------------------------------

def _check_apop_version(data):
    """Returns version or raises."""
    if len(data) < 4:
        return None
    version = struct.unpack_from(">i", data, 0)[0]
    if version > NEW_VERSION:
        return None
    if version < 236:
        return None
    return version


def validate_apop_file(filepath):
    """Dry-run parse. Returns (animal_count, errors)."""
    data = filepath.read_bytes()
    version = _check_apop_version(data)
    if version is None:
        v = struct.unpack_from(">i", data, 0)[0] if len(data) >= 4 else "?"
        return 0, [f"Skipped (version {v}, need 236..{NEW_VERSION})"]

    errors = []
    animals = []
    pos = 4
    total = 0

    try:
        for chunk_idx in range(1024):
            va_count, pos = read_short(data, pos)

            for va_idx in range(va_count):
                pos += 44  # VirtualAnimal fixed header
                pos = skip_pz_string(data, pos)  # migrationGroup
                pos += 16  # nextEatTime + nextRestTime
                iso_count, pos = read_short(data, pos)

                for ani_idx in range(iso_count):
                    animal_start = pos
                    ser, pos = read_ubyte(data, pos)
                    cid, pos = read_ubyte(data, pos)
                    if ser != 1 or cid != 36:
                        errors.append(f"Chunk {chunk_idx}/VA {va_idx}/ani {ani_idx}: "
                                      f"bad header ser={ser} cid={cid} at {animal_start}")
                        return total, errors

                    atype, breed, pos, info = parse_iso_animal(data, pos)

                    if version >= NEW_VERSION:
                        _, pos = read_ubyte(data, pos)  # wild byte

                    animals.append(info)
                    total += 1

            # Tracks
            track_count, pos = read_short(data, pos)
            for _ in range(track_count):
                pos = skip_pz_string(data, pos)
                pos = skip_pz_string(data, pos)
                pos += 8  # x, y
                flag, pos = read_ubyte(data, pos)
                if flag: pos += 4
                pos += 9  # addedTime + addedToWorld

    except (struct.error, IndexError, ValueError, RuntimeError) as e:
        dump_start = max(0, pos - 16)
        dump_end = min(len(data), pos + 32)
        hex_dump = data[dump_start:dump_end].hex(" ")
        parts = [f"Parse error at offset {pos} (v{version}): {e}",
                 f"  Chunk {chunk_idx}, VA {va_idx}, animal {ani_idx}, parsed {total} OK",
                 f"  Hex [{dump_start}..{dump_end}]: {hex_dump}"]
        if animals:
            a = animals[-1]
            parts.append(f"  Last OK: {a['type']}/{a['breed']} id={a['animalId']} "
                         f"genes={a['genes']} wool={a['wool']} eggs={a['eggs']}")
        errors.append("\n".join(parts))
        return total, errors

    if pos != len(data):
        errors.append(f"Trailing data: parsed {pos}/{len(data)} bytes")

    if animals:
        types = {}
        for a in animals:
            k = f"{a['type']}/{a['breed']}"
            types[k] = types.get(k, 0) + 1
        log.info(f"  {filepath.name}: {total} animals "
                 f"[{', '.join(f'{k}: {v}' for k, v in sorted(types.items()))}]")
    else:
        log.debug(f"  {filepath.name}: empty")

    return total, errors


def patch_apop_file(filepath):
    """Patch apop file: bump version + insert wild=0 byte per animal. Returns animal count."""
    data = bytearray(filepath.read_bytes())
    version = _check_apop_version(data)
    if version is None or version >= NEW_VERSION:
        return 0

    out = bytearray(struct.pack(">i", NEW_VERSION))
    pos = 4
    total = 0

    for _ in range(1024):
        va_count, pos = read_short(data, pos)
        out += struct.pack(">h", va_count)

        for _ in range(va_count):
            va_start = pos
            pos += 44
            pos = skip_pz_string(data, pos)
            pos += 16
            iso_count, pos = read_short(data, pos)
            out += data[va_start:pos]  # VA header as-is

            for _ in range(iso_count):
                animal_start = pos
                pos += 2  # serialize + classID
                _, _, pet_end, _ = parse_iso_animal(data, pos)
                out += data[animal_start:pet_end]
                out += b'\x00'  # wild = false
                pos = pet_end
                total += 1

        # Tracks — copy as-is
        tracks_start = pos
        track_count, pos = read_short(data, pos)
        for _ in range(track_count):
            pos = skip_pz_string(data, pos)
            pos = skip_pz_string(data, pos)
            pos += 8
            flag, pos = read_ubyte(data, pos)
            if flag: pos += 4
            pos += 9
        out += data[tracks_start:pos]

    if pos != len(data):
        out += data[pos:]

    filepath.write_bytes(bytes(out))
    return total


# ---------------------------------------------------------------------------
# Chunk, isoregion, version-int, SQLite, sandbox patchers
# ---------------------------------------------------------------------------

def patch_chunk_file(filepath):
    """Patch chunk: version at offset 1, recompute CRC at offset 9."""
    data = bytearray(filepath.read_bytes())
    if len(data) < 17:
        return False
    if struct.unpack_from(">i", data, 1)[0] >= NEW_VERSION:
        return False
    struct.pack_into(">i", data, 1, NEW_VERSION)
    struct.pack_into(">i", data, 5, len(data))
    struct.pack_into(">q", data, 9, java_crc32(data[17:]))
    filepath.write_bytes(bytes(data))
    return True


def patch_isoregion_datachunk(filepath):
    """Patch version ints in datachunk block stream."""
    data = bytearray(filepath.read_bytes())
    if len(data) < 8:
        return False
    patched = False
    pos = 0
    while pos + 8 <= len(data):
        block_len, _ = read_int(data, pos)
        version, _ = read_int(data, pos + 4)
        if 0 < version <= OLD_VERSION:
            struct.pack_into(">i", data, pos + 4, NEW_VERSION)
            patched = True
        if block_len <= 0:
            break
        pos += block_len
    if patched:
        filepath.write_bytes(bytes(data))
    return patched


def patch_version_at_offset(filepath, offset):
    """Bump version int at offset. Accepts any version in (0, OLD_VERSION]."""
    data = bytearray(filepath.read_bytes())
    if len(data) < offset + 4:
        return False
    v = struct.unpack_from(">i", data, offset)[0]
    if v >= NEW_VERSION or v <= 0 or v > OLD_VERSION:
        return False
    struct.pack_into(">i", data, offset, NEW_VERSION)
    filepath.write_bytes(bytes(data))
    return True


def patch_after_magic(filepath, magic):
    """Validate magic prefix, then patch version at offset len(magic)."""
    data = bytearray(filepath.read_bytes())
    if len(data) < len(magic) + 4 or data[:len(magic)] != magic:
        return False
    return patch_version_at_offset(filepath, len(magic))


def patch_sqlite_db(filepath):
    """UPDATE worldversion in all tables that have the column."""
    if not filepath.exists():
        return 0
    conn = sqlite3.connect(str(filepath))
    total = 0
    try:
        for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({table})").fetchall()]
            if "worldversion" in cols:
                cur = conn.execute(f"UPDATE {table} SET worldversion=? WHERE worldversion<=?",
                                   (NEW_VERSION, OLD_VERSION))
                total += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return total


def patch_sandbox_binary(filepath):
    """Patch map_sand.bin: version bump + FirearmUseDamageChance bool->enum."""
    data = bytearray(filepath.read_bytes())
    if len(data) < 16 or data[:4] != b"SAND":
        return False
    v = struct.unpack_from(">i", data, 4)[0]
    if v > OLD_VERSION and v != NEW_VERSION:
        return False
    struct.pack_into(">i", data, 4, NEW_VERSION)

    option_count = struct.unpack_from(">i", data, 12)[0]
    pos = 16
    out = bytearray(data[:16])
    patched = False

    for _ in range(option_count):
        name, pos = read_pz_string(data, pos)
        value, pos = read_pz_string(data, pos)
        if name == "FirearmUseDamageChance" and value.lower() in ("true", "false"):
            old = value
            value = "2" if value.lower() == "true" else "1"
            log.info(f"  FirearmUseDamageChance: '{old}' -> '{value}'")
            patched = True
        out += write_pz_string(name) + write_pz_string(value)

    if pos < len(data):
        out += data[pos:]
    filepath.write_bytes(bytes(out))
    return patched


def patch_sandbox_lua(save_dir):
    """Patch _SandboxVars.lua files: FirearmUseDamageChance bool->int."""
    patched = False
    for d in [save_dir, save_dir.parent, save_dir.parent.parent]:
        for f in d.glob("*_SandboxVars.lua"):
            text = f.read_text(encoding="utf-8")
            new = re.sub(r"(FirearmUseDamageChance\s*=\s*)true(\s*[,\n])", r"\g<1>2\2", text)
            new = re.sub(r"(FirearmUseDamageChance\s*=\s*)false(\s*[,\n])", r"\g<1>1\2", new)
            if new != text:
                f.write_text(new, encoding="utf-8")
                log.info(f"  Patched {f.name}")
                patched = True
    return patched


# ---------------------------------------------------------------------------
# Pre-flight: carried animal check
# ---------------------------------------------------------------------------

def check_for_carried_animals(save_dir):
    """Scan player files for PZ-encoded 'Base.Animal' string (the only animal item type)."""
    pz_encoded = struct.pack(">h", 11) + b"Base.Animal"
    suspicious = []

    def scan(f):
        data = f.read_bytes()
        count = 0
        i = 0
        while (i := data.find(pz_encoded, i)) != -1:
            count += 1
            i += len(pz_encoded)
        return count

    for f in save_dir.glob("map_p*.bin"):
        n = scan(f)
        if n: suspicious.append((f.name, f"Base.Animal x{n}"))

    for f in save_dir.glob("*.bin"):
        if f.name.startswith(("map_", "gos_")) or f.name in _HANDLED_FILES:
            continue
        if f.read_bytes()[:4] == struct.pack(">i", OLD_VERSION):
            n = scan(f)
            if n: suspicious.append((f.name, f"Base.Animal x{n}"))

    return suspicious


# ---------------------------------------------------------------------------
# WorldDictionary patcher — clear stale isLoaded flags in ScriptsDictionary
# ---------------------------------------------------------------------------

def _skip_pz_strings(buf, pos, count):
    """Skip `count` PZ strings."""
    for _ in range(count):
        pos = skip_pz_string(buf, pos)
    return pos


def _skip_dictionary_info_entries(buf, pos, modules_count, mod_count):
    """Skip DictionaryInfo entries (Items or Entities section)."""
    entry_count, pos = read_int(buf, pos)
    use_short_module = modules_count > 127
    use_short_mod = mod_count > 127
    for _ in range(entry_count):
        pos += 2  # registryId (short)
        pos += 2 if use_short_module else 1  # moduleIndex
        pos = skip_pz_string(buf, pos)  # name
        bits, pos = read_ubyte(buf, pos)
        if bits & 1:  # isModded
            pos += 2 if use_short_mod else 1  # modId index
        if bits & 16:  # hasModOverrides
            if bits & 32:  # multipleOverrides
                count, pos = read_ubyte(buf, pos)
                pos += count * (2 if use_short_mod else 1)
            else:
                pos += 2 if use_short_mod else 1
    return pos


def _skip_string_dictionary(buf, pos):
    """Skip the StringDictionary section (register count + ByteBlock-wrapped registers)."""
    reg_count, pos = read_int(buf, pos)
    for _ in range(reg_count):
        pos = skip_pz_string(buf, pos)  # register name
        block_len, pos = read_int(buf, pos)  # ByteBlock length
        pos += block_len  # skip entire block contents
    return pos


def patch_world_dictionary(filepath, dry_run=False):
    """Clear isLoaded flag on all ScriptsDictionary entries.
    The server will re-enable valid ones on next startup.
    Returns (total_entries, cleared_count)."""
    if not filepath.exists():
        return 0, 0

    data = bytearray(filepath.read_bytes())
    pos = 0

    # Header: version(4) + nextInfoId(2) + nextObjectNameId(1) + nextSpriteNameId(4) = 11
    pos += 11

    # ModIDs table
    mod_count, pos = read_int(data, pos)
    pos = _skip_pz_strings(data, pos, mod_count)

    # Modules table
    modules_count, pos = read_int(data, pos)
    pos = _skip_pz_strings(data, pos, modules_count)

    log.debug(f"  WorldDict: {mod_count} mods, {modules_count} modules "
              f"(index size: {'short' if mod_count > 127 else 'byte'}/"
              f"{'short' if modules_count > 127 else 'byte'})")

    # Items section
    pos = _skip_dictionary_info_entries(data, pos, modules_count, mod_count)

    # Entities section — same format
    pos = _skip_dictionary_info_entries(data, pos, modules_count, mod_count)

    # Objects section: int count + entries (byte id + string name)
    obj_count, pos = read_int(data, pos)
    for _ in range(obj_count):
        pos += 1  # byte id
        pos = skip_pz_string(data, pos)

    # Sprites section: int count + entries (int id + string name)
    spr_count, pos = read_int(data, pos)
    for _ in range(spr_count):
        pos += 4  # int id
        pos = skip_pz_string(data, pos)

    # StringDictionary section
    pos = _skip_string_dictionary(data, pos)

    # === ScriptsDictionary section — this is what we need to patch ===
    reg_count, pos = read_int(data, pos)
    total_entries = 0
    cleared = 0

    for _ in range(reg_count):
        reg_name, pos = read_pz_string(data, pos)
        block_len, pos = read_int(data, pos)
        block_start = pos

        # Inside ByteBlock: short nextId + int entryCount
        pos += 2  # nextId
        entry_count, pos = read_int(data, pos)

        for _ in range(entry_count):
            # DictionaryScriptInfo: byte bitHeader, short registryId, long version, string name
            header_pos = pos
            flags, pos = read_ubyte(data, pos)
            pos += 2  # registryId
            pos += 8  # version hash

            # Read name for logging
            if flags & 1:  # name starts with "Base."
                raw_name, pos = read_pz_string(data, pos)
                name = "Base." + raw_name
            else:
                name, pos = read_pz_string(data, pos)

            is_loaded = bool(flags & 2)
            total_entries += 1

            if is_loaded:
                if dry_run:
                    log.info(f"    {reg_name}: {name} (isLoaded=true, would clear)")
                else:
                    data[header_pos] = flags & 0xFD  # clear bit 1
                    log.debug(f"    Cleared isLoaded: {reg_name}/{name}")
                cleared += 1

        # Verify we consumed exactly block_len bytes
        expected_end = block_start + block_len
        if pos != expected_end:
            log.warning(f"  {reg_name}: parsed {pos - block_start} bytes but block is {block_len}")
            pos = expected_end  # trust the block length

    if not dry_run and cleared > 0:
        filepath.write_bytes(bytes(data))

    return total_entries, cleared


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def _read_world_version(save_dir):
    """Read world version from map_ver.bin (SP) or map_t.bin (MP dedicated server).
    Returns version int or None if neither file exists."""
    ver_file = save_dir / "map_ver.bin"
    if ver_file.exists():
        data = ver_file.read_bytes()
        if len(data) >= 4:
            return struct.unpack_from(">i", data, 0)[0]
    # MP dedicated servers write version to map_t.bin: "GMTM" + int version
    t_file = save_dir / "map_t.bin"
    if t_file.exists():
        data = t_file.read_bytes()
        if len(data) >= 8 and data[:4] == b"GMTM":
            return struct.unpack_from(">i", data, 4)[0]
    return None


def main():
    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv
    if "-v" in sys.argv or "--verbose" in sys.argv:
        logging.getLogger().setLevel(logging.DEBUG)

    save_dir = Path.cwd()
    mode = "  [DRY RUN]" if dry_run else ""
    log.info(f"PZ Save Converter: v{OLD_VERSION} -> v{NEW_VERSION}{mode}")
    log.info(f"Save directory: {save_dir}")

    current = _read_world_version(save_dir)
    if current is None:
        log.error("Cannot detect world version. No map_ver.bin or map_t.bin found. "
                  "Are you in the save directory?")
        sys.exit(1)
    if current == NEW_VERSION:
        log.info(f"Already at v{NEW_VERSION}. Nothing to do.")
        return
    if current != OLD_VERSION:
        log.error(f"Save is v{current}, expected v{OLD_VERSION}.")
        sys.exit(1)

    # Pre-flight: carried animals
    suspicious = check_for_carried_animals(save_dir)
    if suspicious:
        log.warning("=" * 60)
        log.warning("POTENTIAL CARRIED ANIMALS DETECTED:")
        for name, detail in suspicious:
            log.warning(f"  {name} ({detail})")
        log.warning("Embedded animals lack the v245 wild byte. This may corrupt player data.")
        log.warning("Use --force to bypass.")
        log.warning("=" * 60)
        if dry_run:
            log.warning("(continuing in dry-run mode)")
        elif not force:
            sys.exit(1)

    log.info(f"Current version: {current}")
    stats = {"files": 0, "chunks": 0, "animals": 0, "db_rows": 0}

    if dry_run:
        _dry_run(save_dir, stats)
        return

    # --- Version int files ---
    log.info("Patching version-int files...")
    for name in SIMPLE_VERSION_FILES:
        f = save_dir / name
        if f.exists() and patch_version_at_offset(f, 0):
            log.info(f"  {name}")
            stats["files"] += 1

    for name, magic in MAGIC_VERSION_FILES.items():
        f = save_dir / name
        if f.exists() and patch_after_magic(f, magic):
            log.info(f"  {name}")
            stats["files"] += 1

    # Player files (PLYR magic)
    for f in save_dir.glob("map_p*.bin"):
        if patch_after_magic(f, b"PLYR"):
            log.info(f"  {f.name}")
            stats["files"] += 1

    # Named player files (no magic, version at offset 0)
    for f in save_dir.glob("*.bin"):
        if f.name.startswith(("map_", "gos_")) or f.name in _HANDLED_FILES:
            continue
        data = f.read_bytes()
        if len(data) >= 4 and struct.unpack_from(">i", data, 0)[0] == OLD_VERSION:
            if patch_version_at_offset(f, 0):
                log.info(f"  {f.name} (named player)")
                stats["files"] += 1

    # GLOS files
    for f in save_dir.glob("gos_*.bin"):
        if patch_after_magic(f, b"GLOS"):
            log.info(f"  {f.name}")
            stats["files"] += 1

    # --- Chunks ---
    log.info("Patching chunks...")
    map_dir = save_dir / "map"
    if map_dir.is_dir():
        for f in map_dir.rglob("*.bin"):
            if patch_chunk_file(f):
                stats["chunks"] += 1
    log.info(f"  {stats['chunks']} chunks patched")

    # --- isoregiondata ---
    log.info("Patching isoregiondata...")
    iso_dir = save_dir / "isoregiondata"
    if iso_dir.is_dir():
        header = iso_dir / "RegionHeader.bin"
        if header.exists():
            patch_version_at_offset(header, 0)
        for f in iso_dir.glob("datachunk_*.bin"):
            patch_isoregion_datachunk(f)

    # --- apop files ---
    log.info("Patching animal population...")
    apop_dir = save_dir / "apop"
    if apop_dir.is_dir():
        for f in sorted(apop_dir.glob("apop_*.bin")):
            n = patch_apop_file(f)
            if n > 0:
                log.info(f"  {f.name}: {n} animals")
                stats["animals"] += n
                stats["files"] += 1
    log.info(f"  {stats['animals']} animals patched")

    # --- SQLite ---
    log.info("Patching databases...")
    for name in ["players.db", "vehicles.db"]:
        f = save_dir / name
        if f.exists():
            n = patch_sqlite_db(f)
            if n: log.info(f"  {name}: {n} rows")
            stats["db_rows"] += n

    # --- Sandbox ---
    log.info("Patching sandbox options...")
    sand = save_dir / "map_sand.bin"
    if sand.exists():
        patch_sandbox_binary(sand)
    patch_sandbox_lua(save_dir)

    # --- WorldDictionary ---
    log.info("Patching WorldDictionary...")
    wd = save_dir / "WorldDictionary.bin"
    if wd.exists():
        total, cleared = patch_world_dictionary(wd)
        log.info(f"  {cleared}/{total} script entries: isLoaded cleared")

    # --- Summary ---
    log.info("=" * 50)
    log.info("Done!")
    log.info(f"  Files:   {stats['files']}")
    log.info(f"  Chunks:  {stats['chunks']}")
    log.info(f"  Animals: {stats['animals']}")
    log.info(f"  DB rows: {stats['db_rows']}")
    final = _read_world_version(save_dir)
    log.info(f"  World version: v{final}" + (" OK" if final == NEW_VERSION else " FAILED"))


def _dry_run(save_dir, stats):
    """Validate mode: inspect all files, parse all animals, report errors."""
    log.info("")
    log.info("=== File inventory ===")

    for name in SIMPLE_VERSION_FILES:
        f = save_dir / name
        if f.exists():
            v = struct.unpack_from(">i", f.read_bytes(), 0)[0]
            log.info(f"  {name}: v{v}")
            stats["files"] += 1

    for name, magic in MAGIC_VERSION_FILES.items():
        f = save_dir / name
        if f.exists():
            data = f.read_bytes()
            ok = data[:len(magic)] == magic
            v = struct.unpack_from(">i", data, len(magic))[0] if ok else "?"
            log.info(f"  {name}: v{v} [{'OK' if ok else 'BAD MAGIC'}]")
            stats["files"] += 1

    for f in sorted(save_dir.glob("map_p*.bin")):
        data = f.read_bytes()
        v = struct.unpack_from(">i", data, 4)[0] if data[:4] == b"PLYR" else "?"
        log.info(f"  {f.name}: v{v}")

    for f in sorted(save_dir.glob("gos_*.bin")):
        data = f.read_bytes()
        v = struct.unpack_from(">i", data, 4)[0] if data[:4] == b"GLOS" else "?"
        log.info(f"  {f.name}: v{v}")

    map_dir = save_dir / "map"
    if map_dir.is_dir():
        chunks = list(map_dir.rglob("*.bin"))
        log.info(f"Chunks: {len(chunks)}")
        for f in sorted(chunks)[:3]:
            data = f.read_bytes()
            if len(data) >= 17:
                v = struct.unpack_from(">i", data, 1)[0]
                crc_ok = struct.unpack_from(">q", data, 9)[0] == java_crc32(data[17:])
                log.info(f"  {f.relative_to(save_dir)}: v{v}, CRC {'OK' if crc_ok else 'BAD'}")

    iso_dir = save_dir / "isoregiondata"
    if iso_dir.is_dir():
        log.info(f"isoregiondata: {sum(1 for _ in iso_dir.glob('datachunk_*.bin'))} files")

    for name in ["players.db", "vehicles.db"]:
        f = save_dir / name
        if f.exists():
            try:
                conn = sqlite3.connect(str(f))
                for (t,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
                    cols = [r[1] for r in conn.execute(f"PRAGMA table_info({t})").fetchall()]
                    if "worldversion" in cols:
                        for v, n in conn.execute(f"SELECT worldversion, COUNT(*) FROM {t} GROUP BY worldversion"):
                            log.info(f"  {name}/{t}: v{v} x{n}")
                conn.close()
            except Exception as e:
                log.warning(f"  {name}: {e}")

    sand = save_dir / "map_sand.bin"
    if sand.exists():
        data = sand.read_bytes()
        if len(data) >= 16 and data[:4] == b"SAND":
            v = struct.unpack_from(">i", data, 4)[0]
            cnt = struct.unpack_from(">i", data, 12)[0]
            log.info(f"  map_sand.bin: v{v}, {cnt} options")
            pos = 16
            for _ in range(cnt):
                name, pos = read_pz_string(data, pos)
                value, pos = read_pz_string(data, pos)
                if name == "FirearmUseDamageChance":
                    needs = value.lower() in ("true", "false")
                    log.info(f"  FirearmUseDamageChance='{value}'" +
                             (" (needs conversion)" if needs else " (OK)"))

    # === apop validation ===
    log.info("")
    log.info("=== Validating apop files ===")
    errs_total = 0
    apop_dir = save_dir / "apop"
    if apop_dir.is_dir():
        for f in sorted(apop_dir.glob("apop_*.bin")):
            try:
                n, errs = validate_apop_file(f)
                stats["animals"] += n
                for e in errs:
                    log.error(f"  {f.name}: {e}")
                errs_total += len(errs)
            except Exception as e:
                log.error(f"  {f.name}: {e}")
                errs_total += 1
    else:
        log.info("  No apop/ directory")

    # WorldDictionary
    log.info("")
    log.info("=== WorldDictionary ===")
    wd = save_dir / "WorldDictionary.bin"
    if wd.exists():
        try:
            total, cleared = patch_world_dictionary(wd, dry_run=True)
            log.info(f"  {total} script entries, {cleared} with stale isLoaded (will be cleared)")
        except Exception as e:
            log.error(f"  Failed to parse: {e}")
            errs_total += 1
    else:
        log.info("  WorldDictionary.bin not found")

    log.info("")
    log.info("=" * 50)
    log.info(f"DRY RUN: {stats['animals']} animals, {errs_total} errors")
    if errs_total == 0:
        log.info("PASS — safe to run without --dry-run")
    else:
        log.error("FAIL — fix errors before converting")


if __name__ == "__main__":
    main()
