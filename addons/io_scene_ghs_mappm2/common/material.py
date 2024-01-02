from collections import namedtuple
from glob import glob
from pathlib import Path
from typing import Optional

import bpy
from bpy.types import Material

MatSettings = namedtuple("MatSettings", ("texoffset", "doublesided"))


def import_materials(
    matsettings_materials: dict[MatSettings, Material], texdir: Optional[Path] = None
):
    # create a mapping to use later
    texoffset_texpaths = dict()
    if texdir is not None:
        for texpath in glob(str(texdir / "*.png")):
            texpath = Path(texpath)
            texoffset = texpath.name[6:-4]
            texoffset_truncated = texoffset[-3:]
            texoffset_texpaths[texoffset_truncated] = texpath

    # iterate through all materials
    for matsettings, mat in matsettings_materials.items():
        texoffset, doublesided = matsettings
        texpath = texoffset_texpaths.get(texoffset)
        if texpath is None:
            print(f"Could not import texture for texoffset {texoffset!r}")

        # set some material settings
        mat.use_backface_culling = not doublesided
        mat.blend_method = "BLEND"
        mat.show_transparent_back = False
        mat.use_nodes = True

        # find the Principled BSDF node
        pbsdfnode = None
        for node in mat.node_tree.nodes:
            if node.bl_idname == "ShaderNodeBsdfPrincipled":
                pbsdfnode = node
                break
        else:
            raise RuntimeError("Newly created material has no Principled BSDF node")

        # place an Image Texture node to left of Principled BSDF node and connect them
        teximgnode = mat.node_tree.nodes.new("ShaderNodeTexImage")
        pbsdfnode_x, pbsdfnode_y = pbsdfnode.location
        teximgnode.location = pbsdfnode_x - 290, pbsdfnode_y
        mat.node_tree.links.new(
            teximgnode.outputs["Color"], pbsdfnode.inputs["Base Color"]
        )
        mat.node_tree.links.new(teximgnode.outputs["Alpha"], pbsdfnode.inputs["Alpha"])

        # load texture file into Image Texture node
        if texpath is not None:
            image = bpy.data.images.load(str(texpath), check_existing=True)
            teximgnode.image = image
