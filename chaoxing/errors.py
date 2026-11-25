"""异常类型：带 stage，方便告诉用户卡在哪一步。"""


class ChaoxingError(Exception):
    stage = "unknown"
    retryable = False

    def __init__(self, message, detail=None):
        super().__init__(message)
        self.message = message
        self.detail = detail

    def __str__(self):
        return self.message


class ConfigError(ChaoxingError):
    stage = "config"


class CookieExpiredError(ChaoxingError):
    stage = "cookie"


class CheckCodeError(ChaoxingError):
    stage = "checkCode"


class FormChangedError(ChaoxingError):
    stage = "form"


class SubmitError(ChaoxingError):
    stage = "submit"


class AlreadySubmitted(ChaoxingError):
    """今天已经提交过（每日限 1 次）。不是失败，目标已达成。"""
    stage = "already"


class NetworkError(ChaoxingError):
    stage = "network"
    retryable = True
