"""从表单页网址里抠参数（面板「解析并保存」与自检共用这一套别名）。"""

#: 详情页里 applyenc 才是页面 enc；enc 是记录标识，别搞反
ALIASES = {
    "form_id": ("formId", "form_id", "id"),
    "enc": ("applyenc", "enc", "formEnc"),
    "fid_enc": ("fidEnc", "fid_enc", "enc2"),
    "state_fid": ("stateFid", "state_fid", "state"),
}


def parse_form_url(url):
    """返回 (参数 dict, 警告列表)。缺的参数值为空串。"""
    from urllib.parse import parse_qs, urlparse

    text = str(url or "").strip()
    query = parse_qs(urlparse(text).query, keep_blank_values=True)
    found = {}
    for field, names in ALIASES.items():
        value = ""
        for name in names:
            for key, values in query.items():
                if key.lower() == name.lower() and values and values[0].strip():
                    value = values[0].strip()
                    break
            if value:
                break
        found[field] = value

    warnings = []
    lower = text.lower()
    if "detail.html" in lower and "applyenc" not in lower:
        warnings.append("这是「查看详情」的网址但没有 applyenc，enc 可能是记录标识，提交会失败")
    if "passport2" in lower:
        warnings.append("这是登录页网址，不是表单页")
    return found, warnings
