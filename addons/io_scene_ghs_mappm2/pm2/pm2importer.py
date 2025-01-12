from collections import namedtuple
from glob import glob
from itertools import chain
from math import ceil, floor
from os import PathLike
from pathlib import Path
from typing import Iterable, Optional, Union

import bpy
from bpy.types import Image, Material, ShaderNodeBsdfPrincipled
from bpy_extras.io_utils import unpack_list
from mathutils import Vector

from .pm2model import AnimatedPrim, Pm2Model, PrimList

TRIFILL_DEBUG = False

MatSettings = namedtuple("MatSettings", ("texoffset", "doublesided", "blend_method"))
# blend_method can be any Blender blend method, e.g. OPAQUE, CLIP, BLEND
MyUV = namedtuple("MyUV", "x, y")
TEXTURE_OPAQUE_CUTOFF = 0x7E / 128


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
        self._texdir = Path(texdir) if texdir is not None else None
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
        colors = []
        for primlist in self.pm2model.primlists:
            for prim in primlist:
                colors.extend(prim.colors)
        # ...unless all the vertex colors are 100% opaque white (i.e. no visible effect)
        if any(c != (1, 1, 1, 1) for c in colors):
            if hasattr(me, "color_attributes"):
                color_attribute = me.color_attributes.new("", "FLOAT_COLOR", "POINT")
                color_attribute.data.foreach_set("color", unpack_list(colors))
            elif hasattr(me, "vertex_colors"):  # Blender 3.0-3.1 compatibility
                color_layer = me.vertex_colors.new()
                loop_vcolors = (colors[lo.vertex_index] for lo in me.loops)
                color_layer.data.foreach_set("color", unpack_list(loop_vcolors))
            else:
                raise AttributeError(
                    "Mesh data has neither `color_attributes` nor `vertex_colors`, "
                    "can't set vertex colors"
                )

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
            blend_method = determine_primlist_blend_method(primlist, teximage)
            this_matsettings = MatSettings(
                primlist_texoffset_trunc, doublesided, blend_method
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
                    blend_name = f"_{blend_method.lower()}"
                    matname = (
                        f"{self.bl_name}_0x{primlist_texoffset_trunc}{doublesided_name}"
                        f"{blend_name}"
                    )
                    mat = bpy.data.materials.new(name=matname)

                    # set some material settings
                    mat.use_backface_culling = not doublesided
                    mat.blend_method = blend_method
                    mat.show_transparent_back = False

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
                    teximage = self._texoffsets_to_images.get(primlist_texoffset_trunc)
                    teximgnode.image = teximage

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


def determine_primlist_blend_method(
    primlist: PrimList, bpyimage: Optional[Image]
) -> str:
    """return Blender blend_method to use for this primlist

    return one of "OPAQUE", "CLIP", or "BLEND"
    """
    encountered_zero_alpha = False

    # check vertex colors for transparency
    for prim in primlist:
        for r, g, b, alpha in prim.colors:
            if alpha < 1.0:
                return "BLEND"

    # return early if image is opaque or invalid
    if bpyimage is None or bpyimage.channels < 4:
        return "OPAQUE"
    imgwidth, imgheight = bpyimage.size
    if not (imgwidth and imgheight):
        return "OPAQUE"

    imagepixels = [0] * imgwidth * imgheight * 4
    bpyimage.pixels.foreach_get(imagepixels)

    # check for any image transparency that is covered by primlist's UVs
    for prim in primlist:
        # remember, prims are trilists, we need to make them separate triangles
        for i in range(len(prim) - 2):
            tri_uvs = prim.texcoords[i : i + 3]
            tri_uvs = [MyUV(uv[0], 1 - uv[1]) for uv in tri_uvs]
            # sort points from top-left to bottom-right
            tri_uvs.sort(key=lambda uv: (-uv.y, uv.x))
            v1, v2, v3 = tri_uvs

            if v1 == v2 == v3:
                # UV triangle forms a point
                tri_pixel_idxs = ((int(v1.x * imgwidth), int(v1.y * imgheight)),)
            elif v1.y == v2.y == v3.y:
                # UV triangles form a horizontal line
                tri_pixel_idxs = horizontal_line_tri_pixel_idxs(
                    v1, v2, v3, imgwidth, imgheight
                )
            elif v2.y == v3.y:
                # UV triangle has flat bottom
                tri_pixel_idxs = flat_bottom_tri_pixels_idxs(
                    v1, v2, v3, imgwidth, imgheight
                )
            elif v1.y == v2.y:
                # UV triangle has flat top
                tri_pixel_idxs = flat_top_tri_pixels_idxs(
                    v1, v2, v3, imgwidth, imgheight
                )
            else:
                # split UV triangle into flat-bottom and flat-top triangles
                v4x = v1.x + ((v2.y - v1.y) / (v3.y - v1.y)) * (v3.x - v1.x)
                v4 = MyUV(v4x, v2.y)
                if not v2.x <= v4.x:
                    v2, v4 = v4, v2
                flat_bottom_tri_pixel_idxs = flat_bottom_tri_pixels_idxs(
                    v1, v2, v4, imgwidth, imgheight
                )
                flat_top_tri_pixel_idxs = flat_top_tri_pixels_idxs(
                    v2, v4, v3, imgwidth, imgheight
                )
                tri_pixel_idxs = chain(
                    flat_bottom_tri_pixel_idxs,
                    flat_top_tri_pixel_idxs,
                )

            for x, y in tri_pixel_idxs:
                if 0 <= x < imgwidth and 0 <= y < imgheight:
                    pixel = y * imgwidth + x
                    if TRIFILL_DEBUG:
                        imagepixels[pixel * 4 : pixel * 4 + 4] = (1, 1, 1, 1)
                    else:
                        alpha = imagepixels[pixel * 4 + 3]
                        if 0 < alpha < TEXTURE_OPAQUE_CUTOFF:
                            return "BLEND"
                        elif alpha == 0:
                            encountered_zero_alpha = True

    if TRIFILL_DEBUG:
        bpyimage.pixels.foreach_set(imagepixels)

    # if an alpha value requiring BLEND was encountered, this function will have already
    # returned by now. That only leaves CLIP and OPAQUE
    if encountered_zero_alpha:
        return "CLIP"
    return "OPAQUE"


def horizontal_line_tri_pixel_idxs(
    v1: MyUV, v2: MyUV, v3: MyUV, imgwidth: int, imgheight: int
) -> Iterable[tuple[int, int]]:
    """yield pixels from 3 points forming a horizontal line

    prerequisites:
    - v1.x <= v2.x <= v3.x
    - v1.y == v2.y == v3.y
    """
    # change from float values to pixels
    x1 = floor(v1.x * imgwidth)
    x2 = ceil(v3.x * imgwidth)
    y = int(v1.y * imgheight)
    for x in range(x1, x2):
        yield x, y


def flat_bottom_tri_pixels_idxs(
    v1: MyUV, v2: MyUV, v3: MyUV, imgwidth: int, imgheight: int
) -> Iterable[tuple[int, int]]:
    """yield points from 3 points forming a flat-bottom triangle

    prerequisites:
    - v1.y > v2.y == v3.y
    - v2.x <= v3.x
    -
    """
    # change from float values to pixels
    v1 = MyUV(v1.x * imgwidth, v1.y * imgheight)
    v2 = MyUV(v2.x * imgwidth, v2.y * imgheight)
    v3 = MyUV(v3.x * imgwidth, v3.y * imgheight)

    invslope1 = (v1.x - v2.x) / (v1.y - v2.y)
    invslope2 = (v3.x - v1.x) / (v1.y - v3.y)

    cury = v1.y
    curx1 = curx2 = v1.x
    while cury >= floor(v2.y):
        curx = floor(curx1)
        while curx <= ceil(curx2):
            x, y = int(curx) % imgwidth, int(cury) % imgheight
            yield x, y
            curx += 1
        if cury - 1 < v2.y:
            factor = cury - v2.y
            cury -= 1
            curx1 -= invslope1 * factor
            curx2 += invslope2 * factor
        else:
            cury -= 1
            curx1 -= invslope1
            curx2 += invslope2


def flat_top_tri_pixels_idxs(
    v1: MyUV, v2: MyUV, v3: MyUV, imgwidth: int, imgheight: int
) -> Iterable[tuple[int, int]]:
    """yield points from 3 points forming a flat-bottom triangle

    prerequisites:
    - v3.y < v1.y == v2.y
    - v1.x <= v2.x
    """
    # change from float values to pixels
    v1 = MyUV(v1.x * imgwidth, v1.y * imgheight)
    v2 = MyUV(v2.x * imgwidth, v2.y * imgheight)
    v3 = MyUV(v3.x * imgwidth, v3.y * imgheight)

    invslope1 = (v3.x - v1.x) / (v1.y - v3.y)
    invslope2 = (v2.x - v3.x) / (v2.y - v3.y)

    cury = v3.y
    curx1 = curx2 = v3.x
    while cury <= ceil(v1.y):
        curx = floor(curx1)
        while curx <= ceil(curx2):
            x, y = int(curx) % imgwidth, int(cury) % imgheight
            yield x, y
            curx += 1
        if cury + 1 > v1.y:
            factor = v1.y - cury
            cury += 1
            curx1 -= invslope1 * factor
            curx2 += invslope2 * factor
        else:
            cury += 1
            curx1 -= invslope1
            curx2 += invslope2
