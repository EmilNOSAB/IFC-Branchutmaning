"""Offline checks of msapi helpers that depend on how the MSPy bindings name things."""
import microstation.msapi as msapi


def test_property_types_with_e_prefix(monkeypatch):
    # dir(CustomProperty) reported by MicroStation 2025: members eString, eBoolean, ... on the class
    class FakeEnum:
        pass

    class FakeCustomProperty:
        Type = FakeEnum
        Type1 = FakeEnum
        eString, eBoolean, eDouble, eInteger = "S", "B", "D", "I"

    monkeypatch.setattr(msapi, "CustomProperty", FakeCustomProperty, raising=False)
    assert msapi.property_types() == {"String": "S", "Boolean": "B", "Double": "D", "Integer": "I"}


def test_property_types_without_prefix(monkeypatch):
    class FakeEnum:
        String, Boolean, Double, Integer = 1, 2, 3, 4

    class FakeCustomProperty:
        Type = FakeEnum

    monkeypatch.setattr(msapi, "CustomProperty", FakeCustomProperty, raising=False)
    assert msapi.property_types()["Boolean"] == 2


def test_imports_survive_missing_optional_symbols(monkeypatch):
    """One class in an unexpected module must not break the other imports
    (first MicroStation run: NameError WString after a failed block import)."""
    import importlib
    import sys
    import types
    names = {"MSPyBentley": ["WString"],
             "MSPyBentleyGeom": ["CurveVector", "DgnBoxDetail", "DPoint3d", "DVec3d", "ISolidPrimitive",
                                 "PolyfaceHeader", "DPoint3dArray"],
             "MSPyECObjects": ["ECValue"],
             "MSPyDgnPlatform": ["BaseGCS", "ConfigurationManager", "CustomItemHost", "CustomProperty", "DgnGCS",
                                 "DraftingElementSchema", "EditElementHandle", "ElementPropertiesSetter",
                                 "ItemTypeLibrary", "NamedGroup", "NamedGroupFlags", "NamedGroupMemberFlags"],
             "MSPyMstnPlatform": ["ISessionMgr", "PyCadInputQueue"]}
    for mod, syms in names.items():
        m = types.ModuleType(mod)
        for s in syms:
            setattr(m, s, type(s, (), {}))
        monkeypatch.setitem(sys.modules, mod, m)
    import microstation.msapi as msapi
    try:
        msapi = importlib.reload(msapi)
        assert msapi.MICROSTATION_AVAILABLE and msapi.IMPORT_ERROR is None
        assert msapi.WString is not None
        assert set(msapi.MISSING_SYMBOLS) == set(msapi.OPTIONAL) - {"DPoint3dArray"}
    finally:
        monkeypatch.undo()
        importlib.reload(msapi)


def test_dgnlib_candidates_from_configuration_values():
    """IFC_Classes_Types.dgnlib is found from configuration variable values
    (values as reported by the user's MicroStation 2026), no fixed path."""
    from microstation.msapi import dgnlib_candidates
    msdir = "C:\\Program Files\\Bentley\\MicroStation 2026\\MicroStation\\"
    dgnliblist = msdir + "Default\\dgnlib\\*.dgnlib;" + msdir + "Default\\dgnlib\\DrawComp\\*.dgnlib"
    c = dgnlib_candidates("IFC_Classes_Types.dgnlib", ["", dgnliblist, msdir])
    assert msdir + "Default\\dgnlib\\ItemTypes\\IFC_Classes_Types.dgnlib" in c
    assert msdir.rstrip("\\") + "\\Default\\Dgnlib\\ItemTypes\\IFC_Classes_Types.dgnlib" in c
    assert len(c) == len(set(c))


def test_picklist_matching():
    from microstation.assign_metadata import match_picklist
    assert match_picklist("IFC4X3_ADD2", ["IFC2x3", "IFC4", "IFC4x3"], "version") == ("IFC4x3", True)
    assert match_picklist("IfcRailwayPart", ["IFCRAILWAYPART"], "class") == ("IFCRAILWAYPART", True)
    assert match_picklist("TRACTION_SWITCHING_ASSEMBLY", ["TractionSwitchingAssembly"], "type")[1]
    assert match_picklist("IfcRail", None, "class") == ("IfcRail", True)
    assert match_picklist("IfcRail", ["IfcWall"], "class") == ("IfcRail", False)
