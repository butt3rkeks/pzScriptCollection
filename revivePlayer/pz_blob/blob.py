"""Full blob parser orchestrator and legacy PatchInfo adapter."""

import struct
from collections import OrderedDict

from .reader import BlobReader
from .constants import BODY_PART_NAMES, NUM_BODY_PARTS, STAT_NAMES
from .log import F, _ro, vlog, vlog_offset, vlog_section
from .kahlua import read_lua_table, print_table_tree, make_json_safe_table
from .parsers import (
    parse_survivor_desc_full,
    parse_human_visual_full,
    parse_inventory_full,
    parse_stats_full,
    parse_body_part_full,
    parse_body_damage_full,
    parse_thermoregulator_full,
    parse_xp_full,
    parse_fitness_full,
    parse_nutrition_full,
    parse_craft_history_full,
)


# ---------------------------------------------------------------------------
# PatchInfo (legacy, for revive/verify commands)
# ---------------------------------------------------------------------------

class PatchInfo:
    """Collects offsets of fields that need patching."""

    def __init__(self):
        self.body_parts = []
        self.infection_time_offset = None
        self.infection_time_value = None
        self.infection_mortality_duration_offset = None
        self.infection_mortality_duration_value = None
        self.stats_offsets = {}   # name -> offset
        self.stats_values = {}    # name -> float value
        self.death_drag_down_offset = None
        self.death_drag_down_value = None
        # Extra info for verify
        self.player_pos = None
        self.player_name = ""
        self.hours_survived = 0.0


# ---------------------------------------------------------------------------
# Full blob parser
# ---------------------------------------------------------------------------

