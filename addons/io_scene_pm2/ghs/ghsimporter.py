import json
from collections import defaultdict
from itertools import chain
from pathlib import Path
from typing import Optional

import bpy
from bpy.types import Action, Armature, FCurve, Material, Mesh, Object
from mathutils import Euler, Vector

from ..pm2.pm2importer import Pm2Importer
from ..pm2.pm2model import Pm2Model
from .meshposrot import mpr_from_file


def set_action_interpolation(bpyaction: Action):
    """set all pos/rot to LINEAR (but preserves CONSTANT) and all scale to CONSTANT"""
    for fcurve in bpyaction.fcurves:
        curvetype = fcurve.data_path.rsplit(".", maxsplit=1)[1]
        if curvetype in ("location", "rotation_euler", "value"):
            for point in fcurve.keyframe_points:
                if point.interpolation != "CONSTANT":
                    point.interpolation = "LINEAR"
        elif curvetype == "scale":
            for point in fcurve.keyframe_points:
                point.interpolation = "CONSTANT"
        else:
            continue


def set_action_1frame_interpolation(
    bpyaction: Action,
    frameidx: int,
    curvetypes: tuple[str, ...],
    interpolation: str,
    posebone: str = None,
):
    """set all fcurves at frameidx to interpolation

    posebone: if bpyaction belongs to an armature, can filter by posebone name
    """
    for fcurve in bpyaction.fcurves:
        curvetype = fcurve.data_path.rsplit(".", maxsplit=1)[1]
        if posebone is not None:
            fcurve_posebone = fcurve.data_path.split('"')[1]
        else:
            fcurve_posebone = None
        if curvetype in curvetypes and posebone == fcurve_posebone:
            frame_point = fcurve.keyframe_points[frameidx]
            frame_point.interpolation = interpolation


def has_scale_keyframe_at_frame(armobj, scalehide_bonename, frame):
    if armobj.animation_data is None:
        return False
    bpyaction = armobj.animation_data.action
    for fcurve in bpyaction.fcurves:
        poseandbonename, curvetype = fcurve.data_path.rsplit(".", maxsplit=1)
        bonename = poseandbonename.split('"')[1]
        if bonename != scalehide_bonename:
            continue
        if curvetype != "scale":
            continue
        keyframe0 = fcurve.keyframe_points[0]
        return keyframe0.co[0] == frame
    return False


