"""Section parsers for the PZ player data blob.

Each parser function takes (reader, world_version) and returns an OrderedDict
of field entries: {name: {offset, type, value, editable}}.
"""

from collections import OrderedDict

from .reader import BlobReader
from .constants import STAT_NAMES, BODY_PART_NAMES, DEATH_RELEVANT_STATS
from .log import F, _ro, vlog, vlog_offset, is_verbose


# ---------------------------------------------------------------------------
# SurvivorDesc
# ---------------------------------------------------------------------------

def parse_survivor_desc_full(reader: BlobReader, world_version: int):
    """Parse SurvivorDesc, return field dict."""
    s = OrderedDict()
    start = reader.pos

    s["_id"] = _ro(reader.pos, "int", reader.get_int())
    s["_forename"] = _ro(reader.pos, "string", reader.read_string())
    s["_surname"] = _ro(reader.pos, "string", reader.read_string())
    s["_torso"] = _ro(reader.pos, "string", reader.read_string())
    s["isFemale"] = F(reader.pos, "int", reader.get_int())
    s["_profession"] = _ro(reader.pos, "string", reader.read_string())

    vlog(f"             name=\"{s['_forename']['value']} {s['_surname']['value']}\", profession=\"{s['_profession']['value']}\"")

    has_extras = reader.get_int()
    extras = []
    if has_extras == 1:
        extra_count = reader.get_int()
        for _ in range(extra_count):
            extras.append(reader.read_string())
    s["_extras"] = _ro(0, "list", extras)

    xp_boost_size = reader.get_int()
    xp_boosts = {}
    for _ in range(xp_boost_size):
        bname = reader.read_string()
        bval = reader.get_int()
        xp_boosts[bname] = bval
    s["_xpBoosts"] = _ro(0, "map", xp_boosts)

    if world_version >= 208:
        s["_voicePrefix"] = _ro(reader.pos, "string", reader.read_string())
        s["voicePitch"] = F(reader.pos, "float", reader.get_float())
        s["voiceType"] = F(reader.pos, "int", reader.get_int())

    vlog(f"             ({reader.pos - start} bytes)")
    return s


# ---------------------------------------------------------------------------
# HumanVisual
# ---------------------------------------------------------------------------

def parse_item_visual(reader: BlobReader, world_version: int):
    """Parse a single ItemVisual (read-only, skip)."""
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


def parse_human_visual_full(reader: BlobReader, world_version: int):
    """Parse HumanVisual, return field dict."""
    s = OrderedDict()
    start = reader.pos
    flags1 = reader.get_byte()

    if flags1 & 0x04:
        s["hairColor_r"] = F(reader.pos, "byte", reader.get_byte())
        s["hairColor_g"] = F(reader.pos, "byte", reader.get_byte())
        s["hairColor_b"] = F(reader.pos, "byte", reader.get_byte())
    if flags1 & 0x02:
        s["beardColor_r"] = F(reader.pos, "byte", reader.get_byte())
        s["beardColor_g"] = F(reader.pos, "byte", reader.get_byte())
        s["beardColor_b"] = F(reader.pos, "byte", reader.get_byte())
    if flags1 & 0x08:
        s["skinColor_r"] = F(reader.pos, "byte", reader.get_byte())
        s["skinColor_g"] = F(reader.pos, "byte", reader.get_byte())
        s["skinColor_b"] = F(reader.pos, "byte", reader.get_byte())

    s["bodyHairIndex"] = F(reader.pos, "byte", reader.get_byte())
    s["skinTextureIndex"] = F(reader.pos, "byte", reader.get_byte())
    s["zombieRotStage"] = F(reader.pos, "byte", reader.get_byte())

    if flags1 & 0x40:
        s["_skinTextureName"] = _ro(reader.pos, "string", reader.read_string())
    if flags1 & 0x10:
        s["_beardModel"] = _ro(reader.pos, "string", reader.read_string())
    if flags1 & 0x20:
        s["_hairModel"] = _ro(reader.pos, "string", reader.read_string())

    blood_len = reader.get_byte()
    if blood_len > 0:
        reader.skip(blood_len)
    dirt_len = reader.get_byte()
    if dirt_len > 0:
        reader.skip(dirt_len)
    holes_len = reader.get_byte()
    if holes_len > 0:
        reader.skip(holes_len)

    visual_count = reader.get_byte()
    for _ in range(visual_count):
        parse_item_visual(reader, world_version)
    s["_clothingVisualCount"] = _ro(0, "info", visual_count)

    s["_nonAttachedHair"] = _ro(reader.pos, "string", reader.read_string())

    flags2 = reader.get_byte()
    if flags2 & 0x04:
        s["naturalHairColor_r"] = F(reader.pos, "byte", reader.get_byte())
        s["naturalHairColor_g"] = F(reader.pos, "byte", reader.get_byte())
        s["naturalHairColor_b"] = F(reader.pos, "byte", reader.get_byte())
    if flags2 & 0x02:
        s["naturalBeardColor_r"] = F(reader.pos, "byte", reader.get_byte())
        s["naturalBeardColor_g"] = F(reader.pos, "byte", reader.get_byte())
        s["naturalBeardColor_b"] = F(reader.pos, "byte", reader.get_byte())

    vlog(f"             flags=0x{flags1:02X}, {visual_count} clothing visuals ({reader.pos - start} bytes)")
    return s


