"""Student-only authentication routes. Never mount these in the operator service."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from app.errors import APIError
from app.student_auth.service import verify_password

router = APIRouter(prefix="/auth", tags=["Student access"])


class BetaInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    passcode: str = Field(min_length=1, max_length=256)


class EmailInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    email: str = Field(min_length=3, max_length=254)


class CodeInput(EmailInput):
    code: str = Field(pattern=r"^[0-9]{6,10}$")


@router.get("/session")
def session(request: Request):
    auth = request.app.state.student_auth
    config = auth.configured()
    try:
        return auth.state(auth.lookup(request))
    except APIError as error:
        if error.status_code != 401:
            raise
        return {"authenticated": False, "mode": config.mode, "needs_renewal": False}


def signed_in(request, token):
    auth = request.app.state.student_auth
    config = auth.configured()
    response = JSONResponse({"ok": True})
    response.set_cookie(
        config.cookie,
        token,
        max_age=config.ttl_seconds,
        secure=config.secure,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return response


@router.post("/beta")
def beta(request: Request, body: BetaInput):
    auth = request.app.state.student_auth
    config = auth.configured()
    auth.origin(request)
    if config.mode != "beta":
        raise APIError(404, "not_found", "Sign-in method is unavailable.")
    auth.limit(request, "beta")
    if not verify_password(body.passcode, config.password_hash):
        raise APIError(401, "invalid_signin", "The passcode was not accepted.")
    return signed_in(request, auth.create(request))


@router.post("/university/code")
def send_code(request: Request, body: EmailInput):
    auth = request.app.state.student_auth
    auth.origin(request)
    auth.limit(request, "send", body.email)
    auth.university().send(body.email)
    return {"ok": True}


@router.post("/university/verify")
def verify_code(request: Request, body: CodeInput):
    auth = request.app.state.student_auth
    auth.origin(request)
    auth.limit(request, "verify", body.email)
    identity = auth.university().verify(body.email, body.code)
    return signed_in(request, auth.create(request, identity))


@router.post("/renew")
def renew(request: Request):
    return request.app.state.student_auth.renew(request)


@router.post("/logout")
def logout(request: Request):
    auth = request.app.state.student_auth
    auth.logout(request)
    config = auth.configured()
    response = JSONResponse({"ok": True})
    response.delete_cookie(
        config.cookie, secure=config.secure, httponly=True, samesite="lax", path="/"
    )
    return response
