"""MicroStation implementation of the DGN backend (runs only inside MicroStation).

Every Bentley API call used by this project is in this file.  The signatures
were checked against the MicroStation Python API reference on
developer.bentley.com (documentation/microstation-python-api/apireference/...)
and Bentley's official API presentations (pdf/06 Working with Elements,
pdf/24 Item Types).  Calls marked ``VERIFY-IN-MS`` are documented in Bentley
material but either their constructor/enum spelling is not listed in the
reference pages or their behaviour must be confirmed in the installed
version; each of them is guarded and reported, and
microstation/inspect_environment.py prints what the installed version offers.
See docs/MicroStation_verifiering.md.

Reference summary (module.Class.method - source page)
  MSPyMstnPlatform.ISessionMgr.GetActiveDgnFile/GetActiveDgnModel/GetActiveDgnModelRef  - ISessionMgr
  MSPyMstnPlatform.PyCadInputQueue.SendKeyin(keyinStr)                                   - PyCadInputQueue
  MSPyDgnPlatform.DgnModel.GetModelInfo, Is3d, GetFileLevelCache, GetGraphicElements      - DgnModel
  MSPyDgnPlatform.ModelInfo.GetUorPerMeter/GetGlobalOrigin/GetMasterUnit                  - ModelInfo
  MSPyDgnPlatform.FileLevelCache.CreateLevel(levelName, levelCode, levelId), Write()      - FileLevelCache
  MSPyDgnPlatform.LevelCache.GetLevelByName/GetLowestAvailableLevelCode/...Id             - FileLevelCache
  MSPyDgnPlatform.EditLevelHandle.SetDescription/SetDisplay                               - EditLevelHandle
  MSPyBentleyGeom.DgnBoxDetail.InitFromCenters(...), ISolidPrimitive.CreateDgnBox(detail) - DgnBoxDetail / ISolidPrimitive
  MSPyBentleyGeom.PolyfaceHeader.CreateVariableSizeIndexed(), AddPolygon(list), Compress,
      SetTwoSided, IsClosedByEdgePairing, ValidatedVolume                                 - PolyfaceHeader
  MSPyBentleyGeom.CurveVector.CreateLinear(points, boundaryType, forceXY)                 - CurveVector
  MSPyDgnPlatform.DraftingElementSchema.ToElement(eeh, curves|solid|mesh, template, ...)  - DraftingElementSchema
  MSPyDgnPlatform.EditElementHandle.AddToModel/DeleteFromModel/GetElementId                - EditElementHandle
  MSPyDgnPlatform.ElementPropertiesSetter.SetLevel/SetColor/SetWeight/Apply                - ElementPropertiesSetter
  MSPyDgnPlatform.ItemTypeLibrary.FindByName/AddItemType/GetItemTypeByName/Write           - ItemTypeLibrary
  MSPyDgnPlatform.ItemType.AddProperty/GetPropertyByName                                  - ItemType
  MSPyDgnPlatform.CustomProperty.SetType                                                  - CustomProperty
  MSPyDgnPlatform.CustomItemHost.ApplyCustomItem(itemType, importLibrariesIfRequired),
      GetCustomItem(libraryName, itemTypeName)                                            - CustomItemHost
  MSPyECObjects.DgnECInstance.SetValue(accessString, ECValue), WriteChanges()             - DgnECInstance
  MSPyECObjects.ECValue.SetString/SetDouble/SetBoolean/SetInteger                          - ECValue
  MSPyDgnPlatform.NamedGroup.Create(name, description, flags, rootModelRef) -> (status, group),
      AddMember(elementId, modelRef, memberFlags), WriteToFile(overwriteExisting)          - NamedGroup
  MSPyDgnPlatform.DgnGCS.CreateGCS(keyName, modelRef) / CreateGCS(baseGCS, modelRef),
      ToModel(modelRef, primary, writeToFile, reproject, reportProblems)                  - DgnGCS
  MSPyDgnPlatform.BaseGCS.CreateGCS(), InitFromEPSGCode(code), GetEPSGCode, GetName       - BaseGCS
  MSPyDgnPlatform.ConfigurationManager.GetVariable(WString, name)                          - ConfigurationManager
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .backend import BackendError, DgnBackend

try:  # The MicroStation Python modules only exist inside MicroStation
    from MSPyBentley import WString  # noqa: F401
    from MSPyBentleyGeom import (CurveVector, DgnBoxDetail, DPoint3d, DVec3d, ISolidPrimitive,  # noqa: F401
                                 PolyfaceHeader)
    from MSPyECObjects import ECValue
    from MSPyDgnPlatform import (BaseGCS, ConfigurationManager, CustomItemHost, CustomProperty,  # noqa: F401
                                 DgnGCS, DraftingElementSchema, EditElementHandle, ElementPropertiesSetter,
                                 ItemTypeLibrary, NamedGroup, NamedGroupFlags, NamedGroupMemberFlags)
    from MSPyMstnPlatform import ISessionMgr, PyCadInputQueue
    MICROSTATION_AVAILABLE = True
    IMPORT_ERROR = None
except ImportError as _e:  # pragma: no cover - outside MicroStation
    MICROSTATION_AVAILABLE = False
    IMPORT_ERROR = str(_e)


def _ok(status) -> bool:
    """BentleyStatus/StatusInt success test (SUCCESS == 0)."""
    try:
        return int(status) == 0
    except (TypeError, ValueError):
        return bool(status)


def get_config_variable(name: str) -> str:
    """ConfigurationManager.GetVariable(cfgValue: WString, cfgVarName: str) -> BentleyStatus."""
    w = WString()
    st = ConfigurationManager.GetVariable(w, name)
    return str(w) if _ok(st) else ""


def property_type_enum():
    """CustomProperty.Type (Bentley pdf/24 uses ``CustomProperty.Type.String``; the
    reference page names the enum ``CustomProperty.Type1``).  VERIFY-IN-MS."""
    for name in ("Type", "Type1"):
        enum = getattr(CustomProperty, name, None)
        if enum is not None and hasattr(enum, "String"):
            return enum
    raise BackendError("CustomProperty type enum not found; dir(CustomProperty)=%s" % dir(CustomProperty))


def create_item_type_library(name: str, dgn_file):
    """Bentley pdf/24: ``ItemTypeLibrary.Create(name, dgnFile, False)``.  The
    reference page lists no factory, so the constructor form is tried too.
    VERIFY-IN-MS."""
    factory = getattr(ItemTypeLibrary, "Create", None)
    if factory is not None:
        return factory(name, dgn_file, False)
    return ItemTypeLibrary(name, dgn_file, False)


class MicroStationBackend(DgnBackend):
    name = "MicroStation"

    def __init__(self, log=print):
        if not MICROSTATION_AVAILABLE:
            raise BackendError("MicroStation Python modules are not available: %s" % IMPORT_ERROR)
        self.log = log
        self.dgn_file = ISessionMgr.GetActiveDgnFile()
        self.model = ISessionMgr.GetActiveDgnModel()
        self.model_ref = ISessionMgr.GetActiveDgnModelRef()
        if self.dgn_file is None or self.model is None:
            raise BackendError("No active DGN file/model. Open the output DGN before running the script.")
        info = self.model.GetModelInfo()
        self.uor_per_meter = float(info.GetUorPerMeter())
        go = info.GetGlobalOrigin()
        self.global_origin = (go.x, go.y, go.z)
        self._libs: Dict[str, Any] = {}
        self._item_types: Dict[Tuple[str, str], Any] = {}
        self._ptype = None

    # ---------------------------------------------------------------- helpers
    def _pt(self, p) -> "DPoint3d":
        u = self.uor_per_meter
        g = self.global_origin
        return DPoint3d(g[0] + p[0] * u, g[1] + p[1] * u, g[2] + p[2] * u)

    @staticmethod
    def _vec(v) -> "DVec3d":
        return DVec3d(v[0], v[1], v[2])

    def _symbology(self, eeh, level_id: int, color: int, weight: int) -> None:
        setter = ElementPropertiesSetter()
        setter.SetLevel(int(level_id))
        setter.SetColor(int(color))
        setter.SetWeight(int(weight))
        setter.Apply(eeh)

    def _finish(self, eeh, status, what: str, level_id, color, weight):
        if not _ok(status):
            raise BackendError("DraftingElementSchema.ToElement failed for %s (status %s)" % (what, status))
        self._symbology(eeh, level_id, color, weight)
        st = eeh.AddToModel()
        if not _ok(st):
            raise BackendError("AddToModel failed for %s (status %s)" % (what, st))
        return eeh

    # ------------------------------------------------------------ environment
    def environment(self) -> Dict[str, Any]:
        env = {"backend": self.name, "dgn_file": str(self.dgn_file.GetFileName()),
               "model": str(self.model.GetModelName())}
        for var in ("_USTN_PRODUCT_RELEASE", "_USTN_PRODUCT_VERSION_GENERATION", "_ENGINENAME", "MS_PYTHON",
                    "MS_DESIGNSEED", "_USTN_INSTALLED_DGNLIBS"):
            try:
                env[var] = get_config_variable(var)
            except Exception as e:  # pragma: no cover
                env[var] = "error: %s" % e
        return env

    def check_model(self) -> Dict[str, Any]:
        info = self.model.GetModelInfo()
        mu = info.GetMasterUnit()
        out = {"is3d": bool(self.model.Is3d()), "uor_per_meter": self.uor_per_meter,
               "global_origin_uor": self.global_origin}
        try:
            out["master_unit_label"] = str(mu.GetLabel())
            out["master_unit_name"] = str(mu.GetName())
        except Exception as e:  # pragma: no cover
            out["master_unit_error"] = str(e)
        return out

    def set_coordinate_system(self, cs_cfg: Dict[str, Any]) -> Dict[str, Any]:
        tried = []
        for key in cs_cfg.get("bentley_gcs_keynames", []):
            try:
                gcs = DgnGCS.CreateGCS(key, self.model_ref)
            except Exception as e:
                tried.append((key, "exception %s" % e))
                continue
            if gcs is None or (hasattr(gcs, "IsValid") and not gcs.IsValid()):
                tried.append((key, "invalid"))
                continue
            vkey = cs_cfg.get("bentley_vertical_datum_key")
            if vkey:
                tried.append(("vertical:" + vkey, gcs.SetVerticalDatumByKey(vkey)))
            st = gcs.ToModel(self.model_ref, True, True, False, False)
            return {"status": "ok" if _ok(st) else "ToModel status %s" % st, "keyname": key,
                    "epsg": gcs.GetEPSGCode(False), "name": str(gcs.GetName()), "tried": tried}
        # fallback: EPSG code (reference page states 20000-32767 for projected systems, 3011 may be refused)
        try:
            base = BaseGCS.CreateGCS()
            res = base.InitFromEPSGCode(int(cs_cfg["epsg_horizontal"]))
            if _ok(res[0] if isinstance(res, tuple) else res):
                gcs = DgnGCS.CreateGCS(base, self.model_ref)
                st = gcs.ToModel(self.model_ref, True, True, False, False)
                return {"status": "ok" if _ok(st) else "ToModel status %s" % st, "epsg_init": res,
                        "epsg": gcs.GetEPSGCode(False), "name": str(gcs.GetName()), "tried": tried}
            tried.append(("EPSG:%s" % cs_cfg["epsg_horizontal"], str(res)))
        except Exception as e:
            tried.append(("EPSG", "exception %s" % e))
        return {"status": "NOT SET - assign SWEREF 99 18 00 manually (Geographic Coordinate System dialog)",
                "tried": tried}

    # ------------------------------------------------------------------ levels
    def ensure_levels(self, levels: Dict[str, Dict[str, Any]]) -> Dict[str, int]:
        cache = self.dgn_file.GetLevelCache()
        out: Dict[str, int] = {}
        changed = False
        for name, spec in levels.items():
            lh = cache.GetLevelByName(name)
            if lh is None or not lh.IsValid():
                code = cache.GetLowestAvailableLevelCode()
                lid = cache.GetLowestAvailableLevelId()
                elh = cache.CreateLevel(name, code, lid)
                if elh is None or not elh.IsValid():
                    raise BackendError("Could not create level %s" % name)
                elh.SetDescription(spec.get("description", ""))
                if spec.get("display") is False:
                    elh.SetDisplay(False)
                changed = True
                lh = cache.GetLevelByName(name)
            out[name] = int(lh.GetLevelId())
        if changed:
            cache.Write()
        return out

    # -------------------------------------------------------------- item types
    def ensure_item_types(self, library: str, spec: Dict[str, Sequence[Tuple[str, str]]]) -> Dict[str, Any]:
        ptype = property_type_enum()
        self._ptype = ptype
        lib = ItemTypeLibrary.FindByName(library, self.dgn_file)
        created = lib is None
        if created:
            lib = create_item_type_library(library, self.dgn_file)
        added = []
        for it_name, props in spec.items():
            it = lib.GetItemTypeByName(it_name)
            if it is None:
                it = lib.AddItemType(it_name, False)
                added.append(it_name)
            for pname, ptype_name in props:
                prop = it.GetPropertyByName(pname)
                if prop is None:
                    prop = it.AddProperty(pname, False)
                    if not prop.SetType(getattr(ptype, ptype_name)):
                        raise BackendError("SetType(%s) failed for %s.%s" % (ptype_name, it_name, pname))
        st = lib.Write()
        lib = ItemTypeLibrary.FindByName(library, self.dgn_file)
        if lib is None:
            raise BackendError("Item type library %s not found after Write() (status %s)" % (library, st))
        self._libs[library] = lib
        for it_name in spec:
            self._item_types[(library, it_name)] = lib.GetItemTypeByName(it_name)
        schema = None
        try:
            schema = str(lib.GetInternalName())
        except Exception:  # pragma: no cover
            pass
        return {"library": library, "created": created, "item_types_added": added, "internal_name": schema}

    def find_bentley_ifc_classification(self, cfg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Locate Bentley's delivered 'IFC Classification' item type in the active
        DGN (imported from IFC_Classes_Types.dgnlib, see MicroStation help
        "(Technology Preview) To Import and Attach IFC-related Item Types")."""
        for lib_name in cfg.get("library_name_candidates", []):
            lib = ItemTypeLibrary.FindByName(lib_name, self.dgn_file)
            if lib is None:
                continue
            for it_name in cfg.get("item_type_candidates", []):
                it = lib.GetItemTypeByName(it_name)
                if it is None:
                    continue
                props = {}
                for role in ("version", "class", "type"):
                    for cand in cfg.get("%s_property_candidates" % role, []):
                        if it.GetPropertyByName(cand) is not None:
                            props[role] = cand
                            break
                self._libs[lib_name] = lib
                self._item_types[(lib_name, it_name)] = it
                return {"library": lib_name, "item_type": it_name, "properties": props}
        return None

    # ------------------------------------------------------------------- purge
    def _generated_handles(self, library: str, marker_item_type: str):
        for elem_ref in self.model.GetGraphicElements():
            eeh = EditElementHandle(elem_ref)  # pdf/24: EditElementHandle(eh.GetElementRef())
            host = CustomItemHost(eeh, False)
            inst = host.GetCustomItem(library, marker_item_type)
            if inst is not None:
                yield eeh, inst

    def purge_generated(self, library: str, marker_item_type: str) -> int:
        if ItemTypeLibrary.FindByName(library, self.dgn_file) is None:
            return 0
        victims = [eeh for eeh, _ in self._generated_handles(library, marker_item_type)]
        n = 0
        for eeh in victims:
            if _ok(eeh.DeleteFromModel()):
                n += 1
        return n

    # ---------------------------------------------------------------- elements
    def add_box(self, base_center, x_axis, y_axis, size_x, size_y, size_z, level_id, color, weight):
        z = (x_axis[1] * y_axis[2] - x_axis[2] * y_axis[1], x_axis[2] * y_axis[0] - x_axis[0] * y_axis[2],
             x_axis[0] * y_axis[1] - x_axis[1] * y_axis[0])
        top = (base_center[0] + z[0] * size_z, base_center[1] + z[1] * size_z, base_center[2] + z[2] * size_z)
        u = self.uor_per_meter
        detail = DgnBoxDetail.InitFromCenters(self._pt(base_center), self._pt(top), self._vec(x_axis), self._vec(y_axis),
                                              size_x * u, size_y * u, size_x * u, size_y * u, True)
        solid = ISolidPrimitive.CreateDgnBox(detail)
        eeh = EditElementHandle()
        st = DraftingElementSchema.ToElement(eeh, solid, None, self.model_ref)
        return self._finish(eeh, st, "box", level_id, color, weight)

    def add_mesh(self, vertices, faces, level_id, color, weight):
        pf = PolyfaceHeader.CreateVariableSizeIndexed()
        pts = [self._pt(p) for p in vertices]
        for f in faces:
            pf.AddPolygon([pts[i] for i in f])
        pf.Compress()
        pf.SetTwoSided(False)
        closed = bool(pf.IsClosedByEdgePairing())
        eeh = EditElementHandle()
        st = DraftingElementSchema.ToElement(eeh, pf, None, self.model_ref)
        self._finish(eeh, st, "mesh", level_id, color, weight)
        if not closed:
            self.log("WARNING: mesh is not closed by edge pairing (element %s)" % eeh.GetElementId())
        return eeh

    def add_ruled_sweep(self, sections, level_id, color, weight):
        """VERIFY-IN-MS: DgnRuledSweepDetail has no documented constructor; the
        C++ API constructor is (bvector<CurveVectorPtr>, bool capped)."""
        from MSPyBentleyGeom import DgnRuledSweepDetail
        curves = [CurveVector.CreateLinear([self._pt(p) for p in sec + [sec[0]]],
                                           CurveVector.BoundaryType.eBOUNDARY_TYPE_Outer, False) for sec in sections]
        detail = DgnRuledSweepDetail(curves, True)
        solid = ISolidPrimitive.CreateDgnRuledSweep(detail)
        eeh = EditElementHandle()
        st = DraftingElementSchema.ToElement(eeh, solid, None, self.model_ref)
        return self._finish(eeh, st, "ruled sweep", level_id, color, weight)

    def add_linestring(self, points, level_id, color, weight):
        cv = CurveVector.CreateLinear([self._pt(p) for p in points], CurveVector.BoundaryType.eBOUNDARY_TYPE_Open, False)
        eeh = EditElementHandle()
        st = DraftingElementSchema.ToElement(eeh, cv, None, True, self.model_ref)
        return self._finish(eeh, st, "line string", level_id, color, weight)

    def add_shape(self, points, level_id, color, weight):
        pts = [self._pt(p) for p in points] + [self._pt(points[0])]
        cv = CurveVector.CreateLinear(pts, CurveVector.BoundaryType.eBOUNDARY_TYPE_Outer, False)
        eeh = EditElementHandle()
        st = DraftingElementSchema.ToElement(eeh, cv, None, True, self.model_ref)
        return self._finish(eeh, st, "shape", level_id, color, weight)

    def element_id(self, element) -> int:
        return int(element.GetElementId())

    # ------------------------------------------------------------- item values
    @staticmethod
    def _ecvalue(value) -> "ECValue":
        v = ECValue()
        if isinstance(value, bool):
            v.SetBoolean(value)
        elif isinstance(value, int):
            v.SetInteger(value)
        elif isinstance(value, float):
            v.SetDouble(value)
        else:
            v.SetString("" if value is None else str(value))
        return v

    def attach_items(self, element, library: str, items: List[Tuple[str, Dict[str, Any]]],
                     bentley_ifc: Optional[Dict[str, Any]] = None) -> None:
        eeh = element
        host = CustomItemHost(eeh, False)
        for it_name, values in items:
            it = self._item_types.get((library, it_name))
            if it is None:
                raise BackendError("Item type %s:%s not prepared" % (library, it_name))
            inst = host.ApplyCustomItem(it, True)
            if inst is None:
                raise BackendError("ApplyCustomItem returned None for %s" % it_name)
            for prop, value in values.items():
                inst.SetValue(prop, self._ecvalue(value))
            inst.WriteChanges()
        if bentley_ifc:
            lib_name, it_name, values = bentley_ifc["library"], bentley_ifc["item_type"], bentley_ifc["values"]
            it = self._item_types.get((lib_name, it_name))
            inst = host.ApplyCustomItem(it, True)
            if inst is None:
                raise BackendError("ApplyCustomItem returned None for Bentley IFC Classification")
            for prop, value in values.items():
                inst.SetValue(prop, self._ecvalue(value))
            inst.WriteChanges()

    # ------------------------------------------------------------ named groups
    def create_named_group(self, name: str, description: str, element_ids: List[int]) -> None:
        res = NamedGroup.Create(name, description, NamedGroupFlags(), self.model_ref)
        status, group = (res if isinstance(res, tuple) else (0, res))
        if not _ok(status) or group is None:
            raise BackendError("NamedGroup.Create failed for %s (status %s)" % (name, status))
        flags = NamedGroupMemberFlags()
        for eid in element_ids:
            group.AddMember(int(eid), self.model_ref, flags)
        st = group.WriteToFile(True)
        if not _ok(st):
            raise BackendError("NamedGroup.WriteToFile failed for %s (status %s)" % (name, st))

    # -------------------------------------------------------------------- save
    def save(self) -> None:
        # FILEDESIGN is MicroStation's "Save" key-in
        PyCadInputQueue.SendKeyin("FILEDESIGN")

    # ---------------------------------------------------------------- read back
    def scan_generated(self, library: str, marker_item_type: str,
                       spec: Optional[Dict[str, Sequence[Tuple[str, str]]]] = None) -> List[Dict[str, Any]]:
        """Read back every element carrying ``marker_item_type`` and the values of
        all item types in ``spec`` (property names are known from the spec, so
        no property enumeration API is needed)."""
        out = []
        if ItemTypeLibrary.FindByName(library, self.dgn_file) is None:
            return out
        for eeh, _ in self._generated_handles(library, marker_item_type):
            host = CustomItemHost(eeh, False)
            items = {}
            for it_name, props in (spec or {}).items():
                inst = host.GetCustomItem(library, it_name)
                if inst is None:
                    continue
                vals = {}
                for p, _t in props:
                    v = ECValue()
                    inst.GetValue(v, p)
                    if v.IsNull():
                        vals[p] = None
                    elif v.IsBoolean():
                        vals[p] = v.GetBoolean()
                    elif v.IsDouble():
                        vals[p] = v.GetDouble()
                    elif v.IsInteger():
                        vals[p] = v.GetInteger()
                    else:
                        vals[p] = str(v.GetString())
                items[it_name] = vals
            out.append({"element_id": int(eeh.GetElementId()), "items": items,
                        "element_type": int(eeh.GetElementType())})
        return out


def timed(log, label: str):
    class _T:
        def __enter__(self):
            self.t = time.perf_counter()
            return self

        def __exit__(self, *a):
            log("%-38s %8.2f s" % (label, time.perf_counter() - self.t))
    return _T()