# ---------------------------------------------------------------------------
# Inventory
# ---------------------------------------------------------------------------

def parse_inventory_full(reader: BlobReader, world_version: int):
    """Parse Inventory metadata, skip item data blocks."""
    s = OrderedDict()
    start = reader.pos

    s["_invType"] = _ro(reader.pos, "string", reader.read_string())
    s["explored"] = F(reader.pos, "byte", reader.get_byte())

    item_count = reader.get_short()
    s["_itemCount"] = _ro(0, "info", item_count)
    for _ in range(item_count):
        identical = reader.get_int()
        data_len = reader.get_int()
        reader.skip(data_len)
        if identical > 1:
            reader.skip((identical - 1) * 4)

    s["hasBeenLooted"] = F(reader.pos, "byte", reader.get_byte())
    s["capacity"] = F(reader.pos, "int", reader.get_int())

    vlog(f"             type=\"{s['_invType']['value']}\", {item_count} item stacks, capacity={s['capacity']['value']} ({reader.pos - start} bytes)")
    return s


# ---------------------------------------------------------------------------
# Stats
# ---------------------------------------------------------------------------

def parse_stats_full(reader: BlobReader, world_version: int):
    """Parse Stats (24 floats in order), return field dict."""
    s = OrderedDict()
    for name in STAT_NAMES:
        offset = reader.pos
        val = reader.get_float()
        s[name] = F(offset, "float", val)
        if is_verbose() and (name in DEATH_RELEVANT_STATS or val != 0.0):
            flag = " <--" if name in ("ZombieFever", "ZombieInfection") and val > 0 else ""
            vlog(f"  [0x{offset:04X}]   {name:22s} = {val:.4f}{flag}")
    return s


# ---------------------------------------------------------------------------
# Body Parts
# ---------------------------------------------------------------------------

