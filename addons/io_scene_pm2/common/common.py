from struct import pack, unpack
from typing import BinaryIO, Optional, Union


def read_unless_eof(file: BinaryIO, num: int) -> bytes:
    """read and return num bytes from file, unless end of file is encountered first

    :param num: number of bytes to attempt to read
    :raises: EOFError if end of file is encountered before end of reading
    :return: num bytes from file
    """
    readbytes = file.read(num)
    if len(readbytes) < num:
        raise EOFError("Unexpected end of file")
    return readbytes


def read_sint16(
    file: BinaryIO, num: Optional[int] = None
) -> Union[int, tuple[int, ...]]:
    """read and return a signed 16-bit integer (little-endian) from file

    :param num: if specified, read this many integers and return as a tuple
    :raises: EOFError if end of file is encountered before end of reading
    :return: an int or a tuple of ints
    """
    if num is None:
        return unpack("<h", read_unless_eof(file, 2))[0]
    else:
        fmt = f"<{num:d}h"
        return unpack(fmt, read_unless_eof(file, 2 * num))


def read_uint32(
    file: BinaryIO, num: Optional[int] = None
) -> Union[int, tuple[int, ...]]:
    """read and return an unsigned 32-bit integer (little-endian) from file

    :param num: if specified, read this many uin32s and return as a tuple
    :raises: EOFError if end of file is encountered before end of reading
    :return: a uint32 or a tuple of uint32s
    """
    if num is None:
        return unpack("<I", read_unless_eof(file, 4))[0]
    else:
        fmt = f"<{num:d}I"
        return unpack(fmt, read_unless_eof(file, 4 * num))


def read_sint32(
    file: BinaryIO, num: Optional[int] = None
) -> Union[int, tuple[int, ...]]:
    """read and return a signed 32-bit integer (little-endian) from file

    :param num: if specified, read this many sin32s and return as a tuple
    :raises: EOFError if end of file is encountered before end of reading
    :return: a sint32 or a tuple of sint32s
    """
    if num is None:
        return unpack("<i", read_unless_eof(file, 4))[0]
    else:
        fmt = f"<{num:d}i"
        return unpack(fmt, read_unless_eof(file, 4 * num))


def read_float32(
    file: BinaryIO, num: Optional[int] = None
) -> Union[float, tuple[float, ...]]:
    """read and return a 32-bit float (little-endian) from file

    :param num: if specified, read this many floats and return as a tuple
    :raises: EOFError if end of file is encountered before end of reading
    :return: a float or a tuple of floats
    """
    if num is None:
        return unpack("<f", read_unless_eof(file, 4))[0]
    else:
        fmt = f"<{num:d}f"
        return unpack(fmt, read_unless_eof(file, 4 * num))


def write_sint32(file: BinaryIO, *ints: int) -> int:
    """write ints to file as signed 32-bit integers (little-endian)

    :param ints: signed int or ints to write to file
    :return: number of bytes written to file
    """
    size = len(ints)
    fmt = f"<{size:d}i"
    ints_as_bytes = pack(fmt, *ints)
    file.write(ints_as_bytes)
    return len(ints_as_bytes)


def write_uint32(file: BinaryIO, *ints: int) -> int:
    """write ints to file as unsigned 32-bit integers (little-endian)

    :param ints: unsigned int or ints to write to file
    :return: number of bytes written to file
    """
    size = len(ints)
    fmt = f"<{size:d}I"
    ints_as_bytes = pack(fmt, *ints)
    file.write(ints_as_bytes)
    return len(ints_as_bytes)
