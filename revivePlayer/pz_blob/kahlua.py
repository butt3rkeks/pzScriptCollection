"""KahluaTable (Lua modData) parsing and display.

Disk save format (KahluaTableImpl):
    int entryCount
    per entry: byte keyType + keyData, byte valueType + valueData
    Type markers: 0=STRING, 1=DOUBLE, 2=TABLE, 3=BOOLEAN
"""

from collections import OrderedDict

from .reader import BlobReader
from .log import vlog


def read_lua_table(reader: BlobReader, depth: int = 0):
    """Read a KahluaTable serialized in the blob (KahluaTableImpl disk format).

    Returns the table as a Python dict (with string/float/bool keys and values,
    nested dicts for sub-tables).
    """
    entry_count = reader.get_int()
    result = {}
    for i in range(entry_count):
        key = _read_table_value(reader, depth)
        val = _read_table_value(reader, depth)
        result[key] = val
    return result


def _read_table_value(reader: BlobReader, depth: int = 0):
    """Read a single key or value in a KahluaTableImpl disk save."""
    type_byte = reader.get_byte()
    if type_byte == 0:    # STRING
        return reader.read_string()
    elif type_byte == 1:  # DOUBLE
        val = reader.get_double()
        return val
    elif type_byte == 2:  # TABLE (nested)
        return read_lua_table(reader, depth + 1)
    elif type_byte == 3:  # BOOLEAN
        return reader.get_byte() == 1
    else:
        raise ValueError(f"Unknown KahluaTable type {type_byte} at offset 0x{reader.pos - 1:04X}. "
                         f"Expected 0=STRING, 1=DOUBLE, 2=TABLE, 3=BOOLEAN.")


def print_table_tree(table: dict, indent: int = 0, max_depth: int = 5):
    """Pretty-print a nested table dict as a readable tree."""
    if max_depth <= 0:
        vlog(f"{' ' * indent}...")
        return
    for key, val in table.items():
        prefix = " " * indent
        if isinstance(val, dict):
            vlog(f"{prefix}{key!r}: ({len(val)} entries)")
            print_table_tree(val, indent + 2, max_depth - 1)
        elif isinstance(val, float):
            if val == int(val) and abs(val) < 1e15:
                vlog(f"{prefix}{key!r} = {int(val)}")
            else:
                vlog(f"{prefix}{key!r} = {val}")
        else:
            vlog(f"{prefix}{key!r} = {val!r}")


def make_json_safe_table(table):
    """Convert a Lua table dict to JSON-safe format (all keys must be strings)."""
    result = OrderedDict()
    for key, val in table.items():
        str_key = str(key)
        if isinstance(val, dict):
            result[str_key] = make_json_safe_table(val)
        else:
            result[str_key] = val
    return result
