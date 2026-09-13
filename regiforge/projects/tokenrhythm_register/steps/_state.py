from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RegistrationState:
    phone: str = ""
    sms_code: str = ""
    api_key: str = ""
