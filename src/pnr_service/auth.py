from dataclasses import dataclass
from typing import Any, Dict, List

from .config import DEFAULT_TENANT_ID


@dataclass(frozen=True)
class AuthContext:
    subject: str
    tenant_id: str
    roles: List[str]

    def has_role(self, role: str) -> bool:
        return role in self.roles


def from_event(event: Dict[str, Any]) -> AuthContext:
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    jwt = authorizer.get("jwt") or {}
    claims = jwt.get("claims") or authorizer.get("claims") or {}

    subject = claims.get("sub") or claims.get("username") or "anonymous"
    tenant_id = claims.get("tenant_id") or claims.get("custom:tenant_id") or DEFAULT_TENANT_ID
    # No fail-open default: a token without a roles/groups claim gets no roles,
    # so require_any_role denies the request rather than granting translator.
    raw_roles = (
        claims.get("roles")
        or claims.get("custom:roles")
        or claims.get("cognito:groups")
        or []
    )
    if isinstance(raw_roles, str):
        roles = [
            role.strip(" []'\"")
            for role in raw_roles.replace(",", " ").split()
            if role.strip(" []'\"")
        ]
    else:
        roles = list(raw_roles)
    return AuthContext(subject=subject, tenant_id=tenant_id, roles=roles)


def require_any_role(ctx: AuthContext, allowed_roles: List[str]) -> None:
    if not any(ctx.has_role(role) for role in allowed_roles):
        raise PermissionError(f"requires one of roles: {', '.join(allowed_roles)}")
