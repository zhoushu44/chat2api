"""NVIDIA Build 注册步骤（按 step 编号）。"""

from ._rpa import PASSWORD, _setup_hcaptcha_route
from ._http_engine import register_http, generate_random_email
from . import step01_open_signin
from . import step02_accept_cookies
from . import step03_email_next
from . import step06_input_password
from . import step07_confirm_password
from . import step08_check_agreement
from . import step09_solve_captcha
from . import step10_inject_token
from . import step11_create_account
from . import step12_verify_email
from . import step13_fetch_apikey

__all__ = [
    "PASSWORD",
    "_setup_hcaptcha_route",
    "register_http",
    "generate_random_email",
    "step01_open_signin",
    "step02_accept_cookies",
    "step03_email_next",
    "step06_input_password",
    "step07_confirm_password",
    "step08_check_agreement",
    "step09_solve_captcha",
    "step10_inject_token",
    "step11_create_account",
    "step12_verify_email",
    "step13_fetch_apikey",
]
