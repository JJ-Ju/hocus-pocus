from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


class CatalogDefinition:
    def __init__(self, path: Path):
        self._path = path

    def libraryFilePath(self):
        return str(self._path)

    def version(self):
        return "1.0"


class CatalogNodeType:
    def __init__(self, definition: CatalogDefinition):
        self._definition = definition

    def name(self):
        return "studio::asset::1.0"

    def nameComponents(self):
        return ("Sop", "studio", "asset", "1.0")

    def aliases(self):
        return ()

    def definition(self):
        return self._definition

    def parmTemplateGroup(self):
        return SimpleNamespace(entries=lambda: ())

    def minNumInputs(self):
        return 1

    def maxNumInputs(self):
        return 1

    def inputNames(self):
        return ("geometry",)

    def inputLabels(self):
        return ("Geometry",)

    def inputDataTypes(self):
        return (("geometry",),)

    def minNumOutputs(self):
        return 1

    def maxNumOutputs(self):
        return 1

    def outputNames(self):
        return ("result",)

    def outputLabels(self):
        return ("Result",)


class CatalogCategory:
    def __init__(self, node_type: CatalogNodeType):
        self._node_type = node_type

    def name(self):
        return "Sop"

    def label(self):
        return "Geometry"

    def nodeTypes(self):
        return {self._node_type.name(): self._node_type}


class CatalogHou:
    def __init__(self, hda_path: Path):
        category = CatalogCategory(CatalogNodeType(CatalogDefinition(hda_path)))
        self._categories = {"Sop": category}

    def nodeTypeCategories(self):
        return self._categories

    def applicationName(self):
        return "Houdini FX"

    def applicationVersion(self):
        return (21, 0, 321)

    def applicationPlatformInfo(self):
        return "windows-x86_64"

    def licenseCategory(self):
        return SimpleNamespace(name=lambda: "Commercial")