def parse_body_part_full(reader: BlobReader, world_version: int, bp_idx: int):
    """Parse a single body part, return field dict with ALL fields."""
    s = OrderedDict()
    bp_start = reader.pos
    name = BODY_PART_NAMES[bp_idx] if bp_idx < len(BODY_PART_NAMES) else f"Part_{bp_idx}"

    s["cut"] = F(reader.pos, "byte", reader.get_byte())
    s["bitten"] = F(reader.pos, "byte", reader.get_byte())
    s["scratched"] = F(reader.pos, "byte", reader.get_byte())
    # Guard byte: controls presence of bandageLife (4 bytes). DO NOT toggle -
    # changing 1->0 or 0->1 would shift all subsequent offsets and corrupt the blob.
    s["_bandaged"] = _ro(reader.pos, "byte", reader.get_byte())
    s["bleeding"] = F(reader.pos, "byte", reader.get_byte())
    s["deepWounded"] = F(reader.pos, "byte", reader.get_byte())
    s["fakeInfected"] = F(reader.pos, "byte", reader.get_byte())
    s["infected"] = F(reader.pos, "byte", reader.get_byte())

    s["health"] = F(reader.pos, "float", reader.get_float())

    is_bandaged = s["_bandaged"]["value"]
    if is_bandaged:
        s["bandageLife"] = F(reader.pos, "float", reader.get_float())

    # Guard byte: controls presence of woundInfectionLevel (4 bytes). DO NOT toggle.
    s["_infectedWound"] = _ro(reader.pos, "byte", reader.get_byte())
    if s["_infectedWound"]["value"]:
        s["woundInfectionLevel"] = F(reader.pos, "float", reader.get_float())

    s["cutTime"] = F(reader.pos, "float", reader.get_float())
    s["biteTime"] = F(reader.pos, "float", reader.get_float())
    s["scratchTime"] = F(reader.pos, "float", reader.get_float())
    s["bleedingTime"] = F(reader.pos, "float", reader.get_float())
    s["alcoholLevel"] = F(reader.pos, "float", reader.get_float())
    s["additionalPain"] = F(reader.pos, "float", reader.get_float())
    s["deepWoundTime"] = F(reader.pos, "float", reader.get_float())
    s["haveGlass"] = F(reader.pos, "byte", reader.get_byte())
    s["getBandageXp"] = F(reader.pos, "byte", reader.get_byte())
    s["stitched"] = F(reader.pos, "byte", reader.get_byte())
    s["stitchTime"] = F(reader.pos, "float", reader.get_float())
    s["getStitchXp"] = F(reader.pos, "byte", reader.get_byte())
    s["getSplintXp"] = F(reader.pos, "byte", reader.get_byte())
    s["fractureTime"] = F(reader.pos, "float", reader.get_float())

    # Guard byte: controls presence of splintFactor (4 bytes). DO NOT toggle.
    s["_hasSplint"] = _ro(reader.pos, "byte", reader.get_byte())
    if s["_hasSplint"]["value"]:
        s["splintFactor"] = F(reader.pos, "float", reader.get_float())

    s["haveBullet"] = F(reader.pos, "byte", reader.get_byte())
    s["burnTime"] = F(reader.pos, "float", reader.get_float())
    s["needBurnWash"] = F(reader.pos, "byte", reader.get_byte())
    s["lastTimeBurnWash"] = F(reader.pos, "float", reader.get_float())
    s["_splintItem"] = _ro(reader.pos, "string", reader.read_string())
    s["_bandageType"] = _ro(reader.pos, "string", reader.read_string())
    s["comfreyTime"] = F(reader.pos, "float", reader.get_float())
    s["wetness"] = F(reader.pos, "float", reader.get_float())
    s["stiffness"] = F(reader.pos, "float", reader.get_float())

    if world_version >= 227:
        s["comfreyFactor"] = F(reader.pos, "float", reader.get_float())
        s["garlicFactor"] = F(reader.pos, "float", reader.get_float())
        s["plantainFactor"] = F(reader.pos, "float", reader.get_float())

    # Verbose logging
    health = s["health"]["value"]
    flags = []
    if s["cut"]["value"]: flags.append("CUT")
    if s["bitten"]["value"]: flags.append("BITTEN")
    if s["scratched"]["value"]: flags.append("SCRATCHED")
    if s["_bandaged"]["value"]: flags.append("bandaged")
    if s["bleeding"]["value"]: flags.append("BLEEDING")
    if s["deepWounded"]["value"]: flags.append("DEEP_WOUND")
    if s["fakeInfected"]["value"]: flags.append("fake_inf")
    if s["infected"]["value"]: flags.append("INFECTED")
    if s["_infectedWound"]["value"]: flags.append("inf_wound")
    if s["_hasSplint"]["value"]: flags.append("splint")

    flag_str = " ".join(flags) if flags else "ok"
    marker = " <-- LETHAL" if health <= 0.0 else (" <-- DAMAGED" if health < 100.0 else "")
    vlog(f"  [0x{bp_start:04X}] {name:15s}: hp={health:6.1f}  [{flag_str}]{marker}")

    return s


# ---------------------------------------------------------------------------
# BodyDamage main fields
# ---------------------------------------------------------------------------

