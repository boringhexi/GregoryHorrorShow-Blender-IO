import bpy
from bpy.props import StringProperty, CollectionProperty
from bpy_extras.io_utils import ImportHelper

bl_info = {
    "name": "Gregory Horror Show PM2 format",
    "author": "boringhexi",
    "version": (0, 1, 2),
    "blender": (3, 5, 0),
    "location": "File > Import",
    "description": "For .pm2 files from Gregory Horror Show (PS2)",
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
        ".pm2.pm2model",
        ".pm2.pm2importer",
        ".import_pm2",
    )
    reload_modules(*modules_to_reload, pkg=__package__)
_this_file_was_already_loaded = True  # to detect the reload next time
# After this point, any imports of the modules above will be up-to-date.


class ImportPM2(bpy.types.Operator, ImportHelper):
    """Import a PM2 file"""

    bl_idname = "import_scene.pm2"
    bl_label = "Import PM2"
    bl_options = {"REGISTER", "UNDO"}
    filename_ext = ".pm2"

    filter_glob: StringProperty(default="*.pm2", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    def execute(self, context):
        # to reduce Blender startup time, delay import until now
        from . import import_pm2

        keywords = self.as_keywords(ignore=("filter_glob",))
        return import_pm2.load(context, **keywords)

    def draw(self, context):
        pass


class PM2_PT_import_options(bpy.types.Panel):
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
    self.layout.operator(ImportPM2.bl_idname, text="Gregory Horror Show (.pm2)")


classes = (
    ImportPM2,
    PM2_PT_import_options,
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
