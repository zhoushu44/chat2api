"""Microsoft FunCaptcha 浏览器内按压验证 Provider。

Microsoft 注册（Outlook / Live 账号）的 "验证质询" 按压验证码
（accessibility challenge，iframe#enforcementFrame 内）无法用 API 求解，
只能在有头浏览器内模拟真人点击按压。本 Provider 复用注册项目传入的
Humanizer 平滑点击，自动重试直到挑战通过或达到最大次数。
"""
from .provider import PROVIDER

__all__ = ["PROVIDER"]
