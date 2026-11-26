"""超星表单协议核心包（纯 Python 3.8+，不依赖 AstrBot）。"""

from .client import ChaoxingClient
from .errors import (
    ChaoxingError,
    CheckCodeError,
    ConfigError,
    CookieExpiredError,
    FormChangedError,
    NetworkError,
    SubmitError,
)
from .forms import build_form_data, parse_location
from .models import CheckinConfig, CheckinResult
from .qrlogin import QrLoginError, QrLoginSession
from .runner import (
    AccountOutcome,
    load_accounts,
    load_accounts_dir,
    merge_account,
    run_all,
)
from .service import run_once
from .state import StateStore

__all__ = [
    "ChaoxingClient",
    "ChaoxingError",
    "CheckCodeError",
    "ConfigError",
    "CookieExpiredError",
    "FormChangedError",
    "NetworkError",
    "SubmitError",
    "build_form_data",
    "parse_location",
    "CheckinConfig",
    "CheckinResult",
    "QrLoginSession",
    "QrLoginError",
    "AccountOutcome",
    "load_accounts",
    "load_accounts_dir",
    "merge_account",
    "run_all",
    "run_once",
    "StateStore",
]

__version__ = "0.2.0"
