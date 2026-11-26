"""打运行包：只装插件跑起来需要的东西，排除截图/测试/开发配置。

AstrBot 插件市场限制 zip <= 16MB；仓库里截图占 26MB，直接打包会被 CI 拒。
用法：python scripts/package.py [--out dist]
"""
import argparse
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: 运行必需（目录整体收）
INCLUDE_DIRS = ["chaoxing", "adapters", "standalone", "pages", "helper", ".astrbot-plugin"]
#: 运行必需（单文件）
INCLUDE_FILES = [
    "main.py", "webui.py", "policy.py", "audit.py", "config_migrate.py",
    "_conf_schema.json", "metadata.yaml", "requirements.txt",
    "LICENSE", "README.md", "CHANGELOG.md", "CREDITS.md", "config.example.json",
]
#: 文档收 md，不收 screenshots
INCLUDE_DOC_GLOB = "docs/*.md"

EXCLUDE_PARTS = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"}
EXCLUDE_SUFFIX = {".pyc", ".pyo"}


def collect():
    items = []
    for name in INCLUDE_FILES:
        p = ROOT / name
        if p.is_file():
            items.append(p)
    for name in INCLUDE_DIRS:
        base = ROOT / name
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file():
                continue
            if EXCLUDE_PARTS.intersection(p.parts) or p.suffix in EXCLUDE_SUFFIX:
                continue
            items.append(p)
    items.extend(sorted(ROOT.glob(INCLUDE_DOC_GLOB)))
    return items


def read_version():
    text = (ROOT / "metadata.yaml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.startswith("version:"):
            return line.split(":", 1)[1].strip()
    return "0.0.0"


def main(argv=None):
    parser = argparse.ArgumentParser(description="打 AstrBot 插件运行包")
    parser.add_argument("--out", default="dist", help="输出目录")
    args = parser.parse_args(argv)

    version = read_version()
    out_dir = ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    name = "astrbot_plugin_xuexit_checkin-v%s.zip" % version
    target = out_dir / name

    files = collect()
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for p in files:
            zf.write(p, p.relative_to(ROOT).as_posix())

    size = target.stat().st_size
    print("包名：%s" % name)
    print("文件：%d 个" % len(files))
    print("体积：%.2f MB（市场上限 16 MB）" % (size / 1048576))
    if size > 16 * 1048576:
        print("超过市场上限，检查是否误收了大文件", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
