"""Binary reader/writer for big-endian Java ByteBuffer blobs."""

import struct


class BlobReader:
    """Reads and patches a ByteBuffer-style big-endian binary blob."""

    def __init__(self, data: bytes):
        self.data = bytearray(data)
        self.pos = 0

    def remaining(self):
        return len(self.data) - self.pos

    # --- Read methods ---

    def get_byte(self) -> int:
        val = self.data[self.pos]
        self.pos += 1
        return val

    def get_signed_byte(self) -> int:
        val = struct.unpack_from('>b', self.data, self.pos)[0]
        self.pos += 1
        return val

    def get_short(self) -> int:
        val = struct.unpack_from('>h', self.data, self.pos)[0]
        self.pos += 2
        return val

    def get_unsigned_short(self) -> int:
        val = struct.unpack_from('>H', self.data, self.pos)[0]
        self.pos += 2
        return val

    def get_int(self) -> int:
        val = struct.unpack_from('>i', self.data, self.pos)[0]
        self.pos += 4
        return val

    def get_long(self) -> int:
        val = struct.unpack_from('>q', self.data, self.pos)[0]
        self.pos += 8
        return val

    def get_float(self) -> float:
        val = struct.unpack_from('>f', self.data, self.pos)[0]
        self.pos += 4
        return val

    def get_double(self) -> float:
        val = struct.unpack_from('>d', self.data, self.pos)[0]
        self.pos += 8
        return val

    def get_bytes(self, n: int) -> bytes:
        val = self.data[self.pos:self.pos + n]
        self.pos += n
        return bytes(val)

    def read_string(self) -> str:
        """Read a PZ UTF-8 string: short length + UTF-8 bytes."""
        num_bytes = self.get_short()
        if num_bytes <= 0:
            return ""
        raw = self.get_bytes(num_bytes)
        return raw.decode('utf-8', errors='replace')

    def skip(self, n: int):
        self.pos += n

    # --- Write methods (in-place patching) ---

    def put_byte_at(self, offset: int, val: int):
        self.data[offset] = val & 0xFF

    def put_short_at(self, offset: int, val: int):
        struct.pack_into('>h', self.data, offset, val)

    def put_float_at(self, offset: int, val: float):
        struct.pack_into('>f', self.data, offset, val)

    def put_int_at(self, offset: int, val: int):
        struct.pack_into('>i', self.data, offset, val)

    def put_double_at(self, offset: int, val: float):
        struct.pack_into('>d', self.data, offset, val)

    def put_long_at(self, offset: int, val: int):
        struct.pack_into('>q', self.data, offset, val)
