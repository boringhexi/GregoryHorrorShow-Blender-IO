import os.path

from .pm2.pm2model import Pm2Model
from .pm2.pm2importer import Pm2Importer


def load_pm2(
    context,
    *,
    filepath,
    files,
):
    dirname = os.path.dirname(filepath)
    for file in files:
        filepath = os.path.join(dirname, file.name)
        with open(filepath, "rb") as fp:
            pm2model = Pm2Model.from_file(fp)
            pm2importer = Pm2Importer(pm2model, bl_name=file.name)
            pm2importer.import_scene()
        del pm2model, pm2importer
    context.view_layer.update()


def load_with_profiler(context, **keywords):
    import cProfile
    import pstats

    pro = cProfile.Profile()
    pro.runctx("load_pm2(context, **keywords)", globals(), locals())
    st = pstats.Stats(pro)
    st.sort_stats("time")
    st.print_stats(0.1)
    st.print_callers(0.1)
    return {"FINISHED"}


def load(context, **keywords):
    # load_with_profiler(context, **keywords)
    load_pm2(context, **keywords)
    return {"FINISHED"}