class GhsImporter:
    def __init__(self, ghspath, pm2dir, mprdir, bl_name="", anim_method="1LONG"):
        """

        :param ghspath:
        :param pm2dir:
        :param mprdir:
        :param anim_method: one of str: "1LONG" (all in a single timeline animation),
        "1LONG_EVERY100" (single timeline animation, each animation begins on a multiple
        of 100 frames), "DRIVER" (separate animations, uses a driver bone to drive shape
        keys), or "SEPARATE_ARMATURES" (each animation gets a separate armature)
        :param bl_name:
        """
        self.ghspath = Path(ghspath)
        self.pm2dir = Path(pm2dir)
        self.mprdir = Path(mprdir) if mprdir is not None else None
        self.bl_name = bl_name
        self.anim_method = anim_method
        self._texoffset_materials_to_reuse: dict[str, Material] = dict()

    def import_stuff(self):
        # load ghs data and MeshPosRots
        with open(self.ghspath, "rt") as ghsfile:
            ghsdata = json.load(ghsfile)
        boneparentinfo = ghsdata["bone_parenting_info"]
        defaultbodyparts = ghsdata["default_body_parts"]
        anims = ghsdata["animations"]
        mprs = []
        if self.mprdir is not None:
            mprpaths = self.mprdir.glob("*.mpr")
            for mprpath in sorted(mprpaths):
                with open(mprpath, "rb") as mprfile:
                    mpr = mpr_from_file(mprfile)
                mprs.append(mpr)

        # create armature
        original_armdata = bpy.data.armatures.new(f"{self.bl_name}_arm")
        original_armobj = bpy.data.objects.new(original_armdata.name, original_armdata)
        bpy.context.collection.objects.link(original_armobj)
        bpy.context.view_layer.objects.active = original_armobj
        # create edit bones, save mapping of boneidx to bone name
        boneidx_to_bonename = dict()
        bpy.ops.object.mode_set(mode="EDIT")
        for boneidx in range(len(boneparentinfo)):
            bpyeditbone = original_armdata.edit_bones.new(name=str(boneidx))
            bpyeditbone.tail = Vector((0, 1, 0))
            boneidx_to_bonename[boneidx] = bpyeditbone.name
        # parent editbones using boneparentinfo and previously saved mapping
        for boneidx, boneparentdata in enumerate(boneparentinfo):
            parentidx = boneparentdata["parent"]
            if parentidx is None:
                continue
            bpybonename = boneidx_to_bonename[boneidx]
            bpyparentname = boneidx_to_bonename[parentidx]
            bpyeditbone = original_armdata.edit_bones[bpybonename]
            bpyparenteditbone = original_armdata.edit_bones[bpyparentname]
            bpyeditbone.parent = bpyparenteditbone

        # load default pm2 body parts
        pm2idx_to_meshobj = dict()
        pm2idx_to_scalehidebone = dict()
        original_default_pm2mesh_to_scalehide_bonename = dict()
        boneidx_to_default_scalehide_bonename = dict()
        default_scalehide_bonename_to_pm2mesh = dict()
        for boneidx, bodypart in enumerate(defaultbodyparts):
            # import default body part pm2
            pm2idx = bodypart["pm2"]
            if pm2idx is None or pm2idx < 0:
                continue
            pm2path = self.pm2dir / f"{pm2idx:03x}.pm2"
            with open(pm2path, "rb") as fp:
                pm2model = Pm2Model.from_file(fp)
            pm2importer = Pm2Importer(
                pm2model,
                bl_name=f"b{boneidx}_p{pm2idx:03x}",
                texoffset_materials_to_reuse=self._texoffset_materials_to_reuse,
            )
            pm2importer.import_scene()
            pm2meshobj = pm2importer.bl_meshobj
            # create scalehide bone for this default body mesh
            bpy.ops.object.mode_set(mode="EDIT")
            scalehide_editbone = original_armobj.data.edit_bones.new(
                name=f"b{boneidx}_p{pm2idx:03x}_hide"
            )
            scalehide_editbone.head = (0, 0, 0)
            scalehide_editbone.tail = (0, 1, 0)
            parent_bonename = boneidx_to_bonename[boneidx]
            parent_editbone = original_armobj.data.edit_bones[parent_bonename]
            scalehide_editbone.parent = parent_editbone
            scalehide_bonename = scalehide_editbone.name
            pm2idx_to_scalehidebone[pm2idx] = scalehide_bonename
            # and parent that mesh to the scalehide bone
            bpy.ops.object.mode_set(mode="POSE")
            pm2meshobj.parent = original_armobj
            pm2meshobj.parent_type = "BONE"
            pm2meshobj.parent_bone = scalehide_bonename
            pm2meshobj.location[1] = -1
            boneidx_to_default_scalehide_bonename[boneidx] = scalehide_bonename
            default_scalehide_bonename_to_pm2mesh[scalehide_bonename] = pm2meshobj.data

            pm2idx_to_meshobj[pm2idx] = pm2meshobj
            original_default_pm2mesh_to_scalehide_bonename[
                pm2meshobj.data
            ] = scalehide_bonename
        bpy.ops.object.mode_set(mode="OBJECT")

        if self.anim_method in ("DRIVER", "1LONG", "1LONG_EVERY100"):
            armobj = original_armobj
        else:  # elif self.anim_method = "SEPARATE_ARMATURES"
            armobj = None

        # get full animation lengths in advance from keyframes
        animlengths = dict()
        for animidx, anim in enumerate(anims):
            anim_len = 0
            for keyframes in anim["animation_data"]:
                for keyframe in keyframes:
                    keyframe_start = keyframe["keyframe_start"]
                    if keyframe_start < 999:
                        anim_len = max(anim_len, keyframe_start)
            animlengths[animidx] = anim_len

        frame_offset = 0
        pm2idx_to_driverbone = dict()
        animidx_to_scalehide_bones = defaultdict(list)
        boneidx_to_scalehide_bones = defaultdict(list)
        deleteme_bonenames = []
        made_copies = False

        for animidx, (anim, mpr) in enumerate(zip(anims, mprs)):
            is_last_animation = animidx + 1 == len(anims)

            if self.anim_method == "SEPARATE_ARMATURES":
                # create new collection
                collection_name = f"{self.bl_name}_anim{animidx}"
                collection = bpy.data.collections.new(collection_name)
                collection_name = collection.name
                bpy.context.scene.collection.children.link(collection)
                # activate new collection
                for lc in bpy.context.view_layer.layer_collection.children:
                    if lc.name == collection_name:
                        bpy.context.view_layer.active_layer_collection = lc
                        break

                # copy existing armature to use as a base
                armdata = original_armdata.copy()
                armdata.name = f"{self.bl_name}_a{animidx}_arm"
                armobj = bpy.data.objects.new(armdata.name, armdata)
                collection.objects.link(armobj)
                bpy.context.view_layer.objects.active = armobj

                # reset this mapping, don't want to reuse non-default pm2 meshes between
                # animations
                pm2idx_to_meshobj = dict()

                # copy default pm2 meshes as well
                # and parent them to respective scalehide bones
                default_scalehide_bonename_to_pm2mesh = dict()
                for (
                    default_pm2mesh,
                    scalehide_bonename,
                ) in original_default_pm2mesh_to_scalehide_bonename.items():
                    meshcopy = default_pm2mesh.copy()
                    bboneidx, pm2suffix = meshcopy.name.split("_")
                    pm2idx = int(pm2suffix.split(".")[0][1:], 16)
                    meshcopy.name = f"{bboneidx}_a{animidx}_p{pm2idx:03x}"
                    pm2meshobj = bpy.data.objects.new(meshcopy.name, meshcopy)
                    collection.objects.link(pm2meshobj)
                    pm2meshobj.parent = armobj
                    pm2meshobj.parent_type = "BONE"
                    pm2meshobj.parent_bone = scalehide_bonename
                    pm2meshobj.location[1] = -1
                    pm2idx_to_meshobj[pm2idx] = pm2meshobj
                    default_scalehide_bonename_to_pm2mesh[
                        scalehide_bonename
                    ] = pm2meshobj.data

                made_copies = True

            if self.anim_method == "DRIVER":
                if armobj.animation_data is not None:
                    armobj.animation_data.action = None

            # animate armature using mpr
            bpy.ops.object.mode_set(mode="POSE")
            # iterate through mpr bones, position pose bones
            last_frame = 0
            for boneidx, boneposedata in mpr.items():
                bpybonename = boneidx_to_bonename[boneidx]
                bpyposebone = armobj.pose.bones[bpybonename]
                bpyposebone.rotation_mode = "ZXY"  # pretty sure it's this and not ZYX
                num_frames = len(boneposedata["pos"])
                last_frame = max(
                    # last_frame, frame_offset + num_frames, animlengths[animidx]
                    last_frame,
                    num_frames,
                    animlengths[animidx],
                )
                for frame in range(num_frames):
                    pos_raw = boneposedata["pos"][frame]
                    pos = Vector(pos_raw)
                    rot_raw = boneposedata["rot"][frame]
                    rot = Euler(rot_raw)
                    bpyposebone.location = pos
                    bpyposebone.rotation_euler = rot
                    bpyposebone.keyframe_insert("location", frame=frame_offset + frame)
                    bpyposebone.keyframe_insert(
                        "rotation_euler", frame=frame_offset + frame
                    )
                    if frame == 0 and armobj.animation_data is not None:
                        # set this and future keyframes to LINEAR interpolation
                        bpyaction: Action = armobj.animation_data.action
                        set_action_1frame_interpolation(
                            bpyaction,
                            -1,
                            ("location", "rotation_euler"),
                            "LINEAR",
                            posebone=bpyposebone.name,
                        )
            if (
                self.anim_method in ("1LONG", "1LONG_EVERY100")
                and armobj.animation_data is not None
            ):
                bpyaction: Action = armobj.animation_data.action
                # prevent interpolation between consecutive animations by setting all
                # final keyframes in this mpr to CONSTANT
                # Note: a constant keyframe causes all future keyframes in the curve to
                # be created constant too, so later keyframes need to be set LINEAR
                set_action_1frame_interpolation(
                    bpyaction, -1, ("location", "rotation_euler"), "CONSTANT"
                )

            # keeping track of stuff to later prevent accidental interpolation between
            # consecutive animations in 1LONG/1LONG_EVERY100 modes
            shapekeys_already_keyframed = set()
            shapekeyactions = set()

            if self.anim_method == "DRIVER" and armobj.animation_data is not None:
                bpyaction: Action = armobj.animation_data.action
                anim_name = str(animidx)
                anim_len = anim["anim_len"]
                bpyaction.frame_end = anim_len
                # put this Action into a new NLA track/strip
                bpy_nla_track = armobj.animation_data.nla_tracks.new()
                bpy_nla_track.name = anim_name
                bpy_nla_strip = bpy_nla_track.strips.new(anim_name, 0, bpyaction)
                bpy_nla_strip.name = anim_name  # because it didn't stick the first time
                bpy_nla_strip.action_frame_end = anim_len
                # lock and mute all NLA tracks, just like the glTF importer. This way an
                # animation only plays when it is starred/solo'd in the GUI
                bpy_nla_track.mute = True
                bpy_nla_track.lock = True

            next_anim_start_frame = 0
            if self.anim_method == "1LONG":
                next_anim_start_frame = frame_offset + last_frame + 1
            elif self.anim_method == "1LONG_EVERY100":
                next_anim_start_frame = (frame_offset + last_frame + 100) // 100 * 100
            current_anim_endhide_frame = next_anim_start_frame

            for boneidx, keyframes in enumerate(anim["animation_data"]):
                parent_bonename = boneidx_to_bonename[boneidx]

                prev_pm2idx = None
                for keyframeidx, (keyframe, next_keyframe) in enumerate(
                    zip(keyframes, keyframes[1:] + [None])
                ):
                    keyframe_start = keyframe["keyframe_start"]
                    if keyframe_start >= 999:
                        break
                    pm2idx = keyframe["pm2"]
                    next_pm2idx = next_keyframe["pm2"]

                    # determine animation start/end for this keyframe
                    if keyframe["interp_type"] == 0:
                        # formerly start=end=0, see if this works instead
                        interp_start = interp_end = keyframe["interp_start"]
                    elif keyframe["interp_type"] == 1:
                        interp_start, interp_end = 0, 1
                    elif keyframe["interp_type"] == 2:
                        interp_start = keyframe["interp_start"]
                        interp_end = interp_start + keyframe["interp_delta"]
                    elif keyframe["interp_type"] == -1:
                        interp_start, interp_end = 1, 0
                    # elif keyframe["interp_type"] == -2:
                    else:
                        print(
                            "WARNING: unknown interpolation type "
                            f'{keyframe["interp_type"]}'
                        )
                        interp_start = interp_end = 0

                    # create scalehide bone or retrieve existing one
                    if pm2idx in pm2idx_to_scalehidebone:
                        scalehide_bonename = pm2idx_to_scalehidebone[pm2idx]
                        repeated_bone = True
                    else:
                        scalehide_bonename = None
                        repeated_bone = False
                    if scalehide_bonename is None or scalehide_bonename not in [
                        bone.name for bone in armobj.data.bones
                    ]:
                        bpy.ops.object.mode_set(mode="EDIT")
                        if pm2idx is not None:
                            scalehide_editbone_name = f"b{boneidx}_p{pm2idx:03x}_hide"
                            scalehide_editbone = armobj.data.edit_bones.new(
                                name=scalehide_editbone_name
                            )
                        else:
                            # no pm2 submesh is displayed this keyframe. We still place
                            # a scalehide bone for now to assist with calculating the
                            # visibility of the default pm2's scalehide bone later.
                            scalehide_editbone_name = (
                                f"b{boneidx}_a{animidx}_k{int(keyframe_start)}_DELETEME"
                            )
                            scalehide_editbone = armobj.data.edit_bones.new(
                                name=scalehide_editbone_name
                            )
                            deleteme_bonenames.append(scalehide_editbone.name)
                        scalehide_editbone.head = (0, 0, 0)
                        scalehide_editbone.tail = (0, 1, 0)
                        parent_editbone = armobj.data.edit_bones[parent_bonename]
                        scalehide_editbone.parent = parent_editbone
                        scalehide_bonename = scalehide_editbone.name
                        pm2idx_to_scalehidebone[pm2idx] = scalehide_bonename
                        repeated_bone = False
                    animidx_to_scalehide_bones[animidx].append(scalehide_bonename)
                    boneidx_to_scalehide_bones[boneidx].append(scalehide_bonename)

                    # and animate the scalehide bone
                    bpy.ops.object.mode_set(mode="POSE")
                    scalehide_posebone = armobj.pose.bones[scalehide_bonename]

                    if self.anim_method in ("1LONG", "1LONG_EVERY100"):
                        # hide later pm2s from previous animations
                        scalehide_posebone.scale = (0, 0, 0)
                        if not repeated_bone:
                            scalehide_posebone.keyframe_insert("scale", frame=0)
                        # hide previous pm2s from later animations
                        if not is_last_animation:
                            scalehide_posebone.keyframe_insert(
                                "scale", frame=current_anim_endhide_frame
                            )
                        # place additional keyframe at anim start if the first keyframe
                        # is late; helps prevent pm2 from being hidden after the end of
                        # the previous animation
                        if keyframeidx == 0 and keyframe_start > 0:
                            scalehide_posebone.scale = (1, 1, 1)
                            scalehide_posebone.keyframe_insert(
                                "scale", frame=frame_offset
                            )

                    # place keyframe where scalehide bone is visible (scaled to 1)
                    scalehide_posebone.scale = (1, 1, 1)
                    scalehide_posebone.keyframe_insert(
                        "scale", frame=frame_offset + keyframe_start
                    )
                    # place keyframe where scalehide bone is hidden (scaled to 0)
                    if prev_pm2idx != pm2idx:
                        scalehide_posebone.scale = (0, 0, 0)
                        if keyframe_start > 0 and keyframeidx > 0:
                            scalehide_posebone.keyframe_insert(
                                "scale", frame=frame_offset + keyframe_start - 1
                            )
                    if pm2idx != next_pm2idx:
                        scalehide_posebone.scale = (0, 0, 0)
                        if (
                            next_keyframe is not None
                            and next_keyframe["keyframe_start"] < 999
                        ):
                            scalehide_posebone.keyframe_insert(
                                "scale",
                                frame=frame_offset + next_keyframe["keyframe_start"],
                            )
                    prev_pm2idx = pm2idx

                    # load model for this keyframe or retrieve existing one
                    if pm2idx is not None:
                        if pm2idx in pm2idx_to_meshobj:
                            pm2meshobj = pm2idx_to_meshobj[pm2idx]
                        else:
                            pm2path = self.pm2dir / f"{pm2idx:03x}.pm2"
                            if not pm2path.is_file():
                                continue
                            with open(pm2path, "rb") as fp:
                                pm2model = Pm2Model.from_file(fp)
                            pm2importer = Pm2Importer(
                                pm2model,
                                bl_name=f"b{boneidx}_p{pm2idx:03x}",
                                texoffset_materials_to_reuse=self._texoffset_materials_to_reuse,
                            )
                            pm2importer.import_scene()
                            pm2meshobj = pm2importer.bl_meshobj

                            # and parent to the scalehide bone
                            # bpy.ops.object.mode_set(mode="POSE")  # already in Pose mode
                            pm2meshobj.parent = armobj
                            pm2meshobj.parent_type = "BONE"
                            pm2meshobj.parent_bone = scalehide_bonename
                            pm2meshobj.location[1] = -1
                            pm2idx_to_meshobj[pm2idx] = pm2meshobj

                        # animate shapekey of model
                        if pm2meshobj.data.shape_keys is not None:
                            shapekey = pm2meshobj.data.shape_keys.key_blocks["Anim"]
                            if self.anim_method == "DRIVER":
                                if pm2idx in pm2idx_to_driverbone:
                                    driver_bonename = pm2idx_to_driverbone[pm2idx]
                                else:
                                    # Create and parent driver bone
                                    bpy.ops.object.mode_set(mode="EDIT")
                                    driver_editbone = armobj.data.edit_bones.new(
                                        name=f"{self.bl_name}_driver"
                                    )
                                    driver_editbone.head = (0, 0, 0)
                                    driver_editbone.tail = (0, 1, 0)
                                    driver_editbone.parent = armobj.data.edit_bones[
                                        scalehide_bonename
                                    ]
                                    driver_bonename = driver_editbone.name

                                    # Link driver bone to shape key
                                    fcurve = pm2meshobj.data.shape_keys.key_blocks[
                                        "Anim"
                                    ].driver_add("value")
                                    driver = fcurve.driver
                                    driver.expression = "var"
                                    variable = driver.variables.new()
                                    variable.name = "var"
                                    variable.type = "TRANSFORMS"
                                    target = variable.targets[0]
                                    target.id = armobj
                                    target.bone_target = driver_bonename
                                    target.transform_space = "LOCAL_SPACE"
                                    target.transform_type = "LOC_X"
                                    pm2idx_to_driverbone[pm2idx] = driver_bonename

                                # Animate driver bone
                                bpy.ops.object.mode_set(mode="POSE")
                                driver_posebone = armobj.pose.bones[driver_bonename]
                                driver_posebone.location.x = interp_start
                                driver_posebone.keyframe_insert(
                                    "location",
                                    frame=frame_offset + keyframe_start,
                                )
                                if (
                                    next_keyframe is not None
                                    and next_keyframe["keyframe_start"] < 999
                                ):
                                    driver_posebone.location.x = interp_end
                                    driver_posebone.keyframe_insert(
                                        "location",
                                        frame=frame_offset
                                        + next_keyframe["keyframe_start"],
                                    )

                            else:
                                shapekey.value = interp_start
                                shapekey.keyframe_insert(
                                    "value",
                                    frame=frame_offset + keyframe_start,
                                )
                                skaction = (
                                    pm2meshobj.data.shape_keys.animation_data.action
                                )
                                set_action_1frame_interpolation(
                                    skaction, -1, ("value",), "LINEAR"
                                )
                                shapekeyactions.add(skaction)
                                if self.anim_method in ("1LONG", "1LONG_EVERY100"):
                                    # prevent shapekey value from being held over from
                                    # the previous animation by setting an extra
                                    # keyframe at anim start
                                    if (
                                        shapekey not in shapekeys_already_keyframed
                                        and frame_offset + keyframe_start > 0
                                    ):
                                        shapekey.keyframe_insert(
                                            "value", frame=frame_offset
                                        )
                                        shapekeys_already_keyframed.add(shapekey)

                                if (
                                    next_keyframe is not None
                                    and next_keyframe["keyframe_start"] < 999
                                ):
                                    shapekey.value = interp_end
                                    shapekey.keyframe_insert(
                                        "value",
                                        frame=frame_offset
                                        + next_keyframe["keyframe_start"],
                                    )

            if self.anim_method in ("1LONG", "1LONG_EVERY100"):
                frame_offset = next_anim_start_frame
                # prevent interpolation of shapekeys between consecutive animations
                for skaction in shapekeyactions:
                    set_action_1frame_interpolation(
                        skaction, -1, ("value",), "CONSTANT"
                    )
            if self.anim_method in ("1LONG", "1LONG_EVERY100", "SEPARATE_ARMATURES"):
                for skaction in shapekeyactions:
                    set_action_interpolation(skaction)
            if (
                self.anim_method == "SEPARATE_ARMATURES"
                and armobj.animation_data is not None
            ):
                # set frame-by-frame visibility of each default pm2's scalehide bone
                # and other fcurve set/cleanup
                bpyaction: Action = armobj.animation_data.action
                set_action_interpolation(bpyaction)
                simplify_scalehide_fcurves(bpyaction)
                self.set_default_scalehide_bones_visibility(
                    boneidx_to_default_scalehide_bonename,
                    boneidx_to_scalehide_bones,
                    bpyaction,
                )
                set_action_interpolation(bpyaction)
                delete_unused_default_pm2meshes(
                    default_scalehide_bonename_to_pm2mesh, armobj
                )
                delete_deleteme_bones(deleteme_bonenames, armobj.data)

        if self.anim_method == "DRIVER":
            # scale to 0 all scalehide bones not in the current animation
            bpy.ops.object.mode_set(mode="POSE")
            all_actions = []
            if armobj.animation_data is not None:
                for animidx, bpy_nla_track in enumerate(
                    armobj.animation_data.nla_tracks
                ):
                    bpy_nla_strip = bpy_nla_track.strips[0]
                    bpyaction = bpy_nla_strip.action
                    armobj.animation_data.action = bpyaction
                    all_actions.append(bpyaction)

                    # for all scalehide bones not in this animation, set frame 0 to
                    # scale 0 if there isn't already a scale keyframe there
                    this_anim_scalehide_bones = set(animidx_to_scalehide_bones[animidx])
                    if not this_anim_scalehide_bones:
                        # takes care of case where animation_data == [], i.e. there are
                        # only default body parts in this animation
                        this_anim_scalehide_bones = set(
                            default_scalehide_bonename_to_pm2mesh.keys()
                        )
                    all_scalehide_bones = set(
                        chain.from_iterable(animidx_to_scalehide_bones.values())
                    )
                    not_this_anim_scalehide_bones = all_scalehide_bones.difference(
                        this_anim_scalehide_bones
                    )
                    # set frame 0 to scale 0 if there isn't already a scale keyframe there
                    for scalehide_bonename in not_this_anim_scalehide_bones:
                        scalehide_posebone = armobj.pose.bones[scalehide_bonename]
                        if not has_scale_keyframe_at_frame(
                            armobj, scalehide_bonename, 0
                        ):
                            scalehide_posebone.scale = (0, 0, 0)
                            scalehide_posebone.keyframe_insert("scale", frame=0)

                    # set frame-by-frame visibility of each default pm2's scalehide bone
                    # and other fcurve set/cleanup
                    set_action_interpolation(bpyaction)
                    simplify_scalehide_fcurves(bpyaction)
                    self.set_default_scalehide_bones_visibility(
                        boneidx_to_default_scalehide_bonename,
                        boneidx_to_scalehide_bones,
                        bpyaction,
                    )
                    set_action_interpolation(bpyaction)

            delete_unused_default_pm2meshes(
                default_scalehide_bonename_to_pm2mesh, armobj, all_actions
            )
            delete_deleteme_bones(deleteme_bonenames, armobj.data)

        if self.anim_method in ("1LONG", "1LONG_EVERY100"):
            # set frame-by-frame visibility of each default pm2's scalehide bone
            # and other fcurve set/cleanup
            if armobj.animation_data is not None:
                bpyaction = original_armobj.animation_data.action
                set_action_interpolation(bpyaction)
                simplify_scalehide_fcurves(bpyaction)
                self.set_default_scalehide_bones_visibility(
                    boneidx_to_default_scalehide_bonename,
                    boneidx_to_scalehide_bones,
                    bpyaction,
                )
                set_action_interpolation(bpyaction)
            delete_unused_default_pm2meshes(
                default_scalehide_bonename_to_pm2mesh, armobj
            )
            delete_deleteme_bones(deleteme_bonenames, armobj.data)

        bpy.ops.object.mode_set(mode="OBJECT")
        if self.anim_method == "SEPARATE_ARMATURES" and made_copies:
            # delete the original armature, we made copies of it but aren't using it
            bpy.data.armatures.remove(original_armdata)
            # same with the original default body part meshes
            for default_pm2mesh in original_default_pm2mesh_to_scalehide_bonename:
                bpy.data.meshes.remove(default_pm2mesh)

    def set_default_scalehide_bones_visibility(
        self,
        boneidx_to_default_scalehide_bonename,
        boneidx_to_scalehide_bones,
        bpyaction: Action,
    ):
        # calc and set frame-by-frame visibility of each default pm2's scalehide bone
        bpy.ops.object.mode_set(mode="POSE")
        for (
            boneidx,
            default_scalehide_bonename,
        ) in boneidx_to_default_scalehide_bonename.items():
            overwriting_scalehide_bonenames = boneidx_to_scalehide_bones.get(boneidx)
            if overwriting_scalehide_bonenames is None:
                continue

            # get the fcurves we'll need
            default_fcurves = [None, None, None]
            overwriting_fcurves_x = []
            for fcurve in bpyaction.fcurves:
                poseandbonename, curvetype = fcurve.data_path.rsplit(".", maxsplit=1)
                bonename = poseandbonename.split('"')[1]
                if curvetype == "scale":
                    if bonename == default_scalehide_bonename:
                        # there are 3 fcurves, x y and z scale
                        default_fcurves[fcurve.array_index] = fcurve
                    elif (
                        bonename in overwriting_scalehide_bonenames
                        and fcurve.array_index == 0
                    ):
                        overwriting_fcurves_x.append(fcurve)

            # create default scalehide fcurves if they don't already exist
            for axis, default_fcurve in enumerate(default_fcurves):
                if default_fcurve is None:
                    data_path = f'pose.bones["{default_scalehide_bonename}"].scale'
                    default_fcurve = bpyaction.fcurves.new(data_path, index=axis)
                    default_fcurves[axis] = default_fcurve

            self.calc_default_scalehide_fcurves(default_fcurves, overwriting_fcurves_x)

    def calc_default_scalehide_fcurves(
        self,
        default_fcurves: tuple[FCurve, FCurve, FCurve],
        overwriting_fcurves: list[FCurve],
    ) -> None:
        """modify default_fcurves to display correctly around overwriting_fcurves

        In plain speak, this makes the default body part meshes display only when needed
        (instead of being displayed all the time)

        Prerequisite: all fcurves must be already in CONSTANT interpolation, with all
        keyframe values being either 0 or 1.

        :param default_fcurves: list [x,y,z] of scale fcurves of the default scalehide bone.
            These fcurves will be modified in-place
        :param overwriting_fcurves: list of scalehide fcurves of the overwriting pm2s
        """

        default_mypoints = fcurve_to_mypoints(default_fcurves[0])
        if (
            self.anim_method in ("1LONG", "1LONG_EVERY100")
            and default_mypoints
            and default_mypoints[0][0] != 0
        ):
            # fixes a bug in 1LONG mode where when the same pm2mesh is both a default
            # and overwriting pm2mesh, it would not be properly hidden until later in
            # the timeline.
            default_mypoints = [(0, 0)] + default_mypoints
        overwriting_mypoints = [fcurve_to_mypoints(fc) for fc in overwriting_fcurves]
        overwriting_sum = sum_scalehide_mypoints(overwriting_mypoints)
        inverted_overwriting_sum = invert_scalehide_mypoints(overwriting_sum)
        new_default_mypoints = sum_scalehide_mypoints(
            [default_mypoints, inverted_overwriting_sum]
        )
        new_default_mypoints = simplify_scalehide_mypoints(new_default_mypoints)
        for default_fcurve in default_fcurves:
            mypoints_into_fcurve(new_default_mypoints, default_fcurve)


