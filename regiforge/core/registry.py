from __future__ import annotations

import importlib
import pkgutil
import sys
from typing import Any

from .base import CaptchaProvider, EmailProvider, ExportProvider, ProxyProvider, RegistrationProject, SmsProvider, VerificationProvider
from .paths import ROOT


class Registry:
    def __init__(self) -> None:
        self.projects: dict[str, RegistrationProject] = {}
        self.captchas: dict[str, CaptchaProvider] = {}
        self.emails: dict[str, EmailProvider] = {}
        self.proxies: dict[str, ProxyProvider] = {}
        self.sms: dict[str, SmsProvider] = {}
        self.verifiers: dict[str, VerificationProvider] = {}
        self.exporters: dict[str, ExportProvider] = {}
        self._loaded = False

    def load(self, force: bool = False) -> None:
        if self._loaded and not force:
            return
        self.projects.clear()
        self.captchas.clear()
        self.emails.clear()
        self.proxies.clear()
        self.sms.clear()
        self.verifiers.clear()
        self.exporters.clear()

        root = str(ROOT)
        if root not in sys.path:
            sys.path.insert(0, root)

        self._load_package_attrs("projects", RegistrationProject, self.projects, attr="PROJECT", key_fn=lambda o: o.id, only_suffixes=(".project",))
        self._load_package_attrs("captcha", CaptchaProvider, self.captchas, attr="PROVIDER", key_fn=lambda o: f"{o.type}.{o.id}" if o.type else o.id, only_suffixes=(".provider",))
        self._load_package_attrs("mailsys", EmailProvider, self.emails, attr="PROVIDER", key_fn=lambda o: o.id, only_suffixes=(".provider",))
        self._load_package_attrs("proxy", ProxyProvider, self.proxies, attr="PROVIDER", key_fn=lambda o: o.id, only_suffixes=(".provider",))
        self._load_package_attrs("sms", SmsProvider, self.sms, attr="PROVIDER", key_fn=lambda o: o.id, only_suffixes=(".provider",))
        self._load_package_attrs("verify", VerificationProvider, self.verifiers, attr="PROVIDER", key_fn=lambda o: o.id, only_suffixes=(".provider",))
        self._load_package_attrs("export", ExportProvider, self.exporters, attr="PROVIDER", key_fn=lambda o: o.id, only_suffixes=(".provider",))
        self._loaded = True

    def _load_package_attrs(self, package_name: str, cls: type, bucket: dict, attr: str, key_fn, only_suffixes: tuple[str, ...] | None = None) -> None:
        try:
            package = importlib.import_module(package_name)
        except Exception as exc:
            print(f"[registry] 无法导入 {package_name}: {exc}")
            return
        if not hasattr(package, "__path__"):
            return

        skip_parts = (".base", ".reader", ".deploy", "._flow", "._rpa", ".STEPS", ".steps.")
        for modinfo in pkgutil.walk_packages(package.__path__, package_name + "."):
            name = modinfo.name
            if any(part in name for part in skip_parts) or (only_suffixes and not name.endswith(only_suffixes)):
                continue
            try:
                mod = importlib.import_module(name)
            except Exception as exc:
                print(f"[registry] skip {name}: {exc}")
                continue
            obj = getattr(mod, attr, None)
            if isinstance(obj, cls):
                bucket[key_fn(obj)] = obj

    def meta(self) -> dict[str, Any]:
        from .project_ui import load_provider_ui_schema

        self.load()
        return {
            "projects": [p.meta() for p in self.projects.values()],
            "captchas": [c.meta() for c in self.captchas.values()],
            "emails": [e.meta() for e in self.emails.values()],
            "proxies": [p.meta() for p in self.proxies.values()],
            "sms": [s.meta() for s in self.sms.values()],
            "verifiers": [v.meta() for v in self.verifiers.values()],
            "exporters": [e.meta() for e in self.exporters.values()],
            "provider_ui": load_provider_ui_schema(),
        }

    def get_project(self, project_id: str) -> RegistrationProject:
        self.load()
        if project_id not in self.projects:
            raise KeyError(f"未知注册项目: {project_id}")
        return self.projects[project_id]

    def get_captcha(self, captcha_id: str) -> CaptchaProvider:
        self.load()
        if captcha_id not in self.captchas:
            raise KeyError(f"未知验证码服务: {captcha_id}")
        return self.captchas[captcha_id]

    def get_email(self, email_id: str) -> EmailProvider:
        self.load()
        if email_id not in self.emails:
            raise KeyError(f"未知邮箱服务: {email_id}")
        return self.emails[email_id]

    def get_proxy(self, proxy_id: str) -> ProxyProvider:
        self.load()
        if proxy_id not in self.proxies:
            raise KeyError(f"未知代理服务: {proxy_id}")
        return self.proxies[proxy_id]

    def get_sms(self, sms_id: str) -> SmsProvider:
        self.load()
        if sms_id not in self.sms:
            raise KeyError(f"未知短信服务: {sms_id}")
        return self.sms[sms_id]

    def get_verifier(self, verifier_id: str) -> VerificationProvider:
        self.load()
        if verifier_id not in self.verifiers:
            raise KeyError(f"未知验证服务: {verifier_id}")
        return self.verifiers[verifier_id]

    def get_exporter(self, exporter_id: str) -> ExportProvider:
        self.load()
        if exporter_id not in self.exporters:
            raise KeyError(f"未知导出服务: {exporter_id}")
        return self.exporters[exporter_id]


_REGISTRY = Registry()


def get_registry() -> Registry:
    return _REGISTRY
