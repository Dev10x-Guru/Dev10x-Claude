"""Old dotted paths for code moved into a plugin namespace (ADR-0034 Stage A).

Stage A moves modules with ``git mv`` and keeps the old path importable.
A star-import shim would hand ``mock.patch`` a copy, and pointing the old
package's ``__path__`` at the new directory would load every module twice.
Both break shared module state such as the ``cwd_resolver`` seam, so the
old names resolve to the very module objects the new path loads.

A package that keeps some modules at the old path (one owned by another
namespace) uses ``alias_submodules``: the old package stays a real
package, moved names resolve to the new modules, and a name the new
package lacks falls through to the old directory.
"""

from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import importlib.util
import sys
from collections.abc import Sequence
from types import ModuleType


class _ExistingModuleLoader(importlib.abc.Loader):
    def __init__(self, *, target: str) -> None:
        self._target = target
        self._original_spec: importlib.machinery.ModuleSpec | None = None

    def create_module(self, spec: importlib.machinery.ModuleSpec) -> ModuleType:
        module = importlib.import_module(self._target)
        self._original_spec = module.__spec__
        return module

    def exec_module(self, module: ModuleType) -> None:
        module.__spec__ = self._original_spec


class PackageAlias(importlib.abc.MetaPathFinder):
    def __init__(self, *, old: str, new: str) -> None:
        self.old = old
        self.new = new

    def target_of(self, *, fullname: str) -> str | None:
        if not fullname.startswith(f"{self.old}."):
            return None
        return f"{self.new}{fullname[len(self.old) :]}"

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        new_name = self.target_of(fullname=fullname)
        if new_name is None or importlib.util.find_spec(new_name) is None:
            return None
        return importlib.machinery.ModuleSpec(
            fullname,
            _ExistingModuleLoader(target=new_name),
        )


def alias_submodules(*, old: str, new: str) -> None:
    if not any(isinstance(finder, PackageAlias) and finder.old == old for finder in sys.meta_path):
        sys.meta_path.insert(0, PackageAlias(old=old, new=new))


def alias_package(*, old: str, new: str) -> ModuleType:
    alias_submodules(old=old, new=new)
    package = importlib.import_module(new)
    sys.modules[old] = package
    return package


def alias_module(*, old: str, new: str) -> ModuleType:
    module = importlib.import_module(new)
    sys.modules[old] = module
    return module


__all__ = ["PackageAlias", "alias_module", "alias_package", "alias_submodules"]
