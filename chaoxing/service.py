"""一键执行：取 checkCode -> 构造表单 -> 提交 -> 记录状态。"""
import json
import time

from .client import ChaoxingClient
from .errors import (
    AlreadySubmitted,
    ChaoxingError,
    ConfigError,
    NetworkError,
    SubmitError,
)
from .forms import build_form_data
from .models import CheckinResult, beijing_now
from .state import StateStore


def run_once(config, force=False, notifier=None, client_factory=None):
    if client_factory is None:
        client_factory = ChaoxingClient
    date_str = beijing_now().strftime("%Y-%m-%d")
    store = StateStore(config.state_path)
    result = None
    try:
        if not config.dry_run and not force and store.already_done(date_str):
            result = CheckinResult(
                ok=True,
                stage="skipped",
                message="今天已经成功提交过，跳过",
                skipped=True,
            )
            return result

        client = client_factory(config)
        check_code = _retry(lambda: client.get_check_code(), config)

        fresh = _try_sync(client, config)

        if config.dry_run:
            extra = ""
            if fresh and fresh.get("form_data"):
                extra = "；已自动同步参数（uuid=%s…, enc=%s…）" % (
                    str(fresh.get("uuid"))[:8],
                    str(fresh.get("enc"))[:8],
                )
            result = CheckinResult(
                ok=True,
                stage="dry_run",
                message="dry-run 通过：Cookie 有效，已取到 checkCode" + extra,
                dry_run=True,
                synced=bool(fresh and fresh.get("form_data")),
            )
            return result

        overrides = None
        if fresh and fresh.get("form_data"):
            # 只覆盖 uuid / 模板 / version。
            # enc 用配置里的「页面 enc」：接口返回的是「本次提交记录的 enc」，
            # 每条记录都不一样，不能拿去提交（cx_health_sign 也是用页面 enc）。
            overrides = {
                "uuid": fresh.get("uuid"),
                "version": fresh.get("version"),
            }
        elif not config.uuid or not config.submit_version:
            raise ConfigError("缺少 uuid / submitVersion：请从 F12 抓包后填入配置")

        try:
            template = fresh["form_data"] if (fresh and fresh.get("form_data")) else config.form_template
            form_json = build_form_data(template, config.location)
            payload = _retry(
                lambda: client.submit(check_code, form_json, overrides), config
            )
            stage = "submit_auto" if overrides else "submit"
            message = "提交成功（参数自动同步）" if overrides else "提交成功"
        except (SubmitError, ConfigError) as first_error:
            if not config.fallback_form_data:
                raise
            fallback_code = _retry(lambda: client.get_check_code(), config)
            payload = _retry(
                lambda: client.submit(fallback_code, str(config.fallback_form_data)),
                config,
            )
            stage = "submit_fallback"
            message = "提交成功（备用模板：" + first_error.message + "）"
        result = CheckinResult(
            ok=True,
            stage=stage,
            message=message,
            detail=_short(payload),
            synced=bool(overrides),
        )
        store.mark_success(date_str, result.to_dict())
        return result
    except AlreadySubmitted as exc:
        # 每天只能交一次：超星说"已达上限"，说明今天已经打过了（可能是本人手动打的）。
        # 这不是失败——目标已达成，按成功记，别报警也别重试。
        result = CheckinResult(
            ok=True,
            stage="already",
            message="今天已经提交过（每日限 1 次），按成功处理",
            detail=exc.detail or "",
            skipped=True,
            dry_run=config.dry_run,
        )
        try:
            store.mark_success(date_str, result.to_dict())
        except Exception:
            pass
        return result
    except ChaoxingError as exc:
        result = CheckinResult(
            ok=False,
            stage=exc.stage,
            message=exc.message,
            detail=exc.detail or "",
            dry_run=config.dry_run,
        )
        return result
    except Exception as exc:
        result = CheckinResult(
            ok=False,
            stage="unknown",
            message="未知错误：" + str(exc),
            detail=repr(exc),
            dry_run=config.dry_run,
        )
        return result
    finally:
        if notifier is not None and result is not None:
            try:
                notifier(result)
            except Exception:
                pass


def _try_sync(client, config):
    """尝试拉取本账号上一次提交，用于自动同步参数；失败返回 None。"""
    if not getattr(config, "auto_sync", True):
        return None
    try:
        return client.fetch_last_submission()
    except ChaoxingError:
        return None
    except Exception:
        return None


def _retry(fn, config, attempts=3):
    last = None
    for index in range(attempts):
        try:
            return fn()
        except NetworkError as exc:
            last = exc
            if index < attempts - 1:
                time.sleep(1.5 * (index + 1))
    raise last


def _short(payload):
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(payload)
    return text[:300]