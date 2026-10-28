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
  MSPyDgnPlatform.DgnDocument.CreateForLocalFile(fileName)                                 - DgnDocument
  MSPyDgnPlatform.DgnFile(document, DgnFileOpenMode.eReadOnly), LoadDgnFile() -> tuple,
      FillDictionaryModel()                                    - Bentley pdf/05 "Create New DgnFile"
  MSPyDgnPlatform.ItemTypeLibrary.CloneForFile(destFile, forReplacement=False), Write()     - ItemTypeLibrary
  MSPyDgnPlatform.ItemType.GetPropertyCount/GetPropertyById, CustomProperty.GetPickListName(ECValue),
      SupportsUnits(), SetUnits(DgnECUnit)                                                 - ItemType / CustomProperty
  MSPyECObjects.DgnECUnit.FromID(id), IsSpecified()                                       - DgnECUnit
  MSPyDgnPlatform.PickListLibrary.CreatePickListLibrary(), GetPickListLibFromDgn(file, lib),
      SavePickListLibToDgn(file, lib, update), GetPickListByName(WString),
      PickList.GetValueCount/CanFindValueById/GetPickListValueByID, PickListValue.GetValue - PickList*
  MSPyDgnPlatform.NormalCellHeaderHandler.CreateOrphanCellElement(eeh, name, is3d, modelRef),
      AddChildElement(eeh, childEeh), AddChildComplete(eeh)                               - NormalCellHeaderHandler
  MSPyDgnPlatform.ChildEditElemIter(parent, ExposeChildrenReason.eEdit), ToNext(), IsValid() - ChildEditElemIter
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .backend import BackendError, DgnBackend

# The MicroStation Python modules only exist inside MicroStation.  Every class
# is looked up by name in all MSPy modules, so one name that lives in another
# module (or is missing in an installed version) does not break the others.
REQUIRED = ["WString", "CurveVector", "DgnBoxDetail", "DPoint3d", "DVec3d", "ISolidPrimitive", "PolyfaceHeader",
            "ECValue", "BaseGCS", "ConfigurationManager", "CustomItemHost", "CustomProperty", "DgnGCS",
            "DraftingElementSchema", "EditElementHandle", "ElementPropertiesSetter", "ItemTypeLibrary", "NamedGroup",
            "NamedGroupFlags", "NamedGroupMemberFlags", "ISessionMgr", "PyCadInputQueue"]
OPTIONAL = ["Int32Array", "DPoint3dArray", "LineStringHandler", "ShapeHandler",
            # importing Bentley's IFC Classification from IFC_Classes_Types.dgnlib, units, cells
            "DgnDocument", "DgnFile", "DgnFileOpenMode", "PickListLibrary", "DgnECUnit",
            "NormalCellHeaderHandler", "ChildEditElemIter", "ExposeChildrenReason",
            # enumerating item type libraries whose name is not known
            "ItemTypeLibraries", "DgnECManager", "SchemaInfoArray", "ECSchemaPersistence", "DgnECHostType"]
MISSING_SYMBOLS: List[str] = []
try:
    import MSPyBentley
    import MSPyBentleyGeom
    import MSPyDgnPlatform
    import MSPyECObjects
    import MSPyMstnPlatform
    _MODULES = [MSPyBentley, MSPyBentleyGeom, MSPyECObjects, MSPyDgnPlatform, MSPyMstnPlatform]
    MICROSTATION_AVAILABLE = True
    IMPORT_ERROR = None
except ImportError as _e:  # pragma: no cover - outside MicroStation
    _MODULES = []
    MICROSTATION_AVAILABLE = False
    IMPORT_ERROR = str(_e)


def _symbol(name: str):
    for mod in _MODULES:
        if hasattr(mod, name):
            return getattr(mod, name)
    if MICROSTATION_AVAILABLE:
        MISSING_SYMBOLS.append(name)
    return None


