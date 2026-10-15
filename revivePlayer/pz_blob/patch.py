"""Revive patches and diagnostic report for the legacy PatchInfo workflow."""

import struct

from .reader import BlobReader
from .blob import PatchInfo
from .constants import BODY_PART_NAMES, NUM_BODY_PARTS, STAT_NAMES, DEATH_RELEVANT_STATS, DAMAGE_MODIFIERS


# ---------------------------------------------------------------------------
# Diagnostic report
# ---------------------------------------------------------------------------

def print_verify_report(patch: PatchInfo):
    """Print a diagnostic report of all death-relevant fields."""
    print("\n" + "=" * 65)
    print("  PLAYER DIAGNOSTIC REPORT")
    print("=" * 65)

    if patch.player_name:
        print(f"  Name:            {patch.player_name}")
    if patch.player_pos:
        print(f"  Position:        ({patch.player_pos[0]:.0f}, {patch.player_pos[1]:.0f}, {patch.player_pos[2]:.0f})")
    print(f"  Hours survived:  {patch.hours_survived:.1f}")

    # Overall health estimate
    total_damage = 0.0
    for bp in patch.body_parts:
        idx = bp["index"]
        if idx < len(DAMAGE_MODIFIERS):
            total_damage += (100.0 - bp["health"]) * DAMAGE_MODIFIERS[idx]
    overall = max(0.0, 100.0 - min(total_damage, 100.0))
    status = "DEAD" if overall <= 0.0 else ("CRITICAL" if overall < 20.0 else "ALIVE")
    print(f"\n  Overall HP:      {overall:.1f} / 100.0  [{status}]")

    # Body parts
    print(f"\n  --- Body Parts ({NUM_BODY_PARTS}) ---")
    print(f"  {'Part':<15s}  {'HP':>6s}  {'Status'}")
    print(f"  {'-'*15}  {'-'*6}  {'-'*30}")
    for bp in patch.body_parts:
        idx = bp["index"]
        name = BODY_PART_NAMES[idx] if idx < len(BODY_PART_NAMES) else f"Part_{idx}"
        health = bp["health"]
        hp_str = f"{health:6.1f}"
        marker = " ** LETHAL **" if health <= 0.0 else (" * damaged *" if health < 100.0 else "")
        print(f"  {name:<15s}  {hp_str}  {marker}")

    # Infection
    print(f"\n  --- Infection ---")
    inf_t = patch.infection_time_value
    inf_m = patch.infection_mortality_duration_value
    print(f"  infectionTime:              {inf_t:>10.4f}  {'<-- ACTIVE' if inf_t and inf_t > 0 else '(none)'}")
    print(f"  infectionMortalityDuration: {inf_m:>10.4f}  {'<-- ACTIVE' if inf_m and inf_m > 0 else '(none)'}")

    # Stats
    print(f"\n  --- Death-Relevant Stats ---")
    for name in STAT_NAMES:
        if name in DEATH_RELEVANT_STATS or patch.stats_values.get(name, 0.0) != 0.0:
            val = patch.stats_values.get(name, 0.0)
            marker = ""
            if name == "ZombieInfection" and val > 0: marker = " <-- LETHAL"
            elif name == "ZombieFever" and val > 0: marker = " <-- ACTIVE"
            elif name == "Pain" and val > 50: marker = " <-- HIGH"
            elif name == "Sickness" and val > 0: marker = " <-- SICK"
            print(f"  {name:24s} = {val:>8.4f}{marker}")

    # Death flags
    print(f"\n  --- Death Flags ---")
    dd = patch.death_drag_down_value
    print(f"  deathDragDown:              {'YES' if dd else 'no'}{'  <-- DEATH FLAG' if dd else ''}")

    # Verdict
    print(f"\n  --- Verdict ---")
    problems = []
    if overall <= 0.0:
        problems.append("overallBodyHealth <= 0 (body part damage)")
    if inf_t is not None and inf_t > 0:
        problems.append(f"active zombie infection (time={inf_t:.1f})")
    zi = patch.stats_values.get("ZombieInfection", 0.0)
    if zi > 0:
        problems.append(f"ZombieInfection stat = {zi:.1f}")
    zf = patch.stats_values.get("ZombieFever", 0.0)
    if zf > 0:
        problems.append(f"ZombieFever stat = {zf:.1f}")
    if dd:
        problems.append("deathDragDown flag set")

    if problems:
        print(f"  Player appears DEAD. Causes:")
        for p in problems:
            print(f"    - {p}")
    else:
        print(f"  Player appears ALIVE - no death indicators found.")

    print("=" * 65)


