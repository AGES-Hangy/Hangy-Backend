import importlib
import pkgutil
from types import ModuleType
from typing import Any


def load_child_exports(package_name: str, namespace: dict[str, Any]) -> None:
    package = importlib.import_module(package_name)
    exported_names = {name for name in namespace if name != "load_child_exports"}

    for module_info in pkgutil.iter_modules(package.__path__):
        if module_info.name.startswith("_"):
            continue

        module = importlib.import_module(f"{package_name}.{module_info.name}")
        exported_names.update(_export_module(module, module_info.name, namespace))

    namespace["__all__"] = sorted(
        name for name in exported_names if not name.startswith("_")
    )


def _export_module(
    module: ModuleType,
    module_name: str,
    namespace: dict[str, Any],
) -> set[str]:
    names = getattr(module, "__all__", None)
    if names is None:
        names = (name for name in vars(module) if not name.startswith("_"))

    exported_names = set[str]()
    for name in names:
        value = getattr(module, name, None)
        if value is None:
            continue

        if name == "router":
            alias = f"{module_name}_router"
            namespace[alias] = value
            exported_names.add(alias)

        if name not in namespace:
            namespace[name] = value
            exported_names.add(name)
        elif namespace[name] is not value:
            alias = f"{module_name}_{name}"
            namespace[alias] = value
            exported_names.add(alias)

    return exported_names