def parse_body_damage_full(reader: BlobReader, world_version: int):
    """Parse BodyDamage.loadMainFields, return field dict."""
    s = OrderedDict()

    s["catchACold"] = F(reader.pos, "float", reader.get_float())
    s["hasACold"] = F(reader.pos, "byte", reader.get_byte())
    s["coldStrength"] = F(reader.pos, "float", reader.get_float())

    vlog_offset(reader, f"cold: catchACold={s['catchACold']['value']:.2f}, hasACold={s['hasACold']['value']}, strength={s['coldStrength']['value']:.2f}")

    if world_version >= 222:
        s["timeToSneezeOrCough"] = F(reader.pos, "int", reader.get_int())

    s["reduceFakeInfection"] = F(reader.pos, "byte", reader.get_byte())
    s["healthFromFoodTimer"] = F(reader.pos, "float", reader.get_float())
    s["painReduction"] = F(reader.pos, "float", reader.get_float())
    s["coldReduction"] = F(reader.pos, "float", reader.get_float())
    s["infectionTime"] = F(reader.pos, "float", reader.get_float())
    s["infectionMortalityDuration"] = F(reader.pos, "float", reader.get_float())
    s["coldDamageStage"] = F(reader.pos, "float", reader.get_float())

    inf_time = s["infectionTime"]["value"]
    inf_mort = s["infectionMortalityDuration"]["value"]
    marker_t = " <-- ACTIVE" if inf_time > 0 else ""
    marker_m = " <-- ACTIVE" if inf_mort > 0 else ""
    vlog(f"  [0x{s['infectionTime']['offset']:04X}]   infectionTime            = {inf_time:.4f}{marker_t}")
    vlog(f"  [0x{s['infectionMortalityDuration']['offset']:04X}]   infectionMortalityDur    = {inf_mort:.4f}{marker_m}")

    return s


# ---------------------------------------------------------------------------
# Thermoregulator
# ---------------------------------------------------------------------------

def parse_thermoregulator_full(reader: BlobReader, world_version: int):
    """Parse Thermoregulator, return field dict."""
    s = OrderedDict()
    start = reader.pos

    s["setPoint"] = F(reader.pos, "float", reader.get_float())
    s["metabolicRate"] = F(reader.pos, "float", reader.get_float())
    if world_version >= 243:
        s["metabolicRateReal"] = F(reader.pos, "float", reader.get_float())
    s["metabolicTarget"] = F(reader.pos, "float", reader.get_float())
    s["bodyHeatDelta"] = F(reader.pos, "float", reader.get_float())
    s["coreHeatDelta"] = F(reader.pos, "float", reader.get_float())
    s["thermalDamage"] = F(reader.pos, "float", reader.get_float())
    s["damageCounter"] = F(reader.pos, "float", reader.get_float())
    if world_version >= 249:  # WorldVersion_ThermalDuration (42.21)
        s["thermalDuration"] = F(reader.pos, "float", reader.get_float())

    node_count = reader.get_int()
    nodes = OrderedDict()
    for i in range(node_count):
        n = OrderedDict()
        n["_bodyPartIndex"] = _ro(reader.pos, "int", reader.get_int())
        n["celsius"] = F(reader.pos, "float", reader.get_float())
        n["skinCelsius"] = F(reader.pos, "float", reader.get_float())
        n["heatDelta"] = F(reader.pos, "float", reader.get_float())
        n["primaryDelta"] = F(reader.pos, "float", reader.get_float())
        n["secondaryDelta"] = F(reader.pos, "float", reader.get_float())
        if world_version >= 241:
            n["insulation"] = F(reader.pos, "float", reader.get_float())
        if world_version >= 243:
            n["windresist"] = F(reader.pos, "float", reader.get_float())
            n["bodyWetness"] = F(reader.pos, "float", reader.get_float())
            n["clothingWetness"] = F(reader.pos, "float", reader.get_float())
        nodes[str(i)] = n
    s["_nodes"] = {"_NOTE": "Nested node data", "nodes": nodes}

    vlog(f"             {node_count} thermal nodes ({reader.pos - start} bytes)")
    return s


# ---------------------------------------------------------------------------
# XP / Perks
# ---------------------------------------------------------------------------

