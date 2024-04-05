from collections import namedtuple
from glob import glob
from os import PathLike
from pathlib import Path
from typing import Optional, Union

import bpy
from bpy.types import Image, Material, ShaderNodeBsdfPrincipled
from bpy_extras.io_utils import unpack_list
from mathutils import Vector

from .pm2model import AnimatedPrim, Pm2Model, PrimList


MatSettings = namedtuple("MatSettings", ("texoffset", "doublesided", "transparent"))


class Pm2Importer:
    def __init__(
        self,
        pm2model: Pm2Model,
        bl_name: str = "",
        texdir: Union[str, PathLike[str], None] = None,
        matsettings_materials_to_reuse: Optional[dict[MatSettings, Material]] = None,
    ):
        """imports a PM2 model, including any vertex animation

        after importing, the Blender mesh object can be accessed via x.bl_meshobj, and
        the mapping of texoffsets to Materials via x.texoffsets_materials_used

        :param pm2model: pm2 model to import
        :param bl_name: what to name this mesh in Blender. Also used to name materials
        :param texdir: if provided, path to directory containing textures to load
        :param matsettings_materials_to_reuse: if provided, a mapping of MatSettings to
            Blender materials. The import process will reuse an existing material if
            its MatSettings is encountered, and the mapping will be updated with any new
            materials created during the import process.
        """
        self.pm2model = pm2model
        self.bl_name = bl_name
        self._texdir = Path(texdir)
        self._matsettings_materials_to_reuse = matsettings_materials_to_reuse

        self._bpycollection = bpy.context.collection
        self.bl_meshobj = None
        self._texoffsets_to_images: dict[str, Image] = dict()

    def import_scene(self):
        self.import_mesh()
        self.import_textures()
        self.create_and_assign_materials()
        self.import_shapekey()

    def import_mesh(self):
        me = bpy.data.meshes.new(self.bl_name)

        # add geometry
        vertices = []
        faces = []
        face_offset = 0
        for primlist in self.pm2model.primlists:
            for prim in primlist:
                vertices.extend(prim.positions)
                for i in range(len(prim) - 2):
                    oi = face_offset + i
                    if i % 2 == 0:
                        tri = (oi + 1, oi, oi + 2)
                    else:  # reverse winding of odd-numbered triangles
                        tri = (oi, oi + 1, oi + 2)
                    faces.append(tri)
                face_offset += len(prim)
        me.from_pydata(vertices, [], faces)

        # add normals
        normals = []
        for primlist in self.pm2model.primlists:
            for prim in primlist:
                prim_normals = (-Vector(n) for n in prim.normals)
                normals.extend(prim_normals)
        me.normals_split_custom_set_from_vertices(normals)
        if hasattr(me, "use_auto_smooth"):  # gone in Blender 4.1.0 onward
            me.use_auto_smooth = True

        # add texcoords
        uv_layer = me.uv_layers.new()
        stcoords = []
        for primlist in self.pm2model.primlists:
            for prim in primlist:
                stcoords.extend(prim.texcoords)
        uvcoords = [(s, 1 - t) for s, t in stcoords]
        loop_uvcoords = [uvcoords[lo.vertex_index] for lo in me.loops]
        uv_layer.data.foreach_set("uv", unpack_list(loop_uvcoords))

        # add vertex colors
        color_attribute = me.color_attributes.new("", "FLOAT_COLOR", "POINT")
        colors = []
        for primlist in self.pm2model.primlists:
            for prim in primlist:
                colors.extend(prim.colors)
        color_attribute.data.foreach_set("color", unpack_list(colors))

        # link mesh to Blender scene
        ob = bpy.data.objects.new(me.name, me)
        self._bpycollection.objects.link(ob)
        self.bl_meshobj = ob

    def import_textures(self):
        if self._texdir is None:
            return

        for primlist in self.pm2model.primlists:
            # take last 3 hex digits of texture_offset
            primlist_texoffset_trunc = f"{primlist.texture_offset:04x}"[-3:]

            # and use it to find a matching texture filename
            for texpath in glob(str(self._texdir / "*.png")):
                texpath = Path(texpath)
                texpath_texoffset = texpath.name[6:-4]
                texpath_texoffset_trunc = texpath_texoffset[-3:]
                if primlist_texoffset_trunc == texpath_texoffset_trunc:
                    teximage = bpy.data.images.load(str(texpath), check_existing=True)
                    self._texoffsets_to_images[primlist_texoffset_trunc] = teximage
                    break
            else:
                print(
                    f"{self.bl_name}: could not find matching texture for texoffset, "
                    f"\n    (i.e. filename ending in '{primlist_texoffset_trunc}.png' "
                    f"within '{self._texdir}')"
                )

    def create_and_assign_materials(self):
        me = self.bl_meshobj.data

        matsettings_to_material_index = dict()
        mat_index = 0
        encountered_matsettings = set()
        primlists_to_matsettings: list[MatSettings] = []
        for primlist in self.pm2model.primlists:
            primlist_texoffset_trunc = f"{primlist.texture_offset:04x}"[-3:]
            doublesided = primlist.doublesided
            teximage = self._texoffsets_to_images.get(primlist_texoffset_trunc)
            transparent = determine_primlist_transparency(primlist, teximage)
            this_matsettings = MatSettings(
                primlist_texoffset_trunc, doublesided, transparent
            )
            primlists_to_matsettings.append(this_matsettings)

            if this_matsettings not in encountered_matsettings:
                # map this_matsettings to index of the soon-to-be-created new material
                matsettings_to_material_index[this_matsettings] = mat_index

                # reuse an existing material if it exists already
                if (
                    self._matsettings_materials_to_reuse is not None
                    and this_matsettings in self._matsettings_materials_to_reuse
                ):
                    mat = self._matsettings_materials_to_reuse[this_matsettings]

                else:  # or create a new material
                    doublesided_name = "_ds" if doublesided else "_bc"
                    matname = (
                        f"{self.bl_name}_0x{primlist_texoffset_trunc}{doublesided_name}"
                    )
                    mat = bpy.data.materials.new(name=matname)

                    # set some material settings
                    mat.use_backface_culling = not doublesided
                    if transparent:
                        mat.blend_method = "BLEND"
                    # mat.show_transparent_back = False  # TODO

                    # set up the material nodes
                    mat.use_nodes = True
                    pbsdfnode = find_principled_bsdf_node(mat)
                    # place Image Texture node to left of Principled BSDF node & connect
                    teximgnode = mat.node_tree.nodes.new("ShaderNodeTexImage")
                    pbsdfnode_x, pbsdfnode_y = pbsdfnode.location
                    teximgnode.location = pbsdfnode_x - 290, pbsdfnode_y
                    mat.node_tree.links.new(
                        teximgnode.outputs["Color"], pbsdfnode.inputs["Base Color"]
                    )
                    mat.node_tree.links.new(
                        teximgnode.outputs["Alpha"], pbsdfnode.inputs["Alpha"]
                    )
                    # assign loaded texture to this Image Texture node
                    image = self._texoffsets_to_images.get(primlist_texoffset_trunc)
                    teximgnode.image = image

                    if self._matsettings_materials_to_reuse is not None:
                        self._matsettings_materials_to_reuse[this_matsettings] = mat

                me.materials.append(mat)
                mat_index += 1
                encountered_matsettings.add(this_matsettings)

        # Map each PrimList (specifically, its vertex indices) to its matsettings
        primlist_vertidxs_to_matsettings = dict()
        vertex_index_offset = 0
        for primlist, matsettings in zip(
            self.pm2model.primlists, primlists_to_matsettings
        ):
            primlist_vertidxs = []
            for prim in primlist:
                prim_vertidxs = [vertex_index_offset + i for i in range(len(prim))]
                primlist_vertidxs.extend(prim_vertidxs)
                vertex_index_offset += len(prim)
            primlist_vertidxs_to_matsettings[tuple(primlist_vertidxs)] = matsettings

        # Assign materials to Blender polygons
        for face in me.polygons:
            # figure out which PrimList this face originally belonged to
            face_vertidxs = set(face.vertices)
            for (
                primlist_vertidxs,
                this_matsettings,
            ) in primlist_vertidxs_to_matsettings.items():
                if face_vertidxs.issubset(primlist_vertidxs):
                    # the face is in this PrimList and therefore uses its texture
                    material_index = matsettings_to_material_index[this_matsettings]
                    face.material_index = material_index
                    break
            else:
                # current face is not a member of any PrimList
                pass

    def import_shapekey(self):
        # first of all, make sure this pm2 actually contains an animation
        if not self.pm2model.animated:
            return

        # Map each Blender vertex index to its position animation deltas
        blvertidxs_to_vertdeltas = list()
        for primlist in self.pm2model.primlists:
            prim: AnimatedPrim
            for prim in primlist:
                blvertidxs_to_vertdeltas.extend(
                    Vector(posd) for posd in prim.position_animdeltas
                )

        # Create shape key
        meshobj = self.bl_meshobj
        sk_basis = meshobj.shape_key_add(name="Basis", from_mix=False)
        sk_basis.interpolation = "KEY_LINEAR"
        meshobj.data.shape_keys.use_relative = True
        sk = meshobj.shape_key_add(name="Anim", from_mix=False)
        sk.interpolation = "KEY_LINEAR"
        for vertidx, posd in enumerate(blvertidxs_to_vertdeltas):
            sk.data[vertidx].co += posd
        sk.id_data.name = self.bl_name  # otherwise they're all like "Key.001", etc


def find_principled_bsdf_node(mat: Material) -> Optional[ShaderNodeBsdfPrincipled]:
    for node in mat.node_tree.nodes:
        if node.bl_idname == "ShaderNodeBsdfPrincipled":
            pbsdfnode = node
            break
    else:
        raise RuntimeError("Newly created material has no Principled BSDF node")
    return pbsdfnode


def determine_primlist_transparency(
    primlist: PrimList, bpyimage: Optional[Image]
) -> bool:
    if bpyimage is None:
        return False

    return False  # TODO placeholder
