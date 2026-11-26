"""命令行入口。

准备配置（不用面板也能走完整流程）：
    python standalone/cli.py --parse-url "<表单链接>" --out config.local.json
    python standalone/cli.py --login --fid 学校fid --out config.local.json

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
import time

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


def _merge_config(path, updates):
    """把新字段并进已有配置，不覆盖用户填过的其他项。"""
    data = {}
    if path and os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            print("已有配置读不出来，将新建（原文件未改动）", file=sys.stderr)
    data.update({k: v for k, v in updates.items() if v != ""})
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return data


def _parse_url(args):
    """从表单链接抠参数。复用面板那一套别名，不另写一份。"""
    from chaoxing.formlink import parse_form_url

    found, warnings = parse_form_url(args.parse_url)
    for text in warnings:
        print("[warn] " + text)
    print("解析结果：")
    for key, value in found.items():
        print("  %-10s %s" % (key, value or "(缺)"))
    missing = [k for k, v in found.items() if not v]
    if args.out:
        _merge_config(args.out, found)
        print("已写入：" + args.out)
    if missing:
        print("还缺：" + ", ".join(missing) + "（确认复制的是详情页链接）", file=sys.stderr)
        return 1
    return 0


def _login(args):
    """扫码登录拿 Cookie。复用插件侧的 QrLoginSession，不另写一份。"""
    from chaoxing.qrlogin import (
        STATE_CONFIRMED,
        STATE_SCANNED,
        QrLoginError,
        QrLoginSession,
    )

    try:
        qr = QrLoginSession(fid=args.fid or "", proxy=args.proxy or "")
        png = qr.refresh()
    except QrLoginError as exc:
        print("二维码生成失败：" + str(exc), file=sys.stderr)
        print("云服务器出口 IP 常过不了登录环境校验，换本机网络或见 helper/README.md",
              file=sys.stderr)
        return 1

    qr_path = args.qr_out or "qr.png"
    with open(qr_path, "wb") as fh:
        fh.write(png)
    print("二维码已存：" + os.path.abspath(qr_path))
    print("用学习通 App 扫它，然后在手机上点确认。最多等 5 分钟。")

    deadline = time.time() + 300
    seen_scanned = False
    while time.time() < deadline:
        try:
            state = qr.poll()
        except Exception as exc:
            print("轮询失败：" + str(exc), file=sys.stderr)
            return 1
        if state.get("state") == STATE_CONFIRMED:
            cookie = qr.cookie_string()
            print("登录成功：" + (state.get("nickname") or "")
                  + " uid=" + (state.get("uid") or ""))
            if args.out:
                _merge_config(args.out, {"cookie": cookie, "uid": state.get("uid") or ""})
                print("Cookie 已写入：" + args.out)
            else:
                print("cookie=" + cookie)
            return 0
        if state.get("state") == STATE_SCANNED and not seen_scanned:
            seen_scanned = True
            print("已扫码，等手机确认…")
        time.sleep(2)
    print("超时：二维码过期了，重跑一次", file=sys.stderr)
    return 1


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
    parser.add_argument("--parse-url", metavar="URL", help="从表单链接抠出四个参数")
    parser.add_argument("--login", action="store_true", help="扫码登录，把 Cookie 写进配置")
    parser.add_argument("--out", metavar="FILE", help="配合 --parse-url / --login 写入配置文件")
    parser.add_argument("--fid", default="", help="扫码登录用的学校租户 fid")
    parser.add_argument("--proxy", default="", help="扫码登录走的代理，如 http://127.0.0.1:8898")
    parser.add_argument("--qr-out", default="", help="二维码图片保存路径，默认 qr.png")
    args = parser.parse_args(argv)

    if args.parse_url:
        return _parse_url(args)
    if args.login:
        if not args.out:
            print("建议加 --out config.local.json，否则 Cookie 只打印在屏幕上", file=sys.stderr)
        return _login(args)

    modes = [bool(args.config), bool(args.accounts), bool(args.accounts_dir)]
    if sum(modes) != 1:
        print("请且只指定一个：--config / --accounts / --accounts-dir", file=sys.stderr)
        print("准备配置：--parse-url <链接> --out config.local.json，再 --login --out 同一个文件",
              file=sys.stderr)
        return 2

    if args.config:
        return _run_single(args)
    return _run_multi(args)


if __name__ == "__main__":
    raise SystemExit(main())