def parse_blob_full(data: bytes, world_version: int) -> tuple:
    """Parse the player data blob fully. Returns (BlobReader, sections_dict).

    The sections dict maps section names to OrderedDicts of field entries,
    each with {offset, type, value, editable}.
    """
    reader = BlobReader(data)
    sections = OrderedDict()

    vlog(f"\n  Blob size: {len(data)} bytes, worldVersion={world_version}")

    # === IsoPlayer.load() header ===
    vlog_section(reader, "IsoPlayer Header")
    hdr = OrderedDict()
    hdr["_serialise"] = _ro(reader.pos, "byte", reader.get_byte())
    hdr["_objectID"] = _ro(reader.pos, "byte", reader.get_byte())
    vlog_offset(reader, f"serialise={hdr['_serialise']['value']}, objectID={hdr['_objectID']['value']}")
    sections["IsoPlayerHeader"] = hdr

    # === IsoMovingObject.load() ===
    vlog_section(reader, "IsoMovingObject")
    mov = OrderedDict()
    mov["_offsetX"] = _ro(reader.pos, "float", reader.get_float())
    mov["_offsetY"] = _ro(reader.pos, "float", reader.get_float())
    mov["x"] = F(reader.pos, "float", reader.get_float())
    mov["y"] = F(reader.pos, "float", reader.get_float())
    mov["z"] = F(reader.pos, "float", reader.get_float())
    mov["direction"] = F(reader.pos, "int", reader.get_int())
    vlog_offset(reader, f"pos=({mov['x']['value']:.1f}, {mov['y']['value']:.1f}, {mov['z']['value']:.1f}), dir={mov['direction']['value']}")
    sections["IsoMovingObject"] = mov

    # Lua modData table
    has_table = reader.get_byte()
    if has_table != 0:
        vlog_offset(reader, "modData table present, parsing...")
        mod_data = read_lua_table(reader)
        from .log import is_verbose
        if is_verbose():
            print_table_tree(mod_data, indent=13)
        sections["modData"] = OrderedDict([
            ("_NOTE", _ro(0, "info", "Read-only. Editing would require re-serialization.")),
            ("_data", _ro(0, "table", make_json_safe_table(mod_data)))
        ])
    else:
        vlog_offset(reader, "no modData table")
        sections["modData"] = OrderedDict([("_NOTE", _ro(0, "info", "No modData table present"))])

    # === IsoGameCharacter.load() ===
    vlog_section(reader, "SurvivorDesc")
    has_descriptor = reader.get_byte()
    if has_descriptor == 1:
        sections["SurvivorDesc"] = parse_survivor_desc_full(reader, world_version)
    else:
        vlog(f"             (no descriptor)")
        sections["SurvivorDesc"] = OrderedDict()

    vlog_section(reader, "HumanVisual")
    sections["HumanVisual"] = parse_human_visual_full(reader, world_version)

    vlog_section(reader, "Inventory")
    inv_start = reader.pos
    sections["Inventory"] = parse_inventory_full(reader, world_version)
    inv_end = reader.pos
    sections["Inventory"]["_byte_range"] = (inv_start, inv_end)

    # Asleep + forceWakeUpTime
    sleep = OrderedDict()
    sleep["asleep"] = F(reader.pos, "byte", reader.get_byte())
    sleep["forceWakeUpTime"] = F(reader.pos, "float", reader.get_float())
    vlog_offset(reader, f"asleep={sleep['asleep']['value']}, forceWakeUpTime={sleep['forceWakeUpTime']['value']}")
    sections["Sleep"] = sleep

    # Stats
    vlog_section(reader, "Stats")
    sections["Stats"] = parse_stats_full(reader, world_version)

    # BodyDamage - Body Parts
    vlog_section(reader, "BodyDamage - Body Parts")
    bp_sections = OrderedDict()
    for bp_idx in range(NUM_BODY_PARTS):
        bp_name = BODY_PART_NAMES[bp_idx] if bp_idx < len(BODY_PART_NAMES) else f"Part_{bp_idx}"
        bp_sections[bp_name] = parse_body_part_full(reader, world_version, bp_idx)
    sections["BodyParts"] = bp_sections

    # BodyDamage - Main Fields
    vlog_section(reader, "BodyDamage - Main Fields")
    sections["BodyDamage"] = parse_body_damage_full(reader, world_version)

    # Thermoregulator
    vlog_section(reader, "Thermoregulator")
    has_thermo = reader.get_byte()
    if has_thermo == 1:
        sections["Thermoregulator"] = parse_thermoregulator_full(reader, world_version)
    else:
        vlog(f"             (not present)")
        sections["Thermoregulator"] = OrderedDict()

    # XP
    vlog_section(reader, "XP / Perks")
    sections["XP"] = parse_xp_full(reader, world_version)

    # Hand item indices
    hands = OrderedDict()
    hands["leftHandItem"] = F(reader.pos, "int", reader.get_int())
    hands["rightHandItem"] = F(reader.pos, "int", reader.get_int())
    vlog_offset(reader, f"leftHand={hands['leftHandItem']['value']}, rightHand={hands['rightHandItem']['value']}")
    sections["HandItems"] = hands

    # onFire
    fire = OrderedDict()
    fire["onFire"] = F(reader.pos, "byte", reader.get_byte())
    if fire["onFire"]["value"]:
        vlog_offset(reader, "ON FIRE!")
    sections["OnFire"] = fire

    # Effects
    vlog_section(reader, "Effects / Misc")
    eff = OrderedDict()
    eff["depressEffect"] = F(reader.pos, "float", reader.get_float())
    eff["depressFirstTakeTime"] = F(reader.pos, "float", reader.get_float())
    eff["betaEffect"] = F(reader.pos, "float", reader.get_float())
    eff["betaDelta"] = F(reader.pos, "float", reader.get_float())
    eff["painEffect"] = F(reader.pos, "float", reader.get_float())
    eff["painDelta"] = F(reader.pos, "float", reader.get_float())
    eff["sleepingTabletEffect"] = F(reader.pos, "float", reader.get_float())
    eff["sleepingTabletDelta"] = F(reader.pos, "float", reader.get_float())
    sections["Effects"] = eff

    # Read books
    books = OrderedDict()
    num_books = reader.get_int()
    book_list = []
    for _ in range(num_books):
        bname = reader.read_string()
        bval = reader.get_int()
        book_list.append({"name": bname, "value": bval})
    books["_books"] = _ro(0, "list", book_list)
    vlog_offset(reader, f"{num_books} books read")

    books["reduceInfectionPower"] = F(reader.pos, "float", reader.get_float())
    sections["Books"] = books

    # Known recipes
    recipes = OrderedDict()
    num_recipes = reader.get_int()
    recipe_list = []
    for _ in range(num_recipes):
        recipe_list.append(reader.read_string())
    recipes["_recipes"] = _ro(0, "list", recipe_list)
    vlog_offset(reader, f"{num_recipes} recipes known")
    sections["Recipes"] = recipes

    # Misc timers
    timers = OrderedDict()
    timers["lastHourSleeped"] = F(reader.pos, "int", reader.get_int())
    timers["timeSinceLastSmoke"] = F(reader.pos, "float", reader.get_float())
    timers["beardGrowTiming"] = F(reader.pos, "float", reader.get_float())
    timers["hairGrowTiming"] = F(reader.pos, "float", reader.get_float())
    sections["Timers"] = timers

    # Cheat flags
    vlog_section(reader, "Cheat Flags")
    cheats = OrderedDict()
    cheats["unlimitedCarry"] = F(reader.pos, "byte", reader.get_byte())
    cheats["buildCheat"] = F(reader.pos, "byte", reader.get_byte())
    cheats["healthCheat"] = F(reader.pos, "byte", reader.get_byte())
    cheats["mechanicsCheat"] = F(reader.pos, "byte", reader.get_byte())
    cheats["movablesCheat"] = F(reader.pos, "byte", reader.get_byte())
    cheats["farmingCheat"] = F(reader.pos, "byte", reader.get_byte())
    if world_version >= 202:
        cheats["fishingCheat"] = F(reader.pos, "byte", reader.get_byte())
    if world_version >= 217:
        cheats["brushTool"] = F(reader.pos, "byte", reader.get_byte())
        cheats["fastMove"] = F(reader.pos, "byte", reader.get_byte())
    cheats["timedActionInstant"] = F(reader.pos, "byte", reader.get_byte())
    cheats["unlimitedEndurance"] = F(reader.pos, "byte", reader.get_byte())
    if world_version >= 230:
        cheats["unlimitedAmmo"] = F(reader.pos, "byte", reader.get_byte())
        cheats["knowAllRecipes"] = F(reader.pos, "byte", reader.get_byte())
    cheats["sneaking"] = F(reader.pos, "byte", reader.get_byte())
    cheats["deathDragDown"] = F(reader.pos, "byte", reader.get_byte())
    if cheats["deathDragDown"]["value"]:
        vlog(f"  [0x{cheats['deathDragDown']['offset']:04X}]   deathDragDown = 1 <-- DEATH FLAG")
    sections["CheatFlags"] = cheats

    # Literature
    lit = OrderedDict()
    lit_size = reader.get_int()
    lit_list = []
    for _ in range(lit_size):
        lname = reader.read_string()
        lval = reader.get_int()
        lit_list.append({"name": lname, "value": lval})
    lit["_literature"] = _ro(0, "list", lit_list)
    sections["Literature"] = lit

    # Print media (version >= 222)
    if world_version >= 222:
        pm = OrderedDict()
        pm_size = reader.get_int()
        pm_list = []
        for _ in range(pm_size):
            pm_list.append(reader.read_string())
        pm["_printMedia"] = _ro(0, "list", pm_list)
        sections["PrintMedia"] = pm

    # Last animal pet
    misc2 = OrderedDict()
    misc2["lastAnimalPet"] = F(reader.pos, "long", reader.get_long())
    sections["AnimalMisc"] = misc2

    # Player cheats (version >= 231)
    if world_version >= 231:
        cheats_size = reader.get_int()
        reader.skip(cheats_size)

    # === IsoPlayer.load() continues ===
    vlog_section(reader, "IsoPlayer Data")
    player = OrderedDict()
    player["hoursSurvived"] = F(reader.pos, "double", reader.get_double())
    vlog_offset(reader, f"hoursSurvived={player['hoursSurvived']['value']:.1f}")

    player["zombieKills"] = F(reader.pos, "int", reader.get_int())
    vlog_offset(reader, f"zombieKills={player['zombieKills']['value']}")

    # Worn items (read-only - variable length with string references)
    worn_count = reader.get_byte()
    worn_list = []
    for _ in range(worn_count):
        wname = reader.read_string()
        widx = reader.get_short()
        worn_list.append({"location": wname, "index": widx})
    player["_wornItems"] = _ro(0, "list", worn_list)
    vlog_offset(reader, f"{worn_count} worn items")

    player["leftHandIdx"] = F(reader.pos, "short", reader.get_short())
    player["rightHandIdx"] = F(reader.pos, "short", reader.get_short())
    player["survivorKills"] = F(reader.pos, "int", reader.get_int())
    vlog_offset(reader, f"survivorKills={player['survivorKills']['value']}")
    sections["Player"] = player

    # Nutrition
    vlog_section(reader, "Nutrition")
    sections["Nutrition"] = parse_nutrition_full(reader)

    # Player metadata
    meta = OrderedDict()
    meta["allChatMuted"] = F(reader.pos, "byte", reader.get_byte())
    meta["_tagPrefix"] = _ro(reader.pos, "string", reader.read_string())
    meta["tagR"] = F(reader.pos, "float", reader.get_float())
    meta["tagG"] = F(reader.pos, "float", reader.get_float())
    meta["tagB"] = F(reader.pos, "float", reader.get_float())
    meta["_displayName"] = _ro(reader.pos, "string", reader.read_string())
    meta["showTag"] = F(reader.pos, "byte", reader.get_byte())
    meta["factionPvp"] = F(reader.pos, "byte", reader.get_byte())
    vlog_offset(reader, f"displayName=\"{meta['_displayName']['value']}\", tag=\"{meta['_tagPrefix']['value']}\"")

    if world_version >= 239:
        meta["autoDrink"] = F(reader.pos, "byte", reader.get_byte())

    # Unknown byte
    meta["_unknownByte"] = _ro(reader.pos, "byte", reader.get_byte())
    sections["PlayerMeta"] = meta

    # Vehicle
    vehicle = OrderedDict()
    has_vehicle = reader.get_byte()
    vehicle["_hasVehicle"] = _ro(0, "info", has_vehicle)
    if has_vehicle == 1:
        vehicle["vehicleX"] = F(reader.pos, "float", reader.get_float())
        vehicle["vehicleY"] = F(reader.pos, "float", reader.get_float())
        vehicle["vehicleSeat"] = F(reader.pos, "byte", reader.get_byte())
        vehicle["vehicleRunning"] = F(reader.pos, "byte", reader.get_byte())
        vlog_offset(reader, f"in vehicle at ({vehicle['vehicleX']['value']:.0f}, {vehicle['vehicleY']['value']:.0f}), seat={vehicle['vehicleSeat']['value']}")
    sections["Vehicle"] = vehicle

    # Mechanics items (read-only)
    mech = OrderedDict()
    mech_size = reader.get_int()
    mech_items = []
    for _ in range(mech_size):
        a = reader.get_long()
        b = reader.get_long()
        mech_items.append({"a": a, "b": b})
    mech["_mechanicsItems"] = _ro(0, "list", mech_items)
    sections["Mechanics"] = mech

    # Fitness
    vlog_section(reader, "Fitness")
    sections["Fitness"] = parse_fitness_full(reader, world_version)

    # Already read books
    arb = OrderedDict()
    already_read_count = reader.get_short()
    arb_list = []
    for _ in range(already_read_count):
        arb_list.append(reader.get_short())
    arb["_alreadyReadBooks"] = _ro(0, "list", arb_list)
    vlog_offset(reader, f"{already_read_count} already-read books")
    sections["AlreadyReadBooks"] = arb

    # Known media lines
    kml = OrderedDict()
    media_count = reader.get_short()
    media_list = []
    for _ in range(media_count):
        media_list.append(reader.read_string())
    kml["_knownMediaLines"] = _ro(0, "list", media_list)
    sections["KnownMedia"] = kml

    # Voice type
    if world_version >= 203:
        voice = OrderedDict()
        voice["voiceType"] = F(reader.pos, "byte", reader.get_byte())
        sections["Voice"] = voice

    # Craft history
    if world_version >= 228:
        vlog_section(reader, "CraftHistory")
        sections["CraftHistory"] = parse_craft_history_full(reader)

    # Done parsing
    print(f"\n[OK] Parsed {reader.pos} of {len(reader.data)} bytes successfully")
    if reader.pos < len(reader.data):
        print(f"     ({len(reader.data) - reader.pos} trailing bytes remain)")
    if reader.pos > len(reader.data):
        print(f"     WARNING: Parser overran blob by {reader.pos - len(reader.data)} bytes!")

    return reader, sections