def parse_xp_full(reader: BlobReader, world_version: int):
    """Parse XP/Perk system, return field dict."""
    s = OrderedDict()
    start = reader.pos

    trait_count = reader.get_int()
    traits = []
    for _ in range(trait_count):
        traits.append(reader.read_string())
    s["_traits"] = _ro(0, "list", traits)
    vlog(f"             traits({trait_count}): {', '.join(traits[:8])}{'...' if trait_count > 8 else ''}")

    s["totalXp"] = F(reader.pos, "float", reader.get_float())
    s["level"] = F(reader.pos, "int", reader.get_int())
    s["lastLevel"] = F(reader.pos, "int", reader.get_int())
    vlog(f"             totalXp={s['totalXp']['value']:.0f}, level={s['level']['value']}, lastLevel={s['lastLevel']['value']}")

    xp_map_size = reader.get_int()
    xp_map = OrderedDict()
    for _ in range(xp_map_size):
        pname = reader.read_string()
        xp_map[pname] = F(reader.pos, "float", reader.get_float())
    s["xpMap"] = xp_map

    perk_list_size = reader.get_int()
    perks = OrderedDict()
    for _ in range(perk_list_size):
        pname = reader.read_string()
        perks[pname] = F(reader.pos, "int", reader.get_int())
    s["perks"] = perks

    if is_verbose():
        leveled = [f"{k}={v['value']}" for k, v in perks.items() if v['value'] > 0]
        vlog(f"             perks({perk_list_size}): {', '.join(leveled[:10])}{'...' if len(leveled) > 10 else ''}")

    xp_mult_size = reader.get_int()
    xp_mults = []
    for _ in range(xp_mult_size):
        mname = reader.read_string()
        mval = reader.get_float()
        mmin = reader.get_byte()
        mmax = reader.get_byte()
        xp_mults.append({"name": mname, "value": mval, "minLevel": mmin, "maxLevel": mmax})
    s["_xpMultipliers"] = _ro(0, "list", xp_mults)

    vlog(f"             ({reader.pos - start} bytes total)")
    return s


# ---------------------------------------------------------------------------
# Fitness
# ---------------------------------------------------------------------------

def parse_fitness_full(reader: BlobReader, world_version: int):
    """Parse Fitness data (read-only)."""
    s = OrderedDict()
    start = reader.pos

    # 5 maps with varying value types
    map1_size = reader.get_int()
    m1 = {}
    for _ in range(map1_size):
        k = reader.read_string()
        m1[k] = reader.get_float()
    s["_fitnessMap1"] = _ro(0, "map", m1)

    map2_size = reader.get_int()
    m2 = {}
    for _ in range(map2_size):
        k = reader.read_string()
        m2[k] = reader.get_int()
    s["_fitnessMap2"] = _ro(0, "map", m2)

    map3_size = reader.get_int()
    m3 = {}
    for _ in range(map3_size):
        k = reader.read_string()
        m3[k] = reader.get_float()
    s["_fitnessMap3"] = _ro(0, "map", m3)

    map4_size = reader.get_int()
    m4 = []
    for _ in range(map4_size):
        m4.append(reader.read_string())
    s["_fitnessMap4"] = _ro(0, "list", m4)

    map5_size = reader.get_int()
    m5 = {}
    for _ in range(map5_size):
        k = reader.read_string()
        m5[k] = reader.get_long()
    s["_fitnessMap5"] = _ro(0, "map", m5)

    vlog(f"             ({reader.pos - start} bytes)")
    return s


# ---------------------------------------------------------------------------
# Nutrition
# ---------------------------------------------------------------------------

def parse_nutrition_full(reader: BlobReader):
    """Parse Nutrition (5 floats), return field dict."""
    s = OrderedDict()
    s["calories"] = F(reader.pos, "float", reader.get_float())
    s["proteins"] = F(reader.pos, "float", reader.get_float())
    s["lipids"] = F(reader.pos, "float", reader.get_float())
    s["carbohydrates"] = F(reader.pos, "float", reader.get_float())
    s["weight"] = F(reader.pos, "float", reader.get_float())
    vlog(f"             cal={s['calories']['value']:.0f}, pro={s['proteins']['value']:.0f}, "
         f"lip={s['lipids']['value']:.0f}, carb={s['carbohydrates']['value']:.0f}, "
         f"weight={s['weight']['value']:.1f}")
    return s


# ---------------------------------------------------------------------------
# CraftHistory
# ---------------------------------------------------------------------------

def parse_craft_history_full(reader: BlobReader):
    """Parse CraftHistory (read-only)."""
    s = OrderedDict()
    start = reader.pos
    entry_count = reader.get_int()
    entries = []
    for _ in range(entry_count):
        key_len = reader.get_int()
        # Keys are stored as char arrays (2 bytes per char)
        key_bytes = reader.get_bytes(key_len * 2)
        key = key_bytes.decode('utf-16-be', errors='replace')
        count = reader.get_int()
        timestamp = reader.get_double()
        entries.append({"recipe": key, "count": count, "timestamp": timestamp})
    s["_entries"] = _ro(0, "list", entries)
    vlog(f"             {entry_count} entries ({reader.pos - start} bytes)")
    return s
