from pathlib import Path


class ImportDirsNotFoundError(FileNotFoundError):
    pass


def find_ghs_import_dirs(ghs_path):
    """automatically determine texdir, pm2dir, and mprdir from ghs_path

    mprdir can be None
    """
    ghs_path = Path(ghs_path)
    ghs_dir = ghs_path.parent

    # case 1: start in texdir, increment texdir to get a base dir then descend into 0
    #   for pm2 and 2 for mpr
    # case 2: start in a base dir, descend into 0 for tex, 1 for pm2, and 2 for mpr
    # case 3: start in a base dir, descend into 1 for tex and 2 for pm2 (no mpr)

    try:
        thisdirnum = int(ghs_dir.name[:3], 16)
    except ValueError:
        raise ImportDirsNotFoundError("ghs file needs to be in a numbered directory")

    # case 1: look for *.png in current dir, if so then we're inside texdir
    if list(ghs_dir.glob("*.png")):
        texdir = ghs_dir
        basedir = ghs_dir.parent / f"{thisdirnum + 1:03x}.sli.stm"
        pm2dir = basedir / "000.stm"
        mprdir = basedir / "002.stm"
        if not mprdir.is_dir or not list(mprdir.glob("*.mpr")):
            mprdir = None

    else:
        basedir = ghs_dir
        texdir = basedir / "000.tex"
        if texdir.is_dir() and list(texdir.glob("*.png")):
            # case 2
            pm2dir = basedir / "001.stm"
            mprdir = basedir / "002.stm"
            if not mprdir.is_dir or not list(mprdir.glob("*.mpr")):
                mprdir = None
        else:
            # case 3
            texdir = basedir / "001.sli.tex"
            pm2dir = basedir / "002.sli.stm"
            mprdir = None

    if not list(texdir.glob("*.png")) or not list(pm2dir.glob("*.pm2")):
        raise ImportDirsNotFoundError()
    if mprdir is not None and not list(mprdir.glob("*.mpr")):
        raise ImportDirsNotFoundError()

    return texdir, pm2dir, mprdir


def find_mappm2_tex_dir(mappm2_path):
    """automatically determine texdir from mappm2_path"""
    mappm2_path = Path(mappm2_path)
    mappm2_dir = mappm2_path.parent
    return mappm2_dir / "000.tex"
