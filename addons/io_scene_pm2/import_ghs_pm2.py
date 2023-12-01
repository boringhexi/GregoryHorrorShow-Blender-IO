import os.path

from .ghs.findimportdirs import find_ghs_import_dirs, find_mappm2_tex_dir
from .ghs.ghsimporter import GhsImporter
from .mappm2.mappm2importer import MapPm2Importer
from .pm2.pm2importer import Pm2Importer
from .pm2.pm2model import Pm2Model


def load_ghs_pm2(
    context,
    *,
    filepath,
    files,
):
    dirname = os.path.dirname(filepath)
    for file in files:
        filepath = os.path.join(dirname, file.name)
        ext = os.path.splitext(file.name)[1]
        if ext == ".ghs":
            texdir, pm2dir, mprdir = find_ghs_import_dirs(filepath)
            bl_name = file.name
            ghsimporter = GhsImporter(
                filepath, pm2dir, mprdir, bl_name, anim_method="DRIVER"
            )
            ghsimporter.import_stuff()
        elif ext == ".map-pm2":
            texdir = find_mappm2_tex_dir(filepath)
            bl_name = file.name
            mappm2importer = MapPm2Importer(filepath, bl_name)
            mappm2importer.import_mappm2()
        elif ext == ".pm2":
            with open(filepath, "rb") as fp:
                pm2model = Pm2Model.from_file(fp)
                bl_name = os.path.splitext(file.name)[0]
                pm2importer = Pm2Importer(pm2model, bl_name=bl_name)
                pm2importer.import_scene()
                del pm2model, pm2importer
        else:
            pass
    context.view_layer.update()


def load_with_profiler(context, **keywords):
    import cProfile
    import pstats

    pro = cProfile.Profile()
    pro.runctx("load_ghs_pm2(context, **keywords)", globals(), locals())
    st = pstats.Stats(pro)
    st.sort_stats("time")
    st.print_stats(0.1)
    st.print_callers(0.1)
    return {"FINISHED"}


def load(context, **keywords):
    # load_with_profiler(context, **keywords)
    load_ghs_pm2(context, **keywords)
    return {"FINISHED"}
