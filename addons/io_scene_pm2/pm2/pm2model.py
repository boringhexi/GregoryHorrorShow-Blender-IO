#!/usr/bin/env python3
"""
pm2model.py

Parse the contents of a Gregory Horror Show .pm2 model file.
"""
from io import BytesIO
from struct import unpack
from sys import argv
from typing import BinaryIO, List, Optional, Sequence, Tuple

from ..common.common import (
    read_float32,
    read_sint16,
    read_sint32,
    read_uint32,
    read_unless_eof,
    write_sint32,
    write_uint32,
)

PM2TYPES = {
    "FLOAT32": 0x12,
    "FLOAT32_ANIM": 0x13,
    "SINT32": 0x32,  # sint16s in the pm2 file that become sint32s in VU memory
    "SINT32_ANIM": 0x33,
}
PM2TYPES_ANIM = {
    "FLOAT32_ANIM": 0x13,
    "SINT32_ANIM": 0x33,
}
VIFCOMMANDS = {
    "NOP": 0x00,
    "STCYCL": 0x01,
    "MSCNT": 0x17,
    "UNPACK_V4_32": 0x6C,
    "UNPACK_V4_16": 0x6D,
}


class Prim:
    """
    A Prim is essentially a list of vertices.

    adjust_all_values: whenever a vertex is added to the prim, we want to normalize its
    values to a 0.0 - 1.0 or -1.0 - 1.0 range. When the vertex originates from a pm2
    file that uses float values, only color needs to be adjusted this way, in which
    case pass False for this parameter. However, when the vertex originates from
    signed integer values, all values need to be adjusted, in which case pass True.

    x.positions: a list of vertex positions

    x.normals: a list of vertex normals

    x.colors: a list of RGBA colors

    x.texcoords: a list of texture coordinates
    """

    _ADJ_POSITION = 1024
    _ADJ_NORMAL = 4096
    _ADJ_RGB = 256
    _ADJ_ALPHA = 128
    _ADJ_TEXCOORD = 4096

    def __init__(self, adjust_all_values: bool = False):
        self.positions: List[Tuple[float, float, float]] = []
        self.normals: List[Tuple[float, float, float]] = []
        self.colors: List[Tuple[float, float, float, float]] = []
        self.texcoords: List[Tuple[float, float]] = []
        self._adjust_all_values = adjust_all_values

    def add_vertex(
        self,
        position: Tuple[float, float, float],
        normal: Tuple[float, float, float],
        color: Tuple[float, float, float, float],
        texcoord: Tuple[float, float],
    ):
        """add a vertex to this Prim"""
        if self._adjust_all_values:
            position = tuple(p / self._ADJ_POSITION for p in position)
            normal = tuple(n / self._ADJ_NORMAL for n in normal)
            texcoord = tuple(t / self._ADJ_TEXCOORD for t in texcoord)
        r, g, b, a = color
        color = (
            r / self._ADJ_RGB,
            g / self._ADJ_RGB,
            b / self._ADJ_RGB,
            a / self._ADJ_ALPHA,
        )

        self.positions.append(position)
        self.normals.append(normal)
        self.colors.append(color)
        self.texcoords.append(texcoord)

    def __len__(self) -> int:
        return len(self.positions)


class AnimatedPrim(Prim):
    """
    The same as Prim, with the addition of:

    - x.position_animdeltas: add these to x.positions to get the next frame
    - x.normal_animdeltas: add these to x.normals to get the next frame
    """

    def __init__(self, adjust_all_values: bool = False):
        super().__init__(adjust_all_values=adjust_all_values)
        self.position_animdeltas: List[Tuple[float, float, float]] = []
        self.normal_animdeltas: List[Tuple[float, float, float]] = []

    def add_vertex(
        self,
        position: Tuple[float, float, float],
        normal: Tuple[float, float, float],
        color: Tuple[float, float, float, float],
        texcoord: Tuple[float, float],
        position_animdelta: Optional[Tuple[float, float, float]] = None,
        normal_animdelta: Optional[Tuple[float, float, float]] = None,
    ):
        super().add_vertex(position, normal, color, texcoord)
        if self._adjust_all_values:
            position_animdelta = tuple(
                p / self._ADJ_POSITION for p in position_animdelta
            )
            normal_animdelta = tuple(n / self._ADJ_NORMAL for n in normal_animdelta)
        self.position_animdeltas.append(position_animdelta)
        self.normal_animdeltas.append(normal_animdelta)


class PrimList(list[Prim]):
    """
    A PrimList is a list of Prims. (Thus far, each Prim appears to be a tristrip.)

    texture_offset: Gregory Horror Show textures contain a texture offset "hint" that
    is used to place the texture in memory. This PrimList's texture_offset is the same
    as that hint, so it can be used to determine which texture to apply.
    """

    def __init__(self, texture_offset: int):
        super().__init__()
        self.texture_offset = texture_offset