# ---------------------------------------------------------------------------
# Apply revival patches
# ---------------------------------------------------------------------------

def apply_patches(reader: BlobReader, patch: PatchInfo, dry_run: bool = False):
    """Apply revival patches. If dry_run, only report what would change."""
    changes = 0
    prefix = "[DRY-RUN] " if dry_run else ""

    # 1. Heal all body parts to 100 HP
    for bp in patch.body_parts:
        idx = bp["index"]
        name = BODY_PART_NAMES[idx] if idx < len(BODY_PART_NAMES) else f"Part_{idx}"
        old_health = bp["health"]
        if old_health < 100.0:
            if not dry_run:
                reader.put_float_at(bp["health_offset"], 100.0)
            print(f"  {prefix}{name:15s}: health {old_health:.1f} -> 100.0")
            changes += 1

        for field, label in [("bitten_offset", "bitten"), ("scratched_offset", "scratched"),
                              ("cut_offset", "cut"), ("bleeding_offset", "bleeding"),
                              ("deep_wounded_offset", "deep wound"),
                              ("infected_offset", "zombie infection"),
                              ("fake_infected_offset", "fake infection")]:
            if reader.data[bp[field]]:
                if not dry_run:
                    reader.put_byte_at(bp[field], 0)
                print(f"  {prefix}{name:15s}: cleared {label}")
                changes += 1

    # 2. Clear infection timing
    if patch.infection_time_offset is not None:
        old_val = struct.unpack_from('>f', reader.data, patch.infection_time_offset)[0]
        if old_val != -1.0:
            if not dry_run:
                reader.put_float_at(patch.infection_time_offset, -1.0)
            print(f"  {prefix}infectionTime: {old_val} -> -1.0")
            changes += 1

    if patch.infection_mortality_duration_offset is not None:
        old_val = struct.unpack_from('>f', reader.data, patch.infection_mortality_duration_offset)[0]
        if old_val != -1.0:
            if not dry_run:
                reader.put_float_at(patch.infection_mortality_duration_offset, -1.0)
            print(f"  {prefix}infectionMortalityDuration: {old_val} -> -1.0")
            changes += 1

    # 3. Clear ZombieFever and ZombieInfection stats
    for stat_name in ["ZombieFever", "ZombieInfection"]:
        if stat_name in patch.stats_offsets:
            offset = patch.stats_offsets[stat_name]
            old_val = struct.unpack_from('>f', reader.data, offset)[0]
            if old_val > 0.0:
                if not dry_run:
                    reader.put_float_at(offset, 0.0)
                print(f"  {prefix}Stat {stat_name}: {old_val} -> 0.0")
                changes += 1

    # 4. Clear pain, sickness, poison stats
    for stat_name in ["Pain", "Sickness", "Poison", "FoodSickness"]:
        if stat_name in patch.stats_offsets:
            offset = patch.stats_offsets[stat_name]
            old_val = struct.unpack_from('>f', reader.data, offset)[0]
            if old_val > 0.0:
                if not dry_run:
                    reader.put_float_at(offset, 0.0)
                print(f"  {prefix}Stat {stat_name}: {old_val} -> 0.0")
                changes += 1

    # 5. Reset endurance
    if "Endurance" in patch.stats_offsets:
        offset = patch.stats_offsets["Endurance"]
        old_val = struct.unpack_from('>f', reader.data, offset)[0]
        if old_val < 1.0:
            if not dry_run:
                reader.put_float_at(offset, 1.0)
            print(f"  {prefix}Stat Endurance: {old_val} -> 1.0")
            changes += 1

    # 6. Clear deathDragDown
    if patch.death_drag_down_offset is not None:
        if reader.data[patch.death_drag_down_offset]:
            if not dry_run:
                reader.put_byte_at(patch.death_drag_down_offset, 0)
            print(f"  {prefix}deathDragDown: cleared")
            changes += 1

    action = "would be made" if dry_run else "applied"
    print(f"\n  Total changes {action}: {changes}")
    return changes
