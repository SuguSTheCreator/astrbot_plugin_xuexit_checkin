"""配置结构迁移（纯逻辑，不依赖 AstrBot，便于测试）。

AstrBot 自己会按 _conf_schema.json 给新增键补默认值（实测 40 个键都在），
但它**不会搬运改过名的旧键**：不登记映射，老用户填的值会静默失效。
这里只负责它不管的那部分。
"""
from typing import Dict, Tuple

#: 配置结构版本。改键名时 +1，并在 LEGACY_CONFIG_KEYS 里登记映射。
CONFIG_SCHEMA_VERSION = 2

#: 旧键名 → 现键名。目前没有历史改名；以后改名必须在这里加一行。
LEGACY_CONFIG_KEYS: Dict[str, str] = {}

_EMPTY: Tuple[object, ...] = (None, "", [])


def migrate(config):
    """就地迁移 dict-like 配置。返回 (搬运说明列表, 是否需要保存)。"""
    try:
        current = int(config.get("CONFIG_SCHEMA_VERSION", 0) or 0)
    except (TypeError, ValueError):
        current = 0
    if current >= CONFIG_SCHEMA_VERSION:
        return [], False

    moved = []
    for old, new in LEGACY_CONFIG_KEYS.items():
        value = config.get(old)
        if value not in _EMPTY and config.get(new) in _EMPTY:
            config[new] = value
            moved.append(old + "→" + new)

    config["CONFIG_SCHEMA_VERSION"] = CONFIG_SCHEMA_VERSION
    return moved, True
