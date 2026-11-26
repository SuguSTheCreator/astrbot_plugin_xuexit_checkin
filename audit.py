"""操作留痕：append-only JSONL。

设计取向：留痕失败不能挡住主流程——所有异常吞掉并返回 False。
但「吞掉」不等于「不说」：失败会记日志并累计计数，自检据此标红，
否则就变成「以为记了其实没记」的空壳留痕。
超过 MAX_BYTES 轮转成 .1，只留最近一代（自用场景够用）。
"""
import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger(__name__)

#: 单文件上限，超过就轮转
MAX_BYTES = 512 * 1024


class AuditLog:
    def __init__(self, path):
        self.path = Path(path)
        #: 写失败次数与最近原因；自检读它们
        self.write_failures = 0
        self.last_error = ""

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
            self.last_error = ""
            return True
        except Exception as exc:
            self.write_failures += 1
            self.last_error = str(exc)
            # 限频：第 1 次和每 20 次说一遍，别把日志刷爆
            if self.write_failures == 1 or self.write_failures % 20 == 0:
                logger.warning("[xuexit] 留痕写入失败 %d 次，最近原因：%s",
                               self.write_failures, exc)
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
