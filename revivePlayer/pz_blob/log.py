"""Logging helpers and field entry factories."""

from collections import OrderedDict

# ---------------------------------------------------------------------------
# Verbose logging
# ---------------------------------------------------------------------------

_verbose = False


def set_verbose(enabled: bool):
    """Enable or disable verbose logging."""
    global _verbose
    _verbose = enabled


def is_verbose() -> bool:
    return _verbose


def vlog(msg: str):
    """Print only when verbose mode is enabled."""
    if _verbose:
        print(msg)


def vlog_offset(reader, msg: str):
    """Print with hex offset prefix when verbose."""
    if _verbose:
        print(f"  [0x{reader.pos:04X}] {msg}")


def vlog_section(reader, title: str):
    """Print a section header with offset."""
    if _verbose:
        print(f"\n  [0x{reader.pos:04X}] === {title} ===")


# ---------------------------------------------------------------------------
# Field entry helpers for JSON edit mode
# ---------------------------------------------------------------------------

def F(offset, dtype, value, editable=True):
    """Create a field entry dict."""
    return {"offset": offset, "type": dtype, "value": value, "editable": editable}


def _ro(offset, dtype, value):
    """Create a read-only field entry."""
    return {"offset": offset, "type": dtype, "value": value, "editable": False}
