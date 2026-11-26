"""表单模板处理：构造 formIdValueData。"""
import json

from .errors import ConfigError


def parse_location(value):
    """把 "lat,lng,address" 解析成 dict；address 允许包含逗号。"""
    if not value:
        return None
    parts = [part.strip() for part in value.split(",", 2)]
    if len(parts) < 2:
        raise ConfigError("LOCATION 格式应为 lat,lng,address", detail=value)
    try:
        lat = float(parts[0])
        lng = float(parts[1])
    except ValueError as exc:
        raise ConfigError("LOCATION 的 lat/lng 必须是数字", detail=value) from exc
    address = parts[2] if len(parts) > 2 else ""
    return {"lat": lat, "lng": lng, "address": address}


def build_form_data(template, location=None):
    """根据模板构造 formIdValueData 字符串（返回紧凑 JSON）。"""
    if isinstance(template, str):
        text = template.strip()
        if not text:
            raise ConfigError("FORM_TEMPLATE 为空：请用 F12 抓包填入 formIdValueData")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ConfigError("FORM_TEMPLATE 不是合法 JSON", detail=str(exc)) from exc
    elif isinstance(template, dict):
        data = template
    else:
        raise ConfigError("FORM_TEMPLATE 类型错误")

    if not isinstance(data, dict) or not data:
        raise ConfigError("FORM_TEMPLATE 必须是非空 JSON 对象")

    loc = parse_location(location) if isinstance(location, str) else location
    if loc:
        _inject_location(data, loc)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def _inject_location(data, loc):
    for field in data.values():
        if not isinstance(field, dict) or field.get("compt") != "location":
            continue
        groups = field.get("groupValues") or []
        if groups and isinstance(groups[0], dict):
            groups[0]["values"] = [[{
                "lat": loc["lat"],
                "lng": loc["lng"],
                "address": loc["address"],
            }]]
