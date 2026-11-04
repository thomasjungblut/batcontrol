""" Optional bearer token authentication

With ``api.auth_token`` set, every route except ``/api/v1/health`` needs
``Authorization: Bearer <token>``. With an empty token the dependency is not
installed at all, so there is no code path that could accept a request for
the wrong reason. ``/api/v1/health`` stays open for container health checks.
"""
import logging
from typing import List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .config import ApiConfig, token_matches

logger = logging.getLogger(__name__)

BEARER_SCHEME = 'bearer'

# auto_error=False so a missing header produces our own 401 with a
# WWW-Authenticate header rather than FastAPI's 403.
_bearer = HTTPBearer(auto_error=False, scheme_name='Bearer token',
                     description='Value of api.auth_token.')


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={'WWW-Authenticate': 'Bearer'},
    )


def auth_dependencies(config: ApiConfig) -> List:
    """ The dependency list to put on the protected routers.

    Empty when no token is configured.
    """
    if not config.auth_enabled:
        return []

    def require_token(
            credentials: Optional[HTTPAuthorizationCredentials] =
            Depends(_bearer)) -> None:
        """ Verify the bearer token in constant time. """
        if credentials is None:
            raise _unauthorized('Missing bearer token.')
        if credentials.scheme.lower() != BEARER_SCHEME:
            raise _unauthorized('Expected an "Authorization: Bearer" header.')
        # Constant-time, and byte-based so a non-ASCII token is rejected
        # rather than raising; the token is never logged.
        if not token_matches(credentials.credentials, config.auth_token):
            raise _unauthorized('Invalid bearer token.')

    return [Depends(require_token)]
