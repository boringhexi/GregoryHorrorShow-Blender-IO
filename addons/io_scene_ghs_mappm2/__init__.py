import bpy
from bpy.props import CollectionProperty, EnumProperty, StringProperty
from bpy_extras.io_utils import ImportHelper

bl_info = {
    "name": "Gregory Horror Show GHS/MAP-PM2 format",
    "author": "boringhexi",
    "version": (0, 1, 9),
    "blender": (4, 0, 0),
    "location": "File > Import",
    "description": "For .ghs and .map-pm2 files from Gregory Horror Show (PS2)",
    "warning": "",
    "doc_url": "https://github.com/boringhexi/blender3d_GregoryHorrorShow/wiki",
    "category": "Import-Export",
}

# Make the entire addon reloadable by Blender:
# The "Reload Scripts" command reloads only this file (the top-level __init__.py).
# That means it won't reload our modules imported by this file (or other modules
# imported by those modules). So instead, the code below will reload our modules
# whenever this file is reloaded.
if "_this_file_was_already_loaded" in locals():
    from .common.reload_modules import reload_modules

    # Order matters. Reload module B before reloading module A that imports module B
    modules_to_reload = (
        ".common.reload_modules",
        ".common.datautils",
        ".common.findimportdirs",
        ".pm2.pm2model",
        ".pm2.pm2importer",
        ".ghs.meshposrot",
        ".ghs.ghsimporter",
        ".mappm2.mappm2container",
        ".mappm2.mappm2importer",
        ".import_ghs_mappm2",
    )
    reload_modules(*modules_to_reload, pkg=__package__)
_this_file_was_already_loaded = True  # to detect the reload next time
# After this point, any imports of the modules above will be up-to-date.


class ImportGHSMAPPM2(bpy.types.Operator, ImportHelper):
    """Import GHS, MAP-PM2, and/or PM2 files"""

    bl_idname = "import_scene.ghsmappm2"
    bl_label = "Import GHS/MAP-PM2"
    bl_options = {"REGISTER", "UNDO"}

    filter_glob: StringProperty(default="*.ghs;*.map-pm2;*.pm2", options={"HIDDEN"})
    files: CollectionProperty(type=bpy.types.PropertyGroup)

    ghs_anim_method: EnumProperty(
        name="GHS animation",
        items=[
            (
                "DRIVER",
                "Easy animation viewer",
                "Imports animations as separate NLA tracks with shapekey drivers. "
                "Works well as an animation viewer, but may have trouble exporting "
                "shapekey animations to other formats",
            ),
            (
                "GLTF",
                "For glTF export",
                "Imports animations as separate NLA tracks, also using NLA tracks for "
                "shapekey animations. From this, glTF exporter can then export a "
                "single file with multiple animations, including shapekey animations"
            ),
            (
                "1LONG",
                "Single timeline",
                "Imports all animations into the timeline in sequence",
            ),
            (
                "1LONG_EVERY100",
                "Single timeline (starts every 100)",
                "Each animation starts on a multiple of 100 frames. Suitable for "
                "exporting to Unity",
            ),
            (
                "SEPARATE_ARMATURES",
                "Separate armatures",
                "Creates a new armature for each animation. Suitable for exporting "
                "each animation to a separate file",
            ),
            (
                "TPOSE",
                "T-Pose approx",
                "Approximates a good-enough T-Pose (by using only default model parts, "
                "no animation, and no rest pose rotation)",
            ),

        ],
        description="How .ghs animations should be imported",
        default="DRIVER",
    )

    def draw(self, context):
        layout = self.layout

        layout.use_property_split = True
        layout.use_property_decorate = False  # No animation.

        layout.prop(self, "ghs_anim_method")

    def execute(self, context):
        # to reduce Blender startup time, delay import until now
        from . import import_ghs_mappm2

        keywords = self.as_keywords(ignore=("filter_glob",))
        return import_ghs_mappm2.load(context, **keywords)


def menu_func_import(self, context):
    self.layout.operator(
        ImportGHSMAPPM2.bl_idname, text="Gregory Horror Show (.ghs/.map-pm2)"
    )


classes = (ImportGHSMAPPM2,)


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
