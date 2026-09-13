"""Step 12: 读取邮箱验证码并提交 OTP。"""
from ._flow import set_code_fetcher, set_mail_timeout, step12_verify_email as run

__all__ = ["run", "set_code_fetcher", "set_mail_timeout"]
