"""ADFS auth provider.

ADFS publishes two issuers in its discovery document:

    "issuer":              "https://adfs.example.com/adfs"                -> ID tokens
    "access_token_issuer": "http://adfs.example.com/adfs/services/trust"  -> access tokens

OIDCProxy validates the upstream *access* token, but builds its verifier from
`issuer`, so every token is rejected with an issuer mismatch. ADFS does
advertise the right value; `access_token_issuer` is a Microsoft extension
rather than part of OIDC Discovery, so OIDCConfiguration drops it on parse.

This keeps the field and prefers it when building the verifier. Everything
else is inherited. Once FastMCP reads the extension itself, delete this module
and point FASTMCP_SERVER_AUTH back at the stock provider.

Configured with the FASTMCP_SERVER_AUTH_AUTH0_* variables: Auth0Provider is a
generic OIDC provider with no Auth0-specific behavior, only an unlucky name.
"""

from typing import Any

from fastmcp.server.auth.auth import TokenVerifier
from fastmcp.server.auth.oidc_proxy import OIDCConfiguration
from fastmcp.server.auth.providers.auth0 import Auth0Provider
from fastmcp.server.auth.providers.jwt import JWTVerifier
from pydantic import AnyHttpUrl

_AUTH0_PROVIDER_PATH = "fastmcp.server.auth.providers.auth0.Auth0Provider"


def _auth0_kwargs_from_env() -> dict[str, Any]:
    """Build Auth0Provider kwargs from FASTMCP_SERVER_AUTH_AUTH0_* variables.

    mcp-clickhouse only maps env variables for the stock providers it knows by
    class path; a custom provider is constructed without arguments. This reuses
    the server's own Auth0 mapping and parsing, so the variables behave exactly
    as they would for the stock Auth0Provider.
    """
    # Imported lazily: mcp_server loads this module while it is being set up.
    from mcp_clickhouse import mcp_server

    prefix, fields = mcp_server._LEGACY_AUTH_PROVIDER_ENV[_AUTH0_PROVIDER_PATH]
    file_values = mcp_server._get_legacy_auth_file_values()
    kwargs: dict[str, Any] = {}
    for field_name in fields:
        env_name = f"FASTMCP_SERVER_AUTH_{prefix}{field_name.upper()}"
        value = mcp_server._get_legacy_auth_env(env_name, file_values)
        if value is None:
            continue
        kwargs[field_name] = mcp_server._parse_auth_provider_env_value(
            _AUTH0_PROVIDER_PATH, field_name, env_name, value
        )
    if not kwargs.get("required_scopes"):
        kwargs["required_scopes"] = mcp_server._LEGACY_AUTH_SCOPE_DEFAULTS[_AUTH0_PROVIDER_PATH]
    return kwargs


class AdfsOIDCConfiguration(OIDCConfiguration):
    """OIDC configuration that retains the ADFS access token issuer.

    Typed as a plain string, not AnyHttpUrl: the value is an identifier that is
    compared verbatim against the token's `iss` claim, never fetched, so URL
    normalization could only corrupt it.
    """

    access_token_issuer: str | None = None


class PxfdAdfsProvider(Auth0Provider):
    """Auth0Provider that verifies access tokens against access_token_issuer."""

    oidc_config: AdfsOIDCConfiguration

    def __init__(self, **kwargs: Any):
        super().__init__(**(kwargs or _auth0_kwargs_from_env()))

    def get_oidc_configuration(
        self,
        config_url: AnyHttpUrl,
        strict: bool | None,
        timeout_seconds: int | None,
    ) -> OIDCConfiguration:
        return AdfsOIDCConfiguration.get_oidc_configuration(
            config_url, strict=strict, timeout_seconds=timeout_seconds
        )

    def get_token_verifier(
        self,
        *,
        algorithm: str | None = None,
        audience: str | None = None,
        required_scopes: list[str] | None = None,
        timeout_seconds: int | None = None,
    ) -> TokenVerifier:
        issuer = self.oidc_config.access_token_issuer or self.oidc_config.issuer
        return JWTVerifier(
            jwks_uri=str(self.oidc_config.jwks_uri),
            issuer=str(issuer),
            algorithm=algorithm,
            audience=audience,
            required_scopes=required_scopes,
        )
