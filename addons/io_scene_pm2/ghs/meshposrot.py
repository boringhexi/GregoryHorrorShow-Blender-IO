import math
from collections import defaultdict
from struct import unpack
from typing import BinaryIO

from ..common import read_float32, read_sint16, read_uint32, read_unless_eof


def mpr_from_file(file: BinaryIO):
    num_bones = read_uint32(file)
    offsets = read_uint32(file, num=num_bones)
    mpr = defaultdict(lambda: defaultdict(list))
    for offset in offsets:
        file.seek(offset)
        num_frames, which_bone, is_floats = unpack("<HBB", read_unless_eof(file, 4))
        for x in range(num_frames):
            if is_floats:
                pos = read_float32(file, num=3)
                rot = read_float32(file, num=3)
            else:
                pos = read_sint16(file, num=3)
                pos = [p / 4096 for p in pos]
                rot = read_sint16(file, num=3)
                rot = [math.radians(r / 0x6400 * 360) for r in rot]
            x, y, z = rot
            rot = (y, x, z)  # TODO messy, as this also gets reordered by Blender as ZXY

            mpr[which_bone]["pos"].append(pos)
            mpr[which_bone]["rot"].append(rot)

    return mpr


# mpr_sample = { 0: {"pos": [(1, 2, 3)], "rot": [(1, 2, 3)]} }