def fcurve_to_mypoints(fcurve: FCurve) -> list[tuple[int, float]]:
    """get mypoints from fcurve keyframes

    "mypoints" are nothing more than a list of (framenum, value)
    """
    num_keyframes = len(fcurve.keyframe_points)
    if num_keyframes == 0:
        return []
    seq = [0] * 2 * num_keyframes
    fcurve.keyframe_points.foreach_get("co", seq)
    # seq is now populated. "chunk" seq into pairs and return
    return [(seq[i], seq[i + 1]) for i in range(0, len(seq), 2)]


def sum_scalehide_mypoints(
    mypoints_lists: list[list[tuple[int, float]]]
) -> list[tuple[int, float]]:
    """2nd attempt, let's try something more certain: evaluate every frame

    or at least evaluate every keyframe
    """
    mypoints_lists = [x for x in mypoints_lists if x]
    if len(mypoints_lists) == 1:
        return mypoints_lists[0]
    if len(mypoints_lists) == 0:
        return []

    # create a mapping to be used later
    last_keyframe = 0
    framenum_to_keyframed_timeline_indices_and_vals = defaultdict(list)
    for i, mypoints in enumerate(mypoints_lists):
        for framenum, value in mypoints:
            framenum_to_keyframed_timeline_indices_and_vals[framenum].append((i, value))
            last_keyframe = max(last_keyframe, framenum)

    current_val_per_timelines = [1] * len(mypoints_lists)

    summed_timeline = []
    for framenum in range(int(last_keyframe)):
        keyframed_timeline_indices_and_vals = (
            framenum_to_keyframed_timeline_indices_and_vals[framenum]
        )
        for timeline_i, value in keyframed_timeline_indices_and_vals:
            current_val_per_timelines[timeline_i] = value
        summed_value = max(current_val_per_timelines)
        summed_timeline.append((framenum, summed_value))
    return summed_timeline


