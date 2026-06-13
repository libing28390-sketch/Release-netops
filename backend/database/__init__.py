import sys
import types
from . import core
from . import schema

__all__ = [
    'DB_PATH',
    'PROJECT_ROOT',
    'BACKEND_DIR',
    'get_db_connection',
    '_USE_PG',
    '_SERIAL_PK',
    '_JSON_ARRAY_FN',
    'init_db',
    '_table_columns',
    '_table_columns_deprecated',
    '_db_initialized',
    '_pool',
    'fetch_interface_data'
]

# Map attributes to their source modules
_ATTR_MAP = {
    'DB_PATH': core,
    'PROJECT_ROOT': core,
    'BACKEND_DIR': core,
    'get_db_connection': core,
    '_USE_PG': core,
    '_SERIAL_PK': core,
    '_JSON_ARRAY_FN': core,
    '_pool': core,
    'fetch_interface_data': core,
    'init_db': schema,
    '_table_columns': schema,
    '_table_columns_deprecated': schema,
    '_db_initialized': schema
}

class _DatabaseModule(types.ModuleType):
    def __getattr__(self, name):
        if name in _ATTR_MAP:
            return getattr(_ATTR_MAP[name], name)
        raise AttributeError(f"module {__name__} has no attribute {name}")

    def __setattr__(self, name, value):
        if name in _ATTR_MAP:
            setattr(_ATTR_MAP[name], name, value)
        else:
            super().__setattr__(name, value)

sys.modules[__name__].__class__ = _DatabaseModule


