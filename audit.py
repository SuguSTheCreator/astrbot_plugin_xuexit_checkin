"""操作留痕：append-only JSONL。

设计取向：留痕失败不能挡住主流程——所有异常吞掉并返回 False。
超过 MAX_BYTES 轮转成 .1，只留最近一代（自用场景够用）。
"""
import json
import os
import time
from pathlib import Path

#: 单文件上限，超过就轮转
MAX_BYTES = 512 * 1024


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)

    def write(self, action, actor="system", target="", detail="", ok=True):
        """记一条。永不抛异常。"""
        record = {
            "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
            "action": str(action or "")[:60],
            "actor": str(actor or "")[:80],
            "target": str(target or "")[:120],
            "detail": str(detail or "")[:300],
            "ok": bool(ok),
        }
        try:
            self._rotate()
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(record, ensure_ascii=False) + "\n")
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
            return True
        except Exception:
            return False

    def _rotate(self):
        try:
            if self.path.exists() and self.path.stat().st_size > MAX_BYTES:
                os.replace(str(self.path), str(self.path) + ".1")
        except Exception:
            pass

    def tail(self, limit=20):
        """最近 limit 条，新的在前；坏行跳过。"""
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except Exception:
            return []
        out = []
        for line in reversed(lines):
            if len(out) >= limit:
                break
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except Exception:
                continue
            if isinstance(item, dict):
                out.append(item)
        return out

    def count(self):
        try:
            return sum(
                1 for line in self.path.read_text(encoding="utf-8").splitlines() if line.strip()
            )
        except Exception:
            return 0