for _name in REQUIRED + OPTIONAL:
    globals()[_name] = _symbol(_name)
if MICROSTATION_AVAILABLE and any(n in MISSING_SYMBOLS for n in REQUIRED):
    IMPORT_ERROR = "missing MicroStation API classes: %s" % [n for n in MISSING_SYMBOLS if n in REQUIRED]


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


def property_types() -> Dict[str, Any]:
    """Item Type property types {'String': value, 'Boolean': ..., 'Double': ..., 'Integer': ...}.

    Bentley pdf/24 writes ``CustomProperty.Type.String``; the installed
    MicroStation 2025 binding exposes the members with the pybind prefix
    ``e`` (``eString``, ``eBoolean``, ``eDouble``, ``eInteger``), both on the
    enum (``CustomProperty.Type``/``Type1``) and directly on ``CustomProperty``
    (verified in MicroStation, see docs/MicroStation_verifiering.md V-02)."""
    holders = [getattr(CustomProperty, n, None) for n in ("Type", "Type1")] + [CustomProperty]
    out: Dict[str, Any] = {}
    for kind in ("String", "Boolean", "Double", "Integer"):
        for holder in holders:
            if holder is None:
                continue
            value = getattr(holder, "e" + kind, None)
            if value is None:
                value = getattr(holder, kind, None)
            if value is not None:
                out[kind] = value
                break
        if kind not in out:
            raise BackendError("Item Type property type %s not found; dir(CustomProperty)=%s" % (kind, dir(CustomProperty)))
    return out


def _norm(text: str) -> str:
    return "".join(ch for ch in str(text).lower() if ch.isalnum())


