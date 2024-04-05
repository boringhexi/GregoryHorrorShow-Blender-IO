from math import radians
from pathlib import Path

import bpy
from bpy.types import Material

from ..pm2.pm2importer import MatSettings, Pm2Importer
from ..pm2.pm2model import Pm2Model
from .mappm2container import MapPm2Container


class MapPm2Importer:
    def __init__(self, mappm2path, texdir, bl_name=""):
        """

        :param mappm2path:
        :param bl_name:
        """
        self.mappm2path = Path(mappm2path)
        self.texdir = texdir
        self.bl_name = bl_name
        self._matsettings_materials_to_reuse: dict[MatSettings, Material] = dict()

    def import_mappm2(self):
        with open(self.mappm2path, "rb") as file:
            mappm2container = MapPm2Container.from_file(file)

        # create new collection
        collection_name = self.bl_name
        collection = bpy.data.collections.new(collection_name)
        collection_name = collection.name
        bpy.context.scene.collection.children.link(collection)
        # activate new collection
        for lc in bpy.context.view_layer.layer_collection.children:
            if lc.name == collection_name:
                bpy.context.view_layer.active_layer_collection = lc
                break

        # import pm2 files
        for i, contentfile in enumerate(mappm2container):
            pm2model = Pm2Model.from_file(contentfile)
            pm2importer = Pm2Importer(
                pm2model,
                bl_name=f"{self.bl_name}_{i:03}",
                texdir=self.texdir,
                matsettings_materials_to_reuse=self._matsettings_materials_to_reuse,
            )
            pm2importer.import_scene()
            # map-pm2 models are 4x too small compared to ghs
            pm2meshobj = pm2importer.bl_meshobj
            pm2meshobj.scale = (4, 4, 4)
            # also need to be rotated to correct axes
            pm2meshobj.rotation_euler = (radians(90), radians(180), 0)