class Pm2Model:
    """
    A Pm2Model is a Gregory Horror Show model. It can be animated, in which case it is
    vertex animation between two frames.
    """

    def __init__(self, primlists: Sequence[PrimList], animated=False):
        self.primlists = primlists
        self.animated = animated

    @classmethod
    def from_file(cls, file: BinaryIO):
        """Initialize a Pm2Model instance from a file"""
        header_bytes = read_unless_eof(file, 0x10)
        (
            magic,
            pm2type,
            unknown1_ignored,
            filesize_ignored,
            numprimlists_ignored,
        ) = unpack("<3s1B3I", header_bytes)
        if not magic == b"PM2":
            raise ValueError(f"not a valid PM2 file, magic={magic!r}")
        if pm2type not in PM2TYPES.values():
            raise ValueError(f"unknown pm2type {hex(pm2type)}")
        animated = pm2type in PM2TYPES_ANIM.values()

        primlists: list[PrimList] = list()
        for x in range(numprimlists_ignored):
            # First we execute VIF unpack commands to transfer values from the file
            # to (simulated) VU memory...
            vu_memory = BytesIO()
            command = None
            while command != VIFCOMMANDS["MSCNT"]:
                command, num, immediate = _read_vif_command(file)
                if command in (
                    VIFCOMMANDS["NOP"],
                    VIFCOMMANDS["STCYCL"],
                    VIFCOMMANDS["MSCNT"],
                ):
                    continue
                elif command == VIFCOMMANDS["UNPACK_V4_32"]:
                    uint32s = read_uint32(file, num=num * 4)
                    write_uint32(vu_memory, *uint32s)
                elif command == VIFCOMMANDS["UNPACK_V4_16"]:
                    sint16s = read_sint16(file, num=num * 4)
                    write_sint32(vu_memory, *sint16s)
                else:
                    raise ValueError(f"Unknown VIF command {hex(command)}")

            # ...And then we parse the current contents of VU memory to get a PrimList.
            vu_memory.seek(0)
            (texture_offset,) = _read_primlist_header(vu_memory)
            primlist = PrimList(texture_offset=texture_offset)
            if pm2type in (PM2TYPES["SINT32"], PM2TYPES["SINT32_ANIM"]):
                datatype = "sint32"
            else:  # "FLOAT32" / "FLOAT32_ANIM"
                datatype = "float32"
            is_last_prim = False
            while not is_last_prim:
                numverts, is_last_prim = _read_prim_header(vu_memory)
                prim = _read_prim(vu_memory, numverts, datatype, animated=animated)
                primlist.append(prim)
            primlists.append(primlist)

        return cls(primlists, animated=animated)


def _read_vif_command(file: BinaryIO) -> Tuple[int, int, int]:
    """read and return a VIF command from file

    :return: tuple of (command, num, immediate)
    """
    immediate, num, command = unpack("<HBB", read_unless_eof(file, 4))
    return command, num, immediate


def _read_primlist_header(file: BinaryIO):
    """read and return a PrimList header from file

    :return: tuple (texture_offset,)
    """
    return unpack("4x4x4x4x1H2x4x4x4x", read_unless_eof(file, 0x20))


def _read_prim_header(file: BinaryIO):
    """read and return a Prim header from file

    :return: tuple (numverts, is_last_prim)
    """
    numverts_and_flag = unpack("1I4x4x4x", read_unless_eof(file, 0x10))[0]
    numverts = numverts_and_flag & 0x7FFF
    is_last_prim = numverts_and_flag & 0x8000
    return numverts, is_last_prim


def _read_prim(file: BinaryIO, numverts, datatype, animated=False):
    """read and return a Prim from file

    :param numverts: number of vertices in the Prim
    :param datatype: data types to read from file, "sint32" or "float32"
    :param animated: if True, read and return an AnimatedPrim
    :return: Prim or AnimatedPrim instance
    """
    if datatype == "sint32":
        read_vals = read_sint32
        adjust_all_values = True
    elif datatype == "float32":
        read_vals = read_float32
        adjust_all_values = False
    else:
        raise ValueError(f"Was provided invalid datatype {datatype!r}")
    if animated:
        prim = AnimatedPrim(adjust_all_values=adjust_all_values)
    else:
        prim = Prim(adjust_all_values=adjust_all_values)
    for _ in range(numverts):
        if animated:
            vals = read_vals(file, num=24)
            posx, posy, posz, posunk = vals[0:4]
            normx, normy, normz, normunk = vals[4:8]
            posx2, posy2, posz2, posunk2 = vals[8:12]
            normx2, normy2, normz2, normunk2 = vals[12:16]
            r, g, b, a = vals[16:20]
            s, t, texunk1, texunk2 = vals[20:24]
            prim.add_vertex(
                (posx, posy, posz),
                (normx, normy, normz),
                (r, g, b, a),
                (s, t),
                position_animdelta=(posx2, posy2, posz2),
                normal_animdelta=(normx2, normy2, normz2),
            )
        else:
            vals = read_vals(file, num=16)
            posx, posy, posz, pozunk = vals[0:4]
            normx, normy, normz, normunk = vals[4:8]
            r, g, b, a = vals[8:12]
            s, t, texunk1, texunk2 = vals[12:16]
            prim.add_vertex(
                (posx, posy, posz),
                (normx, normy, normz),
                (r, g, b, a),
                (s, t),
            )
    return prim


def main(args=tuple(argv[1:])):
    if not args:
        print("Parse a Gregory Horror Show .pm2 model file.")
        print(f"{argv[0]} PM2FILE, [PM2FILE, ...]")
        return
    for path in args:
        print(path)
        with open(path, "rb") as file:
            Pm2Model.from_file(file)
            print("  Success!")


if __name__ == "__main__":
    main()
