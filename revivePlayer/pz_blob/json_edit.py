"""JSON export/import for the blob edit workflow.

Handles converting parsed sections to JSON-serializable structures,
and applying edits from modified JSON back to the binary blob.
"""

import json
import struct
from collections import OrderedDict

from .reader import BlobReader


# ---------------------------------------------------------------------------
# JSON encoder
# ---------------------------------------------------------------------------

class BlobJSONEncoder(json.JSONEncoder):
    """Custom encoder that handles field entry dicts and special values."""

    def default(self, obj):
        if isinstance(obj, (bytes, bytearray)):
            return list(obj)
        return super().default(obj)


# ---------------------------------------------------------------------------
# Export helpers
# ---------------------------------------------------------------------------

def _format_field_for_json(field):
    """Convert a field entry for JSON output: offset as hex string."""
    if not isinstance(field, dict) or "offset" not in field:
        return field
    out = OrderedDict()
    out["offset"] = f"0x{field['offset']:04X}"
    out["type"] = field["type"]
    out["value"] = field["value"]
    out["editable"] = field["editable"]
    return out


def _format_section_for_json(section):
    """Recursively format a section dict for JSON output."""
    if not isinstance(section, dict):
        return section
    out = OrderedDict()
    for key, val in section.items():
        if isinstance(val, dict):
            if "offset" in val and "type" in val and "value" in val:
                # It's a field entry
                out[key] = _format_field_for_json(val)
            elif "_NOTE" in val or "nodes" in val:
                # Special nested section (thermoregulator nodes, etc.)
                out[key] = _format_nested_for_json(val)
            else:
                # Nested section (BodyParts.<name>, XP.perks, XP.xpMap, etc.)
                out[key] = _format_section_for_json(val)
        else:
            out[key] = val
    return out


def _format_nested_for_json(section):
    """Format special nested structures."""
    if not isinstance(section, dict):
        return section
    out = OrderedDict()
    for key, val in section.items():
        if isinstance(val, dict):
            if "offset" in val and "type" in val:
                out[key] = _format_field_for_json(val)
            else:
                out[key] = _format_nested_for_json(val)
        else:
            out[key] = val
    return out


def export_sections_to_json(sections: dict, meta: dict) -> dict:
    """Convert sections dict to JSON-serializable structure."""
    output = OrderedDict()
    output["_meta"] = meta
    for section_name, section_data in sections.items():
        output[section_name] = _format_section_for_json(section_data)
    return output


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

def _parse_hex_offset(val):
    """Parse a hex offset string like '0x06D1' to int."""
    if isinstance(val, str) and val.startswith("0x"):
        return int(val, 16)
    return int(val)


def _collect_editable_fields(sections: dict) -> list:
    """Flatten sections into a list of (path, field_entry) for all editable fields."""
    result = []
    _collect_fields_recursive(sections, [], result)
    return result


def _collect_fields_recursive(obj, path, result):
    """Recursively walk sections and collect field entries."""
    if not isinstance(obj, dict):
        return
    if "offset" in obj and "type" in obj and "value" in obj:
        # This is a field entry
        if obj.get("editable", False):
            result.append((list(path), obj))
        return
    for key, val in obj.items():
        if key.startswith("_") and key != "_nodes":
            continue  # Skip read-only fields
        if isinstance(val, dict):
            _collect_fields_recursive(val, path + [key], result)


def _collect_json_edits(json_data: dict) -> dict:
    """Flatten edited JSON into {hex_offset_str: {"type": ..., "value": ...}}."""
    result = {}
    _collect_json_recursive(json_data, result)
    return result


def _collect_json_recursive(obj, result):
    """Recursively walk JSON and collect editable field values keyed by offset."""
    if not isinstance(obj, dict):
        return
    if "offset" in obj and "type" in obj and "value" in obj:
        if obj.get("editable", False):
            offset_str = obj["offset"]
            result[offset_str] = {"type": obj["type"], "value": obj["value"]}
        return
    for key, val in obj.items():
        if key == "_meta":
            continue
        if isinstance(val, dict):
            _collect_json_recursive(val, result)


def _values_equal(dtype, old_val, new_val):
    """Compare two values, handling float precision."""
    if dtype in ("float", "double"):
        # Compare via struct packing to avoid float precision issues
        fmt = '>f' if dtype == "float" else '>d'
        try:
            old_packed = struct.pack(fmt, float(old_val))
            new_packed = struct.pack(fmt, float(new_val))
            return old_packed == new_packed
        except (ValueError, struct.error):
            return False
    return old_val == new_val


def write_field(reader: BlobReader, offset: int, dtype: str, value):
    """Write a value at the given offset, dispatching by type."""
    if dtype == "float":
        reader.put_float_at(offset, float(value))
    elif dtype == "double":
        reader.put_double_at(offset, float(value))
    elif dtype == "int":
        reader.put_int_at(offset, int(value))
    elif dtype == "byte":
        reader.put_byte_at(offset, int(value))
    elif dtype == "short":
        reader.put_short_at(offset, int(value))
    elif dtype == "long":
        reader.put_long_at(offset, int(value))
    else:
        raise ValueError(f"Cannot write type '{dtype}' at offset 0x{offset:04X}")


def apply_json_edits(reader: BlobReader, sections: dict, edited_json: dict):
    """Compare edited JSON against parsed sections, apply changes.

    Returns number of changes applied.
    """
    # Collect original editable fields
    orig_fields = _collect_editable_fields(sections)
    # Build map from offset -> original field
    orig_by_offset = {}
    for path, field in orig_fields:
        offset_str = f"0x{field['offset']:04X}"
        orig_by_offset[offset_str] = (path, field)

    # Collect edits from JSON
    json_edits = _collect_json_edits(edited_json)

    changes = 0
    for offset_str, edit in sorted(json_edits.items()):
        if offset_str not in orig_by_offset:
            continue
        path, orig_field = orig_by_offset[offset_str]
        dtype = orig_field["type"]
        old_val = orig_field["value"]
        new_val = edit["value"]

        if _values_equal(dtype, old_val, new_val):
            continue

        offset = _parse_hex_offset(offset_str)
        path_str = ".".join(path)
        try:
            write_field(reader, offset, dtype, new_val)
            print(f"  {path_str}: {old_val} -> {new_val}")
            changes += 1
        except (ValueError, struct.error) as e:
            print(f"  WARNING: Failed to write {path_str}: {e}")

    return changes
