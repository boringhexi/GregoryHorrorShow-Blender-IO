from typing import Optional

import bpy
from bpy.types import Material
from bpy_extras.io_utils import unpack_list
from mathutils import Vector

from .pm2model import AnimatedPrim, Pm2Model


class Pm2Importer:
    def __init__(
        self,
        pm2model: Pm2Model,
        bl_name="",
        texoffset_materials_to_reuse: Optional[dict[str, Material]] = None,
    ):
        """imports a PM2 model, including any vertex animation

        after importing, the Blender mesh object can be accessed via x.bl_meshobj, and
        the mapping of texoffsets to Materials via x.texoffsets_materials_used

        :param pm2model: pm2 model to import
        :param bl_name: what to name this mesh in Blender. Also used to name materials
        :param texoffset_materials_to_reuse: if provided, a mapping of texoffsets to
            Blender materials. The import process will reuse an existing material if
            its texoffset is encountered, and the mapping will be updated with any new
            materials created during the import process.
        """
        self.pm2model = pm2model
        self.bl_name = bl_name
        self._texoffset_materials_to_reuse = texoffset_materials_to_reuse

        self._bpycollection = bpy.context.collection
        self.bl_meshobj = None

    def import_scene(self):
        self.import_mesh()
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

    def create_and_assign_materials(self):
        me = self.bl_meshobj.data

        tex_offset_to_material_index = dict()
        mat_index = 0
        encountered_tex_offsets = set()
        for primlist in self.pm2model.primlists:
            texoffset_hex_truncated = f"{primlist.texture_offset:04x}"[1:]
            if texoffset_hex_truncated not in encountered_tex_offsets:
                # map tex_offset to index of the soon-to-be-created new material
                tex_offset_to_material_index[texoffset_hex_truncated] = mat_index
                # create a new material
                # (or introduce a new material from self._texoffset_materials_to_reuse)
                if (
                    self._texoffset_materials_to_reuse is not None
                    and texoffset_hex_truncated in self._texoffset_materials_to_reuse
                ):
                    mat = self._texoffset_materials_to_reuse[texoffset_hex_truncated]
                else:
                    matname = f"{self.bl_name}_0x{texoffset_hex_truncated}"
                    mat = bpy.data.materials.new(name=matname)
                    if self._texoffset_materials_to_reuse is not None:
                        self._texoffset_materials_to_reuse[
                            texoffset_hex_truncated
                        ] = mat
                me.materials.append(mat)
                mat_index += 1
                encountered_tex_offsets.add(texoffset_hex_truncated)

        # Map each PrimList (specifically, its vertex indices) to its texture_offset
        primlist_vertidxs_to_truncated_texoffsets = dict()
        vertex_index_offset = 0
        for primlist in self.pm2model.primlists:
            primlist_vertidxs = []
            for prim in primlist:
                prim_vertidxs = [vertex_index_offset + i for i in range(len(prim))]
                primlist_vertidxs.extend(prim_vertidxs)
                vertex_index_offset += len(prim)
            primlist_vertidxs_to_truncated_texoffsets[
                tuple(primlist_vertidxs)
            ] = f"{primlist.texture_offset:04x}"[1:]

        # Assign materials to Blender polygons
        for face in me.polygons:
            # figure out which PrimList this face originally belonged to
            face_vertidxs = set(face.vertices)
            for (
                primlist_vertidxs,
                tex_offset,
            ) in primlist_vertidxs_to_truncated_texoffsets.items():
                if face_vertidxs.issubset(primlist_vertidxs):
                    # the face is in this PrimList and therefore uses its texture
                    material_index = tex_offset_to_material_index[tex_offset]
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
