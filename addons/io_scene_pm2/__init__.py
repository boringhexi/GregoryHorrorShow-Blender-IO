import bpy
from bpy.props import CollectionProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

bl_info = {
    "name": "Gregory Horror Show GHS/MAP-PM2 format",
    "author": "boringhexi",
    "version": (0, 1, 2),
    "blender": (3, 5, 0),
    "location": "File > Import",
    "description": "For .ghs and .map-pm2 files from Gregory Horror Show (PS2)",
    "warning": "",
    "doc_url": "",
    "category": "Import-Export",
}

# Make the entire addon reloadable by Blender:
# The "Reload Scripts" command reloads only this file (the top-level __init__.py).
# That means it won't reload our modules imported by this file (or other modules
# imported by those modules). So instead, the code below will reload our modules
# whenever this file is reloaded.
if "_this_file_was_already_loaded" in locals():
    from .reload_modules import reload_modules

    # Order matters. Reload module B before reloading module A that imports module B
    modules_to_reload = (
        ".common",
        ".pm2.pm2model",
        ".pm2.pm2importer",
        ".ghs.meshposrot",
        ".ghs.ghsimporter",
        ".ghs.findimportdirs",
        ".mappm2.mappm2container",
        ".mappm2.mappm2importer",
        ".import_ghs_pm2",
    )
    reload_modules(*modules_to_reload, pkg=__package__)
_this_file_was_already_loaded = True  # to detect the reload next time
# After this point, any imports of the modules above will be up-to-date.


class ImportGHSPM2(bpy.types.Operator, ImportHelper):
    """Import GHS, MAP-PM2, and/or PM2 files"""

    bl_idname = "import_scene.ghspm2"
    bl_label = "Import GHS/MAP-PM2"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.ghs;*.map-pm2;*.pm2", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    def execute(self, context):
        # to reduce Blender startup time, delay import until now
        from . import import_ghs_pm2

        keywords = self.as_keywords(ignore=("filter_glob",))
        return import_ghs_pm2.load(context, **keywords)

    def draw(self, context):
        pass


class GHSPM2_PT_import_options(bpy.types.Panel):
    bl_space_type = "FILE_BROWSER"
    bl_region_type = "TOOL_PROPS"
    bl_label = "Options"
    bl_parent_id = "FILE_PT_operator"

    @classmethod
    def poll(cls, context):
        sfile = context.space_data
        operator = sfile.active_operator

        return operator.bl_idname == "IMPORT_SCENE_OT_pm2"

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        sfile = context.space_data
        operator = sfile.active_operator


def menu_func_import(self, context):
    self.layout.operator(
        ImportGHSPM2.bl_idname, text="Gregory Horror Show (.ghs/.map-pm2)"
    )


classes = (
    ImportGHSPM2,
    GHSPM2_PT_import_options,
)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.TOPBAR_MT_file_import.append(menu_func_import)


def unregister():
    bpy.types.TOPBAR_MT_file_import.remove(menu_func_import)
    for cls in classes:
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
