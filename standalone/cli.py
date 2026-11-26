"""命令行入口。

单账号：
    python standalone/cli.py --config config.local.json [--dry-run] [--force] [--json]

多账号：
    python standalone/cli.py --accounts accounts.json [--state-dir state/] [--json]
    python standalone/cli.py --accounts-dir users/ --state-dir state/ [--json]
"""
import argparse
import json
import os
import sys

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adapters.webhook import send_webhook  # noqa: E402
from chaoxing import (  # noqa: E402
    CheckinConfig,
    load_accounts,
    load_accounts_dir,
    run_all,
    run_once,
)


def load_config(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    return CheckinConfig.from_dict(data)


def _run_single(args):
    try:
        config = load_config(args.config)
    except (OSError, ValueError) as exc:
        print("配置加载失败：" + str(exc), file=sys.stderr)
        return 2

    if args.dry_run:
        config.dry_run = True
    result = run_once(config, force=args.force)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(result.to_text())

    if config.webhook_url:
        send_webhook(config.webhook_url, "超星健康打卡", result.to_text())
    return 0 if result.ok else 1


def _run_multi(args):
    try:
        if args.accounts_dir:
            defaults, accounts = load_accounts_dir(args.accounts_dir)
        else:
            defaults, accounts = load_accounts(args.accounts)
    except (OSError, ValueError) as exc:
        print("账号加载失败：" + str(exc), file=sys.stderr)
        return 2

    if not accounts:
        print("账号列表为空", file=sys.stderr)
        return 2

    state_dir = args.state_dir or None
    outcomes = run_all(accounts, defaults, force=args.force, state_dir=state_dir,
                       dry_run=True if args.dry_run else None)

    if args.json:
        print(json.dumps([item.to_dict() for item in outcomes], ensure_ascii=False, indent=2))
    else:
        for item in outcomes:
            print(item.to_text())
        failed = [item for item in outcomes if not item.ok]
        print("")
        print("完成：成功 %d / 共 %d" % (len(outcomes) - len(failed), len(outcomes)))

    webhook_url = str((defaults or {}).get("webhook_url", "") or "")
    if webhook_url:
        lines = [item.to_text() for item in outcomes]
        failed = [item for item in outcomes if not item.ok]
        lines.append("完成：成功 %d / 共 %d" % (len(outcomes) - len(failed), len(outcomes)))
        send_webhook(webhook_url, "健康日报汇总", "\n".join(lines))

    return 0 if all(item.ok for item in outcomes) else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description="超星健康表单自动打卡（CLI）")
    parser.add_argument("--config", help="单账号配置文件（JSON）")
    parser.add_argument("--accounts", help="多账号文件（JSON：defaults + accounts）")
    parser.add_argument("--accounts-dir", help="多账号目录（每个 *.json 一个账号）")
    parser.add_argument("--state-dir", default="", help="状态文件目录（多账号模式）")
    parser.add_argument("--dry-run", action="store_true", help="只检查 Cookie/checkCode，不提交")
    parser.add_argument("--force", action="store_true", help="忽略“今天已提交”状态，强制再跑")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    modes = [bool(args.config), bool(args.accounts), bool(args.accounts_dir)]
    if sum(modes) != 1:
        print("请且只指定一个：--config / --accounts / --accounts-dir", file=sys.stderr)
        return 2

    if args.config:
        return _run_single(args)
    return _run_multi(args)


if __name__ == "__main__":
    raise SystemExit(main())
