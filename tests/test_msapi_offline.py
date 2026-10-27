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
