from __future__ import annotations

import secrets
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from fastapi import HTTPException
from mcp.server.auth.provider import AccessToken, AuthorizationCode, AuthorizationParams, AuthorizeError, RefreshToken, RegistrationError, TokenError
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .config import ACCESS_TTL, CODE_TTL, REFRESH_TTL, REQUEST_TTL, SCOPES, SCOPE_LABELS, McpConfig
from .store import McpStore, digest


def callback_url(uri: str, **parameters: str | None) -> str:
    parsed = urlsplit(uri)
    query = [(key, value) for key, value in parse_qsl(parsed.query) if key not in {"code", "state", "error", "iss"}]
    query.extend((key, value) for key, value in parameters.items() if value is not None)
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))


def valid_redirect(uri: str) -> bool:
    try:
        parsed = urlsplit(uri)
        _ = parsed.port
        return bool(parsed.hostname and not parsed.fragment and not parsed.username and not parsed.password
                    and (parsed.scheme == "https" or (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"})))
    except ValueError:
        return False


class StudioOAuthProvider:
    """SDK OAuth handlers own protocol validation; this provider owns durable grants.

    The instance keeps no current-user state. Every credential binds client,
    resource, subject and a revocable grant, including after a backend restart.
    """

    def __init__(self, app, config: McpConfig):
        self.app, self.config = app, config

    @property
    def store(self) -> McpStore:
        return self.app.state.mcp_store

    def active_user(self, user_id: str) -> dict | None:
        try:
            user = self.app.state.auth_store.get_user(user_id)
        except KeyError:
            return None
        return user if user["is_active"] and not user["must_change_password"] else None

    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        row = self.store.get("client:" + client_id)
        if not row or row["status"] != "active":
            return None
        data = dict(row["payload"])
        encrypted = data.pop("secret_encrypted", None)
        if encrypted:
            data["client_secret"] = self.app.state.grs_provider.credentials.decrypt(encrypted)
            if not data["client_secret"]:
                return None
        return OAuthClientInformationFull.model_validate(data)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        redirects = [str(uri) for uri in client_info.redirect_uris]
        if not redirects or len(redirects) > 10 or any(not valid_redirect(uri) for uri in redirects):
            raise RegistrationError("invalid_redirect_uri", "回调地址必须是 HTTPS 或本机回环 HTTP 地址")
        if client_info.token_endpoint_auth_method not in {"none", "client_secret_post", "client_secret_basic"}:
            raise RegistrationError("invalid_client_metadata", "不支持的客户端认证方式")
        if any(grant not in {"authorization_code", "refresh_token"} for grant in client_info.grant_types):
            raise RegistrationError("invalid_client_metadata", "仅支持 authorization_code 和 refresh_token")
        if len(client_info.client_name or "") > 120:
            raise RegistrationError("invalid_client_metadata", "客户端名称过长")
        data = client_info.model_dump(mode="json")
        raw_secret = data.pop("client_secret", None)
        if raw_secret:
            credentials = self.app.state.grs_provider.credentials
            if not credentials.ready:
                raise RegistrationError("invalid_client_metadata", "请管理员配置凭证主密钥后重试")
            data["secret_encrypted"] = credentials.encrypt(raw_secret)
        self.store.insert("client:" + client_info.client_id, "client", data)

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        if params.resource != self.config.resource:
            raise AuthorizeError("invalid_target", "授权资源与当前 MCP 地址不一致")
        if str(params.redirect_uri) not in [str(uri) for uri in client.redirect_uris] or not valid_redirect(str(params.redirect_uri)):
            raise AuthorizeError("invalid_request", "回调地址与注册信息不一致")
        scopes = params.scopes or SCOPES
        if not scopes or not set(scopes).issubset(SCOPES):
            raise AuthorizeError("invalid_scope", "请求了不支持的权限")
        request_id = secrets.token_urlsafe(24)
        self.store.insert("request:" + request_id, "request", {
            **params.model_dump(mode="json"), "client_id": client.client_id,
            "client_name": client.client_name or "MCP 客户端", "scopes": scopes,
            "expires_at": time.time() + REQUEST_TTL,
        }, status="pending")
        return self.config.base + "/mcp/authorize?request_id=" + request_id

    def request_details(self, request_id: str, user: dict) -> dict:
        with self.store.transaction() as connection:
            row = self.store.get("request:" + request_id, connection, lock=True)
            self._check_request(row, user)
            if not row["owner_id"]:
                self.store.update(row["id"], owner_id=user["id"], connection=connection)
        return {"request_id": request_id, "client_name": row["payload"]["client_name"],
                "account": user["display_name"], "redirect_uri": row["payload"]["redirect_uri"],
                "scopes": [{"id": scope, "label": SCOPE_LABELS[scope]} for scope in row["payload"]["scopes"]],
                "expires_at": row["payload"]["expires_at"]}

    @staticmethod
    def _check_request(row: dict | None, user: dict) -> None:
        if not row or row["status"] != "pending" or row["payload"]["expires_at"] <= time.time():
            raise HTTPException(410, "授权请求已使用或已过期，请从客户端重新连接")
        if row["owner_id"] and row["owner_id"] != user["id"]:
            raise HTTPException(403, "该授权请求已绑定其他账号，请从客户端重新连接")

    def decide(self, request_id: str, user: dict, allow: bool) -> dict:
        if not self.active_user(user["id"]):
            raise HTTPException(403, "请先启用账号并完成初始密码修改")
        with self.store.transaction() as connection:
            row = self.store.get("request:" + request_id, connection, lock=True)
            self._check_request(row, user)
            data = row["payload"]
            self.store.update(row["id"], status="approved" if allow else "denied", owner_id=user["id"], connection=connection)
            if not allow:
                return {"redirect_url": callback_url(data["redirect_uri"], error="access_denied", state=data.get("state"), iss=self.config.issuer)}
            code = secrets.token_urlsafe(32)
            self.store.insert("code:" + digest(code), "code", {**data, "subject": user["id"], "expires_at": time.time() + CODE_TTL},
                              owner_id=user["id"], connection=connection)
        self.app.state.auth_store.audit("mcp_authorize", "mcp", actor_user_id=user["id"], target_id=data["client_id"])
        return {"redirect_url": callback_url(data["redirect_uri"], code=code, state=data.get("state"), iss=self.config.issuer)}

    async def load_authorization_code(self, client: OAuthClientInformationFull, authorization_code: str) -> AuthorizationCode | None:
        row = self.store.get("code:" + digest(authorization_code))
        if not row or row["status"] != "active" or row["payload"]["client_id"] != client.client_id:
            return None
        return AuthorizationCode(code=authorization_code, **{key: value for key, value in row["payload"].items() if key in AuthorizationCode.model_fields and key != "code"})

    def _issue_tokens(self, grant: dict, connection, scopes: list[str]) -> OAuthToken:
        access, refresh = secrets.token_urlsafe(32), secrets.token_urlsafe(40)
        common = {"client_id": grant["payload"]["client_id"], "scopes": scopes,
                  "resource": self.config.resource, "subject": grant["owner_id"]}
        self.store.insert("access:" + digest(access), "access", {**common, "expires_at": int(time.time()) + ACCESS_TTL},
                          owner_id=grant["owner_id"], parent_id=grant["id"], connection=connection)
        self.store.insert("refresh:" + digest(refresh), "refresh", {**common, "expires_at": grant["payload"]["expires_at"]},
                          owner_id=grant["owner_id"], parent_id=grant["id"], connection=connection)
        return OAuthToken(access_token=access, token_type="Bearer", expires_in=ACCESS_TTL, refresh_token=refresh, scope=" ".join(scopes))

    async def exchange_authorization_code(self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode) -> OAuthToken:
        with self.store.transaction() as connection:
            row = self.store.get("code:" + digest(authorization_code.code), connection, lock=True)
            if not row or row["status"] != "active" or row["payload"]["expires_at"] <= time.time() or row["payload"]["client_id"] != client.client_id:
                raise TokenError("invalid_grant", "授权码已使用或过期")
            if not self.active_user(row["owner_id"]):
                raise TokenError("invalid_grant", "账号不可用")
            self.store.update(row["id"], status="used", connection=connection)
            grant_id = "grant:" + secrets.token_urlsafe(18)
            data = {"client_id": client.client_id, "client_name": client.client_name or "MCP 客户端",
                    "scopes": row["payload"]["scopes"], "resource": self.config.resource,
                    "expires_at": int(time.time()) + REFRESH_TTL, "last_used_at": None}
            self.store.insert(grant_id, "grant", data, owner_id=row["owner_id"], connection=connection)
            return self._issue_tokens({"id": grant_id, "owner_id": row["owner_id"], "payload": data}, connection, data["scopes"])

    async def load_refresh_token(self, client: OAuthClientInformationFull, refresh_token: str) -> RefreshToken | None:
        with self.store.transaction() as connection:
            row = self.store.get("refresh:" + digest(refresh_token), connection)
            if not row or row["payload"]["client_id"] != client.client_id:
                return None
            # Always lock the grant before credentials, matching connection
            # revocation, to avoid opposite-order MySQL row-lock deadlocks.
            self.store.get(row["parent_id"], connection, lock=True)
            row = self.store.get(row["id"], connection, lock=True)
            if row["status"] == "used":
                self.store.revoke(row["parent_id"], connection)
                return None
            if row["status"] != "active":
                return None
            return RefreshToken(token=refresh_token, **row["payload"])

    async def exchange_refresh_token(self, client: OAuthClientInformationFull, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        result = None
        with self.store.transaction() as connection:
            row = self.store.get("refresh:" + digest(refresh_token.token), connection)
            grant = self.store.get(row["parent_id"], connection, lock=True) if row else None
            row = self.store.get(row["id"], connection, lock=True) if row else None
            if row and row["status"] == "used":
                self.store.revoke(row["parent_id"], connection)
            elif row and grant and row["status"] == "active" and grant["status"] == "active" and row["payload"]["client_id"] == client.client_id \
                    and grant["payload"]["expires_at"] > time.time() and self.active_user(row["owner_id"]):
                if not set(scopes).issubset(row["payload"]["scopes"]):
                    raise TokenError("invalid_scope", "刷新不能扩大授权范围")
                self.store.update(row["id"], status="used", connection=connection)
                # Rotate access credentials as well as refresh credentials.
                connection.execute("UPDATE mcp_gateway_records SET status='revoked' WHERE parent_id=? AND kind='access'", (grant["id"],))
                result = self._issue_tokens(grant, connection, scopes)
        if result is None:
            raise TokenError("invalid_grant", "刷新令牌无效、已使用或授权已撤销")
        return result

    async def load_access_token(self, token: str) -> AccessToken | None:
        row = self.store.get("access:" + digest(token))
        if not row or row["status"] != "active" or row["payload"]["expires_at"] <= time.time() or row["payload"]["resource"] != self.config.resource:
            return None
        grant = self.store.get(row["parent_id"])
        if not grant or grant["status"] != "active" or grant["payload"]["expires_at"] <= time.time() or not self.active_user(row["owner_id"]):
            return None
        self.store.update(grant["id"], payload={**grant["payload"], "last_used_at": time.time()})
        return AccessToken(token=token, **row["payload"])

    async def verify_token(self, token: str) -> AccessToken | None:
        return await self.load_access_token(token)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        for kind in ("access", "refresh"):
            row = self.store.get(kind + ":" + digest(token.token))
            if row:
                self.store.revoke(row["parent_id"])
                return

    def connections(self, user_id: str) -> list[dict]:
        result = []
        for row in self.store.list("grant", user_id):
            data = row["payload"]
            result.append({"id": row["id"], "client_name": data["client_name"], "scopes": data["scopes"],
                           "created_at": row["created_at"], "last_used_at": data.get("last_used_at"), "expires_at": data["expires_at"],
                           "status": "expired" if row["status"] == "active" and data["expires_at"] <= time.time() else row["status"]})
        return result

    def revoke_connection(self, grant_id: str, user_id: str) -> None:
        with self.store.transaction() as connection:
            row = self.store.get(grant_id, connection, lock=True)
            if not row or row["kind"] != "grant" or row["owner_id"] != user_id:
                raise HTTPException(404, "授权连接不存在")
            self.store.revoke(grant_id, connection)
        self.app.state.auth_store.audit("mcp_revoke", "mcp", actor_user_id=user_id, target_id=grant_id)
