import bpy
from bpy_extras.io_utils import unpack_list

from .pm2model import Pm2Model


class Pm2Importer:
    def __init__(self, pm2model: Pm2Model, bl_name=""):
        """

        :param pm2model:
        :param blname: what to name this mesh in Blender
        """
        self._pm2model = pm2model
        self._bpycollection = bpy.context.collection
        self.bl_name = bl_name  # TODO get bl_name from filename base
        self.bl_meshobj = None

    def import_scene(self):
        self.import_mesh()
        self.create_and_assign_materials()

    def import_mesh(self):
        me = bpy.data.meshes.new(self.bl_name)

        # add geometry
        vertices = []
        faces = []
        face_offset = 0
        for primlist in self._pm2model.primlists:
            for prim in primlist:
                vertices.extend(prim.positions)
                for i in range(len(prim) - 2):
                    oi = face_offset + i
                    if i % 2 == 0:
                        tri = (oi, oi + 1, oi + 2)
                    else:  # reverse winding of odd-numbered triangles
                        tri = (oi + 1, oi, oi + 2)
                    faces.append(tri)
                face_offset += len(prim)
        me.from_pydata(vertices, [], faces)

        # add normals
        normals = []
        for primlist in self._pm2model.primlists:
            for prim in primlist:
                normals.extend(prim.normals)
        me.normals_split_custom_set_from_vertices(normals)
        me.use_auto_smooth = True

        # add texcoords
        uv_layer = me.uv_layers.new()
        stcoords = []
        for primlist in self._pm2model.primlists:
            for prim in primlist:
                stcoords.extend(prim.texcoords)
        uvcoords = [(s, 1 - t) for s, t in stcoords]
        loop_uvcoords = [uvcoords[lo.vertex_index] for lo in me.loops]
        uv_layer.data.foreach_set("uv", unpack_list(loop_uvcoords))

        # add vertex colors
        color_attribute = me.color_attributes.new("", "FLOAT_COLOR", "POINT")
        colors = []
        for primlist in self._pm2model.primlists:
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
        for primlist in self._pm2model.primlists:
            tex_offset = primlist.texture_offset
            if tex_offset not in encountered_tex_offsets:
                # map tex_offset to index of the soon-to-be-created new material
                tex_offset_to_material_index[tex_offset] = mat_index
                # create a new material
                mat = bpy.data.materials.new(name=f"{self.bl_name}_{hex(tex_offset)}")
                me.materials.append(mat)
                mat_index += 1
                encountered_tex_offsets.add(tex_offset)

        # Map each PrimList (specifically, its vertex indices) to its texture_offset
        primlist_vertidxs_to_tex_offsets = dict()
        vertex_index_offset = 0
        for primlist in self._pm2model.primlists:
            primlist_vertidxs = []
            for prim in primlist:
                prim_vertidxs = [vertex_index_offset + i for i in range(len(prim))]
                primlist_vertidxs.extend(prim_vertidxs)
                vertex_index_offset += len(prim)
            primlist_vertidxs_to_tex_offsets[
                tuple(primlist_vertidxs)
            ] = primlist.texture_offset

        # Assign materials to Blender polygons
        for face in me.polygons:
            # figure out which PrimList this face originally belonged to
            face_vertidxs = set(face.vertices)
            for (
                primlist_vertidxs,
                tex_offset,
            ) in primlist_vertidxs_to_tex_offsets.items():
                if face_vertidxs.issubset(primlist_vertidxs):
                    # the face is in this PrimList and therefore uses its texture
                    material_index = tex_offset_to_material_index[tex_offset]
                    face.material_index = material_index
                    break
            else:
                # current face is not a member of any PrimList
                pass
