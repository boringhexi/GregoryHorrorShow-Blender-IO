import os.path
from math import radians

from .common.findimportdirs import find_ghs_import_dirs, find_mappm2_tex_dir
from .common.material import import_materials
from .ghs.ghsimporter import GhsImporter
from .mappm2.mappm2importer import MapPm2Importer
from .pm2.pm2importer import Pm2Importer
from .pm2.pm2model import Pm2Model


def load_ghs_mappm2(context, *, filepath, files, ghs_anim_method="DRIVER"):
    dirname = os.path.dirname(filepath)
    for file in files:
        filepath = os.path.join(dirname, file.name)
        ext = os.path.splitext(file.name)[1]
        if ext == ".ghs":
            texdir, pm2dir, mprdir = find_ghs_import_dirs(filepath)
            bl_name = file.name
            ghsimporter = GhsImporter(
                filepath, pm2dir, mprdir, texdir, bl_name, anim_method=ghs_anim_method
            )
            ghsimporter.import_stuff()
        elif ext == ".map-pm2":
            texdir = find_mappm2_tex_dir(filepath)
            bl_name = file.name
            mappm2importer = MapPm2Importer(filepath, texdir, bl_name)
            mappm2importer.import_mappm2()
        elif ext == ".pm2":
            with open(filepath, "rb") as fp:
                pm2model = Pm2Model.from_file(fp)
                bl_name = os.path.splitext(file.name)[0]
                matsettings_materials = dict()
                pm2importer = Pm2Importer(
                    pm2model,
                    bl_name=bl_name,
                    matsettings_materials_to_reuse=matsettings_materials,
                )
                pm2importer.import_scene()
                import_materials(matsettings_materials, None)
                # also need to be rotated to correct axes
                pm2meshobj = pm2importer.bl_meshobj
                pm2meshobj.rotation_euler = (radians(90), radians(180), 0)
                del pm2model, pm2importer
        else:
            pass
    context.view_layer.update()


def load_with_profiler(context, **keywords):
    import cProfile
    import pstats

    pro = cProfile.Profile()
    pro.runctx("load_ghs_mappm2(context, **keywords)", globals(), locals())
    st = pstats.Stats(pro)
    st.sort_stats("time")
    st.print_stats(0.1)
    st.print_callers(0.1)
    return {"FINISHED"}


def load(context, **keywords):
    # load_with_profiler(context, **keywords)
    load_ghs_mappm2(context, **keywords)
    return {"FINISHED"}
