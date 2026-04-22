from importlib import import_module

__all__ = ["router"]


def __getattr__(name: str):
    if name == "router":
        return import_module("app.api.services.tenants.route").router
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
