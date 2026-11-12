from __future__ import annotations

import smtplib
import ssl as ssl_module
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any

from .auth import validate_email
from .grs_provider import CredentialManager
from .storage import JobStore, now


class MailProviderError(RuntimeError):
    """SMTP 配置无效或发信失败。"""


SECURITY_CHOICES = ("ssl", "starttls", "none")
DEFAULT_SECURITY = "ssl"
DEFAULT_FROM_NAME = "ZLY AI Studio"


def normalize_security(value: str) -> str:
    text = (value or "").strip().lower()
    return text if text in SECURITY_CHOICES else DEFAULT_SECURITY


class MailProviderService:
    """管理设置里的 SMTP 发件服务：为「忘记密码」提供验证码邮件通道。"""

    def __init__(self, store: JobStore, credential_key: str | None) -> None:
        self.store = store
        self.credentials = CredentialManager(credential_key)

    # -- 配置读取 ----------------------------------------------------------

    def _config(self) -> dict[str, Any]:
        return self.store.get_mail_settings()

    def password(self) -> str | None:
        return self.credentials.decrypt(self._config().get("password_encrypted"))

    def reveal_secret(self, field: str) -> str | None:
        if field != "password":
            raise ValueError("邮件服务只支持复制 SMTP 密码")
        return self.password()

    def availability(self) -> tuple[bool, str | None]:
        config = self._config()
        if not config.get("enabled"):
            return False, "邮件服务尚未启用，请联系超级管理员在「管理设置 → 邮件服务」配置。"
        if not str(config.get("host") or "").strip():
            return False, "SMTP 服务器地址未配置。"
        if not str(config.get("from_address") or "").strip():
            return False, "发件人邮箱未配置。"
        if str(config.get("username") or "").strip() and not self.password():
            return False, "SMTP 登录密码未配置或无法解密。"
        return True, None

    def public_config(self) -> dict[str, Any]:
        config = self._config()
        available, _ = self.availability()
        return {
            "enabled": bool(config["enabled"]),
            "host": str(config.get("host") or ""),
            "port": int(config.get("port") or 465),
            "security": normalize_security(str(config.get("security") or "")),
            "username": str(config.get("username") or ""),
            "from_address": str(config.get("from_address") or ""),
            "from_name": str(config.get("from_name") or DEFAULT_FROM_NAME),
            "has_password": bool(self.password()),
            "credential_ready": self.credentials.ready,
            "configured": available,
            "last_test_status": config.get("last_test_status"),
            "last_test_message": config.get("last_test_message"),
            "last_test_at": config.get("last_test_at"),
        }

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        host = str(payload.get("host") or "").strip()
        if not host:
            raise ValueError("SMTP 服务器地址不能为空")
        try:
            port = int(payload.get("port") or 465)
        except (TypeError, ValueError) as error:
            raise ValueError("SMTP 端口必须是数字") from error
        if not 1 <= port <= 65535:
            raise ValueError("SMTP 端口范围应为 1-65535")
        from_address = validate_email(str(payload.get("from_address") or ""))
        values: dict[str, Any] = {
            "enabled": bool(payload.get("enabled", True)),
            "host": host,
            "port": port,
            "security": normalize_security(str(payload.get("security") or "")),
            "username": str(payload.get("username") or "").strip(),
            "from_address": from_address,
            "from_name": str(payload.get("from_name") or DEFAULT_FROM_NAME).strip() or DEFAULT_FROM_NAME,
        }
        password = payload.get("password")
        if password is not None and str(password).strip():
            if not self.credentials.ready:
                raise ValueError(self.credentials.error or "凭证主密钥不可用")
            values["password_encrypted"] = self.credentials.encrypt(str(password).strip())
        self.store.update_mail_settings(**values)
        return self.public_config()

    # -- 发信 --------------------------------------------------------------

    def _open_connection(self, config: dict[str, Any], *, password: str, timeout: float) -> smtplib.SMTP:
        host = str(config.get("host") or "").strip()
        port = int(config.get("port") or 465)
        security = normalize_security(str(config.get("security") or ""))
        username = str(config.get("username") or "").strip()
        if security == "ssl":
            server: smtplib.SMTP = smtplib.SMTP_SSL(
                host, port, timeout=timeout, context=ssl_module.create_default_context(),
            )
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)
            server.ehlo()
            if security == "starttls":
                server.starttls(context=ssl_module.create_default_context())
                server.ehlo()
        if username:
            server.login(username, password)
        return server

    def send(self, *, to: str, subject: str, text: str, html: str | None = None) -> None:
        available, reason = self.availability()
        if not available:
            raise MailProviderError(reason or "邮件服务不可用")
        config = self._config()
        from_address = str(config.get("from_address") or "").strip()
        from_name = str(config.get("from_name") or "").strip()
        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = formataddr((from_name, from_address)) if from_name else from_address
        message["To"] = to
        message.set_content(text)
        if html:
            message.add_alternative(html, subtype="html")
        try:
            server = self._open_connection(config, password=self.password() or "", timeout=30)
            try:
                server.send_message(message)
            finally:
                try:
                    server.quit()
                except smtplib.SMTPException:
                    server.close()
        except MailProviderError:
            raise
        except (smtplib.SMTPException, OSError, ssl_module.SSLError, TimeoutError) as error:
            raise MailProviderError(f"发送邮件失败：{error}") from error

    def send_password_reset(
        self, *, to: str, code: str, display_name: str | None = None, ttl_minutes: int = 15,
    ) -> None:
        greeting = f"{display_name} 你好，" if display_name else "你好，"
        subject = "【ZLY AI Studio】重置密码验证码"
        text = (
            f"{greeting}\n\n"
            f"你正在重置 ZLY AI Studio 创作工作台账号的登录密码，本次验证码为：{code}\n"
            f"该验证码 {ttl_minutes} 分钟内有效，请勿转发或泄露给他人。\n\n"
            "如果这不是你本人的操作，请忽略本邮件，你的密码不会发生变化。\n"
        )
        html = (
            f"<p>{greeting}</p>"
            "<p>你正在重置 ZLY AI Studio 创作工作台账号的登录密码，本次验证码为："
            f"<strong style=\"font-size:20px;letter-spacing:2px\">{code}</strong></p>"
            f"<p>该验证码 {ttl_minutes} 分钟内有效，请勿转发或泄露给他人。</p>"
            "<p style=\"color:#6b7280\">如果这不是你本人的操作，请忽略本邮件，你的密码不会发生变化。</p>"
        )
        self.send(to=to, subject=subject, text=text, html=html)

    def test(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        config = self._config()
        merged = dict(config)
        if payload:
            merged.update({key: value for key, value in payload.items() if value is not None})
        host = str(merged.get("host") or "").strip()
        if not host:
            raise ValueError("SMTP 服务器地址不能为空")
        try:
            port = int(merged.get("port") or 465)
        except (TypeError, ValueError) as error:
            raise ValueError("SMTP 端口必须是数字") from error
        merged["host"] = host
        merged["port"] = port
        submitted = (payload or {}).get("password")
        password = (
            submitted.strip()
            if isinstance(submitted, str) and submitted.strip()
            else (self.password() or "")
        )
        test_time = now()
        try:
            server = self._open_connection(merged, password=password, timeout=15)
            try:
                server.noop()
            finally:
                try:
                    server.quit()
                except smtplib.SMTPException:
                    server.close()
            status, message = "成功", f"已连接 {host}:{port}（{normalize_security(str(merged.get('security') or ''))}）"
        except Exception as error:  # noqa: BLE001 - 任意 SMTP/网络异常都要回显给管理员
            status, message = "失败", str(error)
        self.store.update_mail_settings(
            last_test_status=status, last_test_message=message, last_test_at=test_time,
        )
        if status != "成功":
            raise MailProviderError(f"邮件服务连接测试失败：{message}")
        return self.public_config()