def dgnlib_candidates(file_name: str, config_values: Sequence[str]) -> List[str]:
    """Directories where Bentley's ``file_name`` may live, derived from
    configuration variable values (MS_DGNLIBLIST_ITEMTYPES, MS_DGNLIBLIST,
    MSDIR ...).  Entries may be folders, files or wildcard patterns separated by
    ';'.  Each folder is tried as is and with an ``ItemTypes`` subfolder (the
    delivered location is <MSDIR>\\Default\\Dgnlib\\ItemTypes).  No
    installation path is hard-coded."""
    import ntpath
    import os
    dirs: List[str] = []
    for value in config_values:
        for entry in (value or "").split(";"):
            entry = entry.strip().strip('"')
            if not entry:
                continue
            if "*" in entry or "?" in entry or entry.lower().endswith(".dgnlib"):
                entry = ntpath.dirname(entry) if "\\" in entry else os.path.dirname(entry)
            entry = entry.rstrip("\\/")
            for d in (entry, entry + "\\ItemTypes", entry + "\\Default\\Dgnlib\\ItemTypes"):
                if d not in dirs:
                    dirs.append(d)
    return [d + "\\" + file_name for d in dirs]


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
        missing = [n for n in MISSING_SYMBOLS if n in REQUIRED]
        if missing:
            raise BackendError("MicroStation API classes not found in MSPy modules: %s" % missing)
        if MISSING_SYMBOLS:
            log("Valfria API-klasser saknas (reservvägar används): %s" % MISSING_SYMBOLS)
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
        if getattr(self, "hold_elements", False):
            return eeh  # not added: becomes a child of a cell (add_cell)
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

    def _gcs_from_epsg(self, code: int, tried: list):
        try:
            base = BaseGCS.CreateGCS()
            res = base.InitFromEPSGCode(int(code))
            if _ok(res[0] if isinstance(res, tuple) else res):
                return DgnGCS.CreateGCS(base, self.model_ref)
            tried.append(("EPSG:%s" % code, str(res)))
        except Exception as e:
            tried.append(("EPSG:%s" % code, "exception %s" % e))
        return None

    def _write_gcs(self, gcs, cs_cfg, tried, **extra):
        for vkey in [cs_cfg.get("bentley_vertical_datum_key")] + list(cs_cfg.get("bentley_vertical_datum_keys", [])):
            if vkey:
                try:
                    tried.append(("vertical:" + vkey, gcs.SetVerticalDatumByKey(vkey)))
                except Exception as e:
                    tried.append(("vertical:" + vkey, "exception %s" % e))
        st = gcs.ToModel(self.model_ref, True, True, False, False)
        out = {"status": "ok" if _ok(st) else "ToModel status %s" % st,
               "epsg": gcs.GetEPSGCode(False), "name": str(gcs.GetName()), "tried": tried}
        for getter in ("GetVerticalDatumName", "GetVerticalDatumCode", "GetDatumName"):
            try:
                out[getter] = str(getattr(gcs, getter)())
            except Exception:
                pass
        out.update(extra)
        return out

    def set_coordinate_system(self, cs_cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Order: EPSG codes in ``epsg_try_first`` (5850 = SWEREF 99 18 00 + RH 2000,
        compound), then the Bentley key names, then epsg_horizontal (3011)."""
        tried = []
        for code in cs_cfg.get("epsg_try_first", []):
            gcs = self._gcs_from_epsg(code, tried)
            if gcs is not None and (not hasattr(gcs, "IsValid") or gcs.IsValid()):
                return self._write_gcs(gcs, cs_cfg, tried, epsg_init=code)
        for key in cs_cfg.get("bentley_gcs_keynames", []):
            try:
                gcs = DgnGCS.CreateGCS(key, self.model_ref)
            except Exception as e:
                tried.append((key, "exception %s" % e))
                continue
            if gcs is None or (hasattr(gcs, "IsValid") and not gcs.IsValid()):
                tried.append((key, "invalid"))
                continue
            return self._write_gcs(gcs, cs_cfg, tried, keyname=key)
        gcs = self._gcs_from_epsg(cs_cfg["epsg_horizontal"], tried)
        if gcs is not None:
            return self._write_gcs(gcs, cs_cfg, tried, epsg_init=cs_cfg["epsg_horizontal"])
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
    def _unit(self, ifc_type: str, units_cfg: Dict[str, Any]):
        """DgnECUnit for an IFC measure type (candidates from config, first one
        that DgnECUnit.FromID resolves).  Cached per IFC type."""
        cache = self.__dict__.setdefault("_unit_cache", {})
        if ifc_type in cache:
            return cache[ifc_type]
        unit = None
        tried = []
        for uid in units_cfg.get(ifc_type, []):
            try:
                u = DgnECUnit.FromID(uid)
                ok = u is not None and (not hasattr(u, "IsSpecified") or u.IsSpecified())
                tried.append((uid, bool(ok)))
                if ok:
                    unit = (uid, u)
                    break
            except Exception as e:
                tried.append((uid, "exception %s" % e))
        cache[ifc_type] = unit
        self.__dict__.setdefault("unit_report", {})[ifc_type] = {"used": unit[0] if unit else None, "tried": tried}
        return unit

    def ensure_item_types(self, library: str, spec: Dict[str, Sequence[Tuple[str, str]]],
                          units: Optional[Dict[Tuple[str, str], str]] = None,
                          units_cfg: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """``units`` maps (item type, property) to the IFC measure type and
        ``units_cfg`` the IFC measure type to DgnECUnit ids; Double properties
        then get CustomProperty.SetUnits(DgnECUnit) so the value carries its unit
        into the export."""
        ptype = property_types()
        self._ptype = ptype
        lib = ItemTypeLibrary.FindByName(library, self.dgn_file)
        created = lib is None
        if created:
            lib = create_item_type_library(library, self.dgn_file)
        added = []
        units_set: List[Tuple[str, str, Any]] = []
        for it_name, props in spec.items():
            it = lib.GetItemTypeByName(it_name)
            if it is None:
                it = lib.AddItemType(it_name, False)
                added.append(it_name)
            for pname, ptype_name in props:
                prop = it.GetPropertyByName(pname)
                if prop is None:
                    prop = it.AddProperty(pname, False)
                    if not prop.SetType(ptype[ptype_name]):
                        raise BackendError("SetType(%s) failed for %s.%s" % (ptype_name, it_name, pname))
                ifc_type = (units or {}).get((it_name, pname))
                if ifc_type and units_cfg and DgnECUnit is not None and ptype_name == "Double":
                    unit = self._unit(ifc_type, units_cfg)
                    if unit is not None:
                        try:
                            ok = prop.SupportsUnits() and prop.SetUnits(unit[1])
                        except Exception as e:
                            ok = "exception %s" % e
                        units_set.append(("%s.%s" % (it_name, pname), unit[0], ok))
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
        return {"library": library, "created": created, "item_types_added": added, "internal_name": schema,
                "units_set": units_set, "unit_ids": getattr(self, "unit_report", {})}

    # ------------------------------------------- Bentley's IFC Classification
    def _all_libraries(self, dgn_file) -> List[Tuple[str, Any]]:
        """Every Item Type library in a file, without knowing its name:
        1. iterate ItemTypeLibraries(dgnFile) (pybind collection, VERIFY-IN-MS),
        2. DgnECManager.DiscoverSchemas(SchemaInfoArray, dgnFile, Stored, eAll)
           + ItemTypeLibrary.FindBySchemaName(schemaName, dgnFile).
        Both ways are tried; what each found is kept in ``self.library_discovery``."""
        found: Dict[str, Any] = {}
        disc: Dict[str, Any] = {}
        try:
            libs = ItemTypeLibraries(dgn_file)
            names = []
            for lib in libs:
                if lib is not None:
                    found.setdefault(str(lib.GetName()), lib)
                    names.append(str(lib.GetName()))
            disc["ItemTypeLibraries"] = names
        except Exception as e:
            disc["ItemTypeLibraries"] = "%s: %s" % (type(e).__name__, e)
        try:
            infos = SchemaInfoArray()
            DgnECManager.GetManager().DiscoverSchemas(infos, dgn_file, ECSchemaPersistence.eECSCHEMAPERSISTENCE_All,
                                                      DgnECHostType.eAll)
            schemas = []
            for info in infos:
                sname = str(info.GetSchemaName())
                lib = ItemTypeLibrary.FindBySchemaName(sname, dgn_file)
                schemas.append([sname, None if lib is None else str(lib.GetName())])
                if lib is not None:
                    found.setdefault(str(lib.GetName()), lib)
            disc["DiscoverSchemas"] = schemas
        except Exception as e:
            disc["DiscoverSchemas"] = "%s: %s" % (type(e).__name__, e)
        self.library_discovery = disc
        return list(found.items())

    def _find_library(self, cfg: Dict[str, Any], dgn_file):
        """Bentley's IFC classification library: by the configured names, else
        the library that holds an item type named like ``item_type_candidates``
        (Bentley's help calls the item type 'IfcClassification')."""
        for name in cfg.get("library_name_candidates", []):
            for finder in (ItemTypeLibrary.FindByName, ItemTypeLibrary.FindBySchemaName):
                try:
                    lib = finder(name, dgn_file)
                except Exception:
                    lib = None
                if lib is not None:
                    return str(lib.GetName()), lib
        wanted = {_norm(n) for n in cfg.get("item_type_candidates", [])}
        libs = self._all_libraries(dgn_file)
        for name, lib in libs:
            if any(_norm(str(it.GetName())) in wanted for it in self._item_types_of(lib)):
                return name, lib
        for name, lib in libs:
            if "ifcclass" in _norm(name):
                return name, lib
        return None, None

    @staticmethod
    def _item_types_of(lib) -> List[Any]:
        out = []
        try:
            for i in range(int(lib.GetItemTypeCount())):
                out.append(lib.GetItemTypeAt(i))
        except Exception:
            pass
        return [it for it in out if it is not None]

    @staticmethod
    def _properties_of(it) -> List[Any]:
        """All properties of an item type (GetPropertyCount + GetPropertyById; the
        ids are not documented to be 0..n-1, so a wider range is scanned)."""
        try:
            n = int(it.GetPropertyCount())
        except Exception:
            return []
        props, seen = [], set()
        for pid in range(0, 4 * n + 16):
            if len(props) >= n:
                break
            try:
                p = it.GetPropertyById(pid)
            except Exception:
                p = None
            if p is not None and str(p.GetName()) not in seen:
                seen.add(str(p.GetName()))
                props.append(p)
        return props

    def _picklist_values(self, prop, dgn_file, limit: int = 2000) -> Optional[Dict[str, Any]]:
        """Name and values of the pick list behind a property (None if it has none)."""
        if PickListLibrary is None:
            return None
        v = ECValue()
        try:
            if not prop.GetPickListName(v) or v.IsNull():
                return None
            name = str(v.GetString())
        except Exception:
            return None
        if not name:
            return None
        try:
            lib = PickListLibrary.CreatePickListLibrary()
            PickListLibrary.GetPickListLibFromDgn(dgn_file, lib)
            pl = lib.GetPickListByName(WString(name))
        except Exception as e:
            return {"name": name, "error": str(e), "values": []}
        if pl is None:
            return {"name": name, "values": [], "error": "pick list not found in file"}
        values, n = [], int(pl.GetValueCount())
        for vid in range(0, 4 * n + 16):
            if len(values) >= min(n, limit):
                break
            try:
                if pl.CanFindValueById(vid):
                    values.append(str(pl.GetPickListValueByID(vid).GetValue()))
            except Exception:
                pass
        return {"name": name, "count": n, "values": values}

    def describe_item_type(self, it, dgn_file=None) -> List[Dict[str, Any]]:
        dgn_file = dgn_file or self.dgn_file
        out = []
        for p in self._properties_of(it):
            entry = {"name": str(p.GetName())}
            try:
                entry["type"] = str(p.GetType())
            except Exception:
                pass
            pl = self._picklist_values(p, dgn_file)
            if pl:
                entry["picklist"] = pl
            out.append(entry)
        return out

    def open_dgn_readonly(self, path: str):
        """Bentley pdf/05: DgnFile(document, DgnFileOpenMode.eReadOnly) + LoadDgnFile();
        the dictionary model holds the Item Type and pick list definitions."""
        doc = DgnDocument.CreateForLocalFile(path)
        if doc is None:
            raise BackendError("DgnDocument.CreateForLocalFile returned None for %s" % path)
        f = DgnFile(doc, DgnFileOpenMode.eReadOnly)
        st = f.LoadDgnFile()
        if not _ok(st[0] if isinstance(st, tuple) else st):
            raise BackendError("LoadDgnFile failed for %s (status %s)" % (path, st))
        f.FillDictionaryModel()
        return f

    def locate_dgnlib(self, cfg: Dict[str, Any]) -> Optional[str]:
        import os
        values = [get_config_variable(v) for v in cfg.get("dgnlib_search_config_variables", [])]
        for cand in dgnlib_candidates(cfg["dgnlib_file"], values):
            if os.path.isfile(cand):
                return cand
        return None

    def import_bentley_ifc_classification(self, cfg: Dict[str, Any]) -> Dict[str, Any]:
        """Copy Bentley's 'IFC Classification' Item Type library and its pick
        lists from IFC_Classes_Types.dgnlib into the active DGN (the same as
        Item Types dialog > Import, MicroStation help "To Import and Attach
        IFC-related Item Types to DGN Elements before Exporting to IFC").
        ItemTypeLibrary.CloneForFile(destFile) + Write(); pick lists with
        PickListLibrary.GetPickListLibFromDgn/SavePickListLibToDgn."""
        rep: Dict[str, Any] = {}
        missing = [n for n in ("DgnDocument", "DgnFile", "DgnFileOpenMode") if globals().get(n) is None]
        if missing:
            rep["error"] = "API classes missing: %s" % missing
            return rep
        path = self.locate_dgnlib(cfg)
        rep["dgnlib"] = path
        if not path:
            rep["error"] = "%s not found via %s" % (cfg["dgnlib_file"], cfg.get("dgnlib_search_config_variables"))
            return rep
        src = self.open_dgn_readonly(path)
        self._dgnlib_src = src  # kept open: the item type may be applied from it directly
        name, lib = self._find_library(cfg, src)
        rep["libraries_in_dgnlib"] = getattr(self, "library_discovery", None)
        if lib is None:
            rep["error"] = "no IFC classification library in %s (names tried %s, item types %s)" % (
                path, cfg.get("library_name_candidates"), cfg.get("item_type_candidates"))
            return rep
        rep["library_in_dgnlib"] = name
        if PickListLibrary is not None:
            try:
                pls = PickListLibrary.CreatePickListLibrary()
                PickListLibrary.GetPickListLibFromDgn(src, pls)
                rep["picklists_in_dgnlib"] = int(pls.GetPickListCount())
                rep["picklists_saved"] = bool(PickListLibrary.SavePickListLibToDgn(self.dgn_file, pls, False))
            except Exception as e:
                rep["picklists_error"] = str(e)
        clone = lib.CloneForFile(self.dgn_file, False)
        if clone is None:
            rep["error"] = "CloneForFile returned None"
            return rep
        rep["written"] = bool(clone.Write())
        return rep

    def find_bentley_ifc_classification(self, cfg: Dict[str, Any], dgn_file=None) -> Optional[Dict[str, Any]]:
        """Locate Bentley's delivered 'IFC Classification' item type in the active
        DGN (or in ``dgn_file``, e.g. the opened dgnlib) and work out which
        property is version/class/type (candidate names from config, otherwise
        by name), with the pick list values of each, so values can be written
        exactly as the pick lists spell them."""
        dgn_file = dgn_file or self.dgn_file
        lib_name, lib = self._find_library(cfg, dgn_file)
        if lib is None:
            return None
        wanted = {_norm(n) for n in cfg.get("item_type_candidates", [])}
        it = next((i for i in self._item_types_of(lib) if _norm(str(i.GetName())) in wanted), None)
        if it is None:
            its = self._item_types_of(lib)
            if len(its) != 1:
                return {"library": lib_name, "item_type": None, "properties": {},
                        "item_types_in_library": [str(i.GetName()) for i in its]}
            it = its[0]
        it_name = str(it.GetName())
        desc = self.describe_item_type(it, dgn_file)
        names = [d["name"] for d in desc]
        props: Dict[str, str] = {}
        for role in ("version", "class", "type"):
            lower = {n.lower(): n for n in names}
            for cand in cfg.get("%s_property_candidates" % role, []):
                if cand.lower() in lower:
                    props[role] = lower[cand.lower()]
                    break
            if role not in props:
                hits = [n for n in names if role in n.lower() and n not in props.values()]
                if hits:
                    props[role] = hits[0]
        self._libs[lib_name] = lib
        self._item_types[(lib_name, it_name)] = it
        picklists = {role: next((d["picklist"]["values"] for d in desc if d["name"] == pname and d.get("picklist")), None)
                     for role, pname in props.items()}
        return {"library": lib_name, "item_type": it_name, "properties": props, "all_properties": desc,
                "picklists": {k: v for k, v in picklists.items() if v}}

    def ensure_bentley_ifc_classification(self, cfg: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Dict[str, Any]]:
        found = self.find_bentley_ifc_classification(cfg)
        rep: Dict[str, Any] = {"present_before": bool(found and found.get("item_type"))}
        if not rep["present_before"] and cfg.get("auto_import", True):
            try:
                rep["import"] = self.import_bentley_ifc_classification(cfg)
            except Exception as e:
                rep["import"] = {"error": "%s: %s" % (type(e).__name__, e)}
            found = self.find_bentley_ifc_classification(cfg)
            src = getattr(self, "_dgnlib_src", None)
            if not (found and found.get("item_type")) and src is not None:
                # second route: attach the item type from the opened dgnlib;
                # ApplyCustomItem(itemType, importLibrariesIfRequired=True) copies
                # the library into the DGN on the first attachment
                found = self.find_bentley_ifc_classification(cfg, src)
                rep["source"] = "dgnlib item type, imported on first ApplyCustomItem"
        if found and not found.get("item_type"):
            rep["error"] = "library found but item type not identified: %s" % found.get("item_types_in_library")
            found = None
        return found, rep

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

    def _indexed_polyface(self, vertices, faces):
        """Closed triangle mesh with exactly shared vertices.

        PolyfaceHeader.CreateIndexedMesh(numPerFace, DPoint3dArray, Int32Array).
        The index base (0/1) is not stated in the reference, so it is probed once
        with IsClosedByEdgePairing() and reused.  Falls back to AddPolygon per
        face WITHOUT Compress(): in the first MicroStation run Compress() merged
        nearby vertices of the rail outline (mm spacing) and broke closure."""
        tri = all(len(f) == 3 for f in faces) and Int32Array is not None and DPoint3dArray is not None
        if tri:
            pts = DPoint3dArray()
            for p in vertices:
                pts.append(self._pt(p))
        bases = [self._mesh_index_base] if getattr(self, "_mesh_index_base", None) is not None else [1, 0]
        if tri:
            for base in bases:
                idx = Int32Array()
                for f in faces:
                    for i in f:
                        idx.append(int(i) + base)
                try:
                    pf = PolyfaceHeader.CreateIndexedMesh(3, pts, idx)
                except Exception as e:  # pragma: no cover - reported once
                    self.log("CreateIndexedMesh failed (%s), using AddPolygon" % e)
                    break
                if pf is not None and pf.IsClosedByEdgePairing():
                    if getattr(self, "_mesh_index_base", None) is None:
                        self._mesh_index_base = base
                        self.log("  polyface: CreateIndexedMesh with %d-based indices" % base)
                    return pf, True
        pf = PolyfaceHeader.CreateVariableSizeIndexed()
        plist = [self._pt(p) for p in vertices]
        for f in faces:
            pf.AddPolygon([plist[i] for i in f])
        return pf, bool(pf.IsClosedByEdgePairing())

    def add_mesh(self, vertices, faces, level_id, color, weight):
        pf, closed = self._indexed_polyface(vertices, faces)
        pf.SetTwoSided(False)
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

    # DGN line strings / shapes hold at most 5000 vertices
    MAX_VERTICES = 5000

    def _point_array(self, points, closed: bool):
        pts = list(points)
        if len(pts) > self.MAX_VERTICES - 1:
            step = len(pts) / float(self.MAX_VERTICES - 2)
            pts = [pts[int(i * step)] for i in range(self.MAX_VERTICES - 2)] + [pts[-1]]
        if closed:
            pts = pts + [pts[0]]
        if DPoint3dArray is None:
            return [self._pt(p) for p in pts]
        arr = DPoint3dArray()
        for p in pts:
            arr.append(self._pt(p))
        return arr

    def _curve_element(self, points, closed: bool, what: str, level_id, color, weight):
        """Line string / shape.  First LineStringHandler/ShapeHandler
        (CreateLineStringElement / CreateShapeElement(eeh, template, DPoint3dArray,
        is3d, modelRef)); if that fails, CurveVector.CreateLinear +
        DraftingElementSchema.ToElement.  Every failure reason is reported."""
        arr = self._point_array(points, closed)
        reasons = []
        eeh = EditElementHandle()
        try:
            if (ShapeHandler if closed else LineStringHandler) is None:
                raise BackendError("handler class not available")
            if closed:
                st = ShapeHandler.CreateShapeElement(eeh, None, arr, True, self.model_ref)
            else:
                st = LineStringHandler.CreateLineStringElement(eeh, None, arr, True, self.model_ref)
            if _ok(st):
                return self._finish(eeh, st, what, level_id, color, weight)
            reasons.append("handler status %s" % st)
        except Exception as e:
            reasons.append("handler: %s" % e)
        try:
            bt = CurveVector.BoundaryType.eBOUNDARY_TYPE_Outer if closed else CurveVector.BoundaryType.eBOUNDARY_TYPE_Open
            cv = CurveVector.CreateLinear(arr, bt, False)
            eeh = EditElementHandle()
            st = DraftingElementSchema.ToElement(eeh, cv, None, True, self.model_ref)
            if _ok(st):
                return self._finish(eeh, st, what, level_id, color, weight)
            reasons.append("CurveVector status %s" % st)
        except Exception as e:
            reasons.append("CurveVector: %s" % e)
        raise BackendError("%s (%d points) could not be created: %s" % (what, len(arr), "; ".join(reasons)))

    def add_linestring(self, points, level_id, color, weight):
        return self._curve_element(points, False, "line string", level_id, color, weight)

    def add_shape(self, points, level_id, color, weight):
        return self._curve_element(points, True, "shape", level_id, color, weight)

    def element_id(self, element) -> int:
        return int(element.GetElementId())

    # ------------------------------------------------------------------ cells
    def add_cell(self, name: str, children: List[Any], level_id: int, add: bool = True):
        """Named (orphan) cell with the given element handles as children
        (NormalCellHeaderHandler.CreateOrphanCellElement + AddChildElement +
        AddChildComplete).  Children are created with ``hold_elements = True``;
        a cell that is itself a child is created with ``add=False``."""
        eeh = EditElementHandle()
        st = NormalCellHeaderHandler.CreateOrphanCellElement(eeh, name, True, self.model_ref)
        if not _ok(st):
            raise BackendError("CreateOrphanCellElement failed for %s (status %s)" % (name, st))
        for ch in children:
            st = NormalCellHeaderHandler.AddChildElement(eeh, ch)
            if not _ok(st):
                raise BackendError("AddChildElement failed in %s (status %s)" % (name, st))
        st = NormalCellHeaderHandler.AddChildComplete(eeh)
        if not _ok(st):
            raise BackendError("AddChildComplete failed for %s (status %s)" % (name, st))
        setter = ElementPropertiesSetter()
        setter.SetLevel(int(level_id))
        setter.Apply(eeh)
        if add:
            st = eeh.AddToModel()
            if not _ok(st):
                raise BackendError("AddToModel failed for cell %s (status %s)" % (name, st))
        return eeh

    def for_each_cell_child(self, cell, fn) -> int:
        """Calls ``fn(index, child_handle)`` for the direct children of a cell in
        the model (used to attach Item Types to the children).  The iterator
        object is reused by ToNext(), so the handle is only valid inside fn."""
        n = 0
        it = ChildEditElemIter(cell, ExposeChildrenReason.eEdit)
        while it is not None and it.IsValid():
            fn(n, it)
            n += 1
            it = it.ToNext()
        return n

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

    def get_item_value(self, element, library: str, item_type: str, prop: str):
        """Value of one Item Type property on an element (None if not attached)."""
        inst = CustomItemHost(element, False).GetCustomItem(library, item_type)
        if inst is None:
            return None
        v = ECValue()
        inst.GetValue(v, prop)
        return None if v.IsNull() else str(v.GetString())

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