def invert_scalehide_mypoints(
    mypoints: list[tuple[int, float]]
) -> list[tuple[int, float]]:
    """invert the values of mypoints (for a given definition of "invert")

    :param mypoints: list of (framenum, value)
    :return: list of (framenum, value) where value is 0 if it was 1, or 1 if it was 0
    """
    ret = []
    for framenum, value in mypoints:
        if value == 0:
            value = 1
        else:  # elif value == 1:
            value = 0
        ret.append((framenum, value))
    return ret


def simplify_scalehide_mypoints(
    mypoints: list[tuple[int, float]]
) -> list[tuple[int, float]]:
    return mypoints  # TODO


def mypoints_into_fcurve(mypoints: list[tuple[int, float]], fcurve: FCurve) -> None:
    """insert mypoints into fcurve as keyframes

    modifies fcurve in-place, replacing its keyframes mypoints
    """
    num_keyframes = len(mypoints)
    if num_keyframes == 0:
        pass  # TODO just delete the fcurve from the action instead?
    seq = list(chain.from_iterable(mypoints))
    fcurve.keyframe_points.clear()
    fcurve.keyframe_points.add(count=num_keyframes)
    fcurve.keyframe_points.foreach_set("co", seq)


def simplify_scalehide_fcurves(bpyaction: Action):
    ...  # TODO as well...


