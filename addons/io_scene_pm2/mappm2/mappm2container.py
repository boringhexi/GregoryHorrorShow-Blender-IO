"""
mappm2container.py

Parse the contents of a Gregory Horror Show .map-pm2 file, which contains room models.
"""
from io import SEEK_CUR, SEEK_END, BytesIO
from struct import unpack
from typing import BinaryIO


class MapPm2Container(list):
    @classmethod
    def from_file(cls, file: BinaryIO) -> "MapPm2Container":
        magic = file.read(3)
        file.seek(1, SEEK_CUR)
        if magic != b"MAP":
            # Check if it's the kind of .map-pm2 file that lacks the first 4 bytes
            if not quickcheck_mapx_file(file):
                raise ValueError(f"Not a valid MAP file (magic='{magic})'")
            file.seek(0)

        file.seek(4, SEEK_CUR)
        num1, num2 = unpack("<2H", file.read(4))
        file.seek(4, SEEK_CUR)
        num_offsets = num1 * num2
        offsets_raw = unpack(f"<{num_offsets}I", file.read(num_offsets * 4))
        offsets = [o for o in offsets_raw if o > 0]
        offsets.sort()
        filesizes = [o2 - o1 for o1, o2 in zip(offsets, offsets[1:])]
        filesizes.append(-1)  # last content file extends to the end of the MAP file
        contentfiles = []
        for offset, size in zip(offsets, filesizes):
            file.seek(offset)
            data = file.read(size)
            if not data:  # fixes a special case with JP 09f.sli.stm/001.map-pm2
                continue
            contentfiles.append(BytesIO(data))
        return cls(contentfiles)


def quickcheck_mapx_file(file: BinaryIO) -> bool:
    """Check if file is the kind of .map-pm2 file that lacks the first 4 bytes

    :param file: file to check
    :return: True if file is that kind of .map-pm2 file, False otherwise
    """
    file.seek(0, SEEK_END)
    mapxfilesize = file.tell()
    file.seek(0)

    filesize_data = file.read(4)
    if len(filesize_data) < 4:
        return False
    filesize = unpack("<I", filesize_data)[0]
    if filesize != mapxfilesize:
        return False
    nums_data = file.read(4)
    if len(nums_data) < 4:
        return False
    num1, num2 = unpack("<2H", nums_data)
    num_offsets = num1 * num2
    offsets_data = file.read(num_offsets * 4)
    if len(offsets_data) < num_offsets * 4:
        return False
    offsets_raw = unpack(f"<{num_offsets}I", offsets_data)
    offsets = [o for o in offsets_raw if o > 0]
    if not offsets:
        return False
    for offset in offsets:
        file.seek(offset)
        magic = file.read(3)
        if magic != b"PM2":
            return False
    return True