# ---------------------------------------------------------------------------
# Legacy adapter
# ---------------------------------------------------------------------------

def parse_blob(data: bytes, world_version: int) -> tuple:
    """Parse the player data blob. Returns (BlobReader, PatchInfo).

    Delegates to parse_blob_full() and builds a PatchInfo from the result.
    """
    reader, sections = parse_blob_full(data, world_version)
    patch = _sections_to_patch_info(sections)
    return reader, patch


def _sections_to_patch_info(sections: dict) -> PatchInfo:
    """Build a legacy PatchInfo from the full sections dict."""
    patch = PatchInfo()

    # Position
    mov = sections.get("IsoMovingObject", {})
    if "x" in mov and "y" in mov and "z" in mov:
        patch.player_pos = (mov["x"]["value"], mov["y"]["value"], mov["z"]["value"])

    # Stats
    stats = sections.get("Stats", {})
    for name, field in stats.items():
        if isinstance(field, dict) and "offset" in field:
            patch.stats_offsets[name] = field["offset"]
            patch.stats_values[name] = field["value"]

    # Body parts
    bp_sections = sections.get("BodyParts", {})
    for idx, bp_name in enumerate(BODY_PART_NAMES):
        bp = bp_sections.get(bp_name, {})
        if not bp:
            continue
        bp_info = {"index": idx}
        bp_info["health_offset"] = bp.get("health", {}).get("offset", 0)
        bp_info["health"] = bp.get("health", {}).get("value", 100.0)
        bp_info["cut_offset"] = bp.get("cut", {}).get("offset", 0)
        bp_info["bitten_offset"] = bp.get("bitten", {}).get("offset", 0)
        bp_info["scratched_offset"] = bp.get("scratched", {}).get("offset", 0)
        bp_info["bandaged_offset"] = bp.get("_bandaged", {}).get("offset", 0)
        bp_info["bleeding_offset"] = bp.get("bleeding", {}).get("offset", 0)
        bp_info["deep_wounded_offset"] = bp.get("deepWounded", {}).get("offset", 0)
        bp_info["fake_infected_offset"] = bp.get("fakeInfected", {}).get("offset", 0)
        bp_info["infected_offset"] = bp.get("infected", {}).get("offset", 0)
        bp_info["infected_wound_offset"] = bp.get("_infectedWound", {}).get("offset", 0)
        patch.body_parts.append(bp_info)

    # Infection
    bd = sections.get("BodyDamage", {})
    if "infectionTime" in bd:
        patch.infection_time_offset = bd["infectionTime"]["offset"]
        patch.infection_time_value = bd["infectionTime"]["value"]
    if "infectionMortalityDuration" in bd:
        patch.infection_mortality_duration_offset = bd["infectionMortalityDuration"]["offset"]
        patch.infection_mortality_duration_value = bd["infectionMortalityDuration"]["value"]

    # Death flag
    cheats = sections.get("CheatFlags", {})
    if "deathDragDown" in cheats:
        patch.death_drag_down_offset = cheats["deathDragDown"]["offset"]
        patch.death_drag_down_value = cheats["deathDragDown"]["value"]

    # Player info
    player = sections.get("Player", {})
    if "hoursSurvived" in player:
        patch.hours_survived = player["hoursSurvived"]["value"]
    pmeta = sections.get("PlayerMeta", {})
    if "_displayName" in pmeta:
        patch.player_name = pmeta["_displayName"]["value"]

    return patch