def delete_unused_default_pm2meshes(
    default_scalehide_bonename_to_pm2mesh: dict[str, Mesh],
    armobj: Object,
    actions: Optional[list[Action]] = None,
) -> None:
    """remove any pm2mesh and scalehide bone that is always hidden (across all Actions)

    :param default_scalehide_bonename_to_pm2mesh: dict of bone names to mesh datablocks.
    Used to remove any pm2mesh that corresponds to an always-hidden scalehide bone.
    :param armobj: armature object. used to delete unused bones
    :param actions: if None, use armobj's action, scan through all Actions to see
    whether a given scalehide bone is used or not
    """
    if actions is None:
        if armobj.animation_data is None:
            actions = []
        else:
            actions = [armobj.animation_data.action]
    original_mode = bpy.context.object.mode
    sets_of_editbones_to_remove = []
    sets_of_pm2meshes_to_remove = []
    bpy.ops.object.mode_set(mode="POSE")
    for action in actions:
        editbones_to_remove = set()
        pm2meshes_to_remove = set()
        for fcurve in action.fcurves:
            poseandbonename, curvetype = fcurve.data_path.rsplit(".", maxsplit=1)
            fcurve_bonename = poseandbonename.split('"')[1]
            if fcurve_bonename in default_scalehide_bonename_to_pm2mesh:
                if fcurve_is_all0(fcurve):
                    editbones_to_remove.add(fcurve_bonename)
                    pm2mesh = default_scalehide_bonename_to_pm2mesh[fcurve_bonename]
                    pm2meshes_to_remove.add(pm2mesh)
        sets_of_editbones_to_remove.append(editbones_to_remove)
        sets_of_pm2meshes_to_remove.append(pm2meshes_to_remove)

    if sets_of_pm2meshes_to_remove:
        bpy.ops.object.mode_set(mode="OBJECT")
        for pm2mesh in set.intersection(*sets_of_pm2meshes_to_remove):
            bpy.data.meshes.remove(pm2mesh)

    if sets_of_editbones_to_remove:
        bpy.ops.object.mode_set(mode="EDIT")
        arm: Armature = armobj.data
        for edit_bone in arm.edit_bones:
            if edit_bone.name in set.intersection(*sets_of_editbones_to_remove):
                arm.edit_bones.remove(edit_bone)

    bpy.ops.object.mode_set(mode=original_mode)


def fcurve_is_all0(fcurve: FCurve) -> bool:
    mypoints = fcurve_to_mypoints(fcurve)
    if not mypoints:
        return False
    framenums, values = zip(*mypoints)
    return not any(values)


def delete_deleteme_bones(deleteme_bonenames: list[str], arm: Armature) -> None:
    """remove any bone whose name is in deleteme_bonenames

    :param deleteme_bonenames: list of bone names
    :param arm: armature datablock containing the bones
    """
    original_mode = bpy.context.object.mode

    bpy.ops.object.mode_set(mode="EDIT")
    for edit_bone in arm.edit_bones:
        if edit_bone.name in deleteme_bonenames:
            print("deleting", edit_bone.name)
            arm.edit_bones.remove(edit_bone)

    bpy.ops.object.mode_set(mode=original_mode)
