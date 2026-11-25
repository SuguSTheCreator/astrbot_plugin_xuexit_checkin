"""本地状态：记录是否已提交、最近一次结果（防重复提交）。"""
import json
import os

from .models import beijing_now


class StateStore:
    def __init__(self, path):
        self.path = path or "state.json"

    def load(self):
        if not self.path or not os.path.exists(self.path):
            return {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def save(self, data):
        if not self.path:
            return
        folder = os.path.dirname(os.path.abspath(self.path))
        if folder and not os.path.isdir(folder):
            os.makedirs(folder, exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self.path)

    def already_done(self, date_str):
        return bool(self.load().get("last_success_date") == date_str)

    def mark_success(self, date_str, result):
        data = self.load()
        data["last_success_date"] = date_str
        data["last_result"] = result
        data["updated_at"] = beijing_now().strftime("%Y-%m-%d %H:%M:%S")
        self.save(data)
