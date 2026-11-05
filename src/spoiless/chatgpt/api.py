"""ChatGPT connection, accounts, and models API routes."""

from typing import Literal

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from spoiless.chatgpt.accounts import AccountError, list_accounts
from spoiless.chatgpt.credentials import CredentialStoreError
from spoiless.chatgpt.session import SignInBusy, SignInManager, SignInStartError
from spoiless.database import connect
from spoiless.local_security import _local_request

router = APIRouter()
_sign_in = SignInManager()


class SignInResponse(BaseModel):
    status: Literal[
        "idle",
        "saved",
        "pending",
        "processing",
        "connected",
        "denied",
        "failed",
        "expired",
        "cancelled",
    ]
    email: str | None = None
    plan_usage_enabled: bool | None = None


class SignInAction(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: bool = Field(strict=True)
    account_id: str | None = Field(
        default=None, min_length=1, max_length=64, strict=True
    )


@router.get("/api/chatgpt/sign-in", response_model=SignInResponse)
def chatgpt_sign_in_status(request: Request, response: Response) -> SignInResponse:
    _local_request(request)
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))


@router.post("/api/chatgpt/sign-in", response_model=SignInResponse)
def start_chatgpt_sign_in(
    request: Request, response: Response, action: SignInAction
) -> SignInResponse:
    _local_request(request, mutation=True)
    if not action.confirm:
        raise HTTPException(422, "Confirmation is required.")
    try:
        _sign_in.start(action.account_id)
    except (SignInBusy, AccountError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except (CredentialStoreError, SignInStartError) as exc:
        raise HTTPException(503, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))


@router.post("/api/chatgpt/sign-in/cancel", response_model=SignInResponse)
def cancel_chatgpt_sign_in(
    request: Request, response: Response, action: SignInAction
) -> SignInResponse:
    _local_request(request, mutation=True)
    if not action.confirm:
        raise HTTPException(422, "Confirmation is required.")
    try:
        _sign_in.cancel()
    except SignInBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))


class AccountResponse(BaseModel):
    id: str
    email: str | None
    active: bool


class AccountSelection(BaseModel):
    model_config = ConfigDict(extra="forbid")

    account_id: str = Field(min_length=1, max_length=64, strict=True)
    confirm: bool = Field(strict=True)


@router.get("/api/chatgpt/accounts", response_model=list[AccountResponse])
def chatgpt_accounts(request: Request, response: Response) -> list[AccountResponse]:
    _local_request(request)
    response.headers["Cache-Control"] = "no-store"
    return [
        AccountResponse(id=account.id, email=account.email, active=account.active)
        for account in list_accounts()
    ]


@router.post("/api/chatgpt/accounts/select", response_model=SignInResponse)
def select_chatgpt_account(
    request: Request, response: Response, selection: AccountSelection
) -> SignInResponse:
    _local_request(request, mutation=True)
    if not selection.confirm:
        raise HTTPException(422, "Confirmation is required.")
    try:
        _sign_in.select_account(selection.account_id)
    except SignInBusy as exc:
        raise HTTPException(409, str(exc)) from exc
    except AccountError as exc:
        raise HTTPException(409, str(exc)) from exc
    except CredentialStoreError as exc:
        raise HTTPException(503, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return SignInResponse(**vars(_sign_in.state()))


class SignOutAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = Field(strict=True)


@router.post("/api/chatgpt/sign-out")
def sign_out_chatgpt(
    request: Request, response: Response, action: SignOutAction
) -> dict:
    _local_request(request, mutation=True)
    if not action.confirm:
        raise HTTPException(422, "Confirmation is required.")
    try:
        confirmed = _sign_in.sign_out()
    except (SignInBusy, AccountError) as exc:
        raise HTTPException(409, str(exc)) from exc
    except (CredentialStoreError, SignInStartError) as exc:
        raise HTTPException(503, str(exc)) from exc
    response.headers["Cache-Control"] = "no-store"
    return {"revocation_confirmed": confirmed}


class ModelListAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: bool = Field(strict=True)


class ChatGPTModel(BaseModel):
    slug: str
    display_name: str


@router.post("/api/chatgpt/models", response_model=list[ChatGPTModel])
def chatgpt_models(
    request: Request, response: Response, action: ModelListAction
) -> list[ChatGPTModel]:
    from spoiless.chatgpt.accounts import active_account
    from spoiless.chatgpt.exchange import ExchangeError
    from spoiless.chatgpt.models import ModelCatalogError, list_available_models

    _local_request(request, mutation=True)
    if not action.confirm:
        raise HTTPException(422, "Confirmation is required.")
    # ponytail: any database write invalidates lookup; narrow per account if needed.
    with connect() as observer:
        version = observer.execute("PRAGMA data_version").fetchone()[0]
        account = active_account()
        if account is None:
            raise HTTPException(409, "Connect a ChatGPT account first.")
        try:
            models = list_available_models(account.id)
        except ExchangeError:
            raise HTTPException(
                503, "Could not refresh the ChatGPT connection. Please retry."
            ) from None
        except SignInBusy:
            raise HTTPException(409, "ChatGPT account is busy. Please retry.") from None
        except ModelCatalogError:
            raise HTTPException(
                503, "Could not load ChatGPT models. Please retry."
            ) from None
        except AccountError:
            raise HTTPException(409, "This account needs to sign in again.") from None
        except (CredentialStoreError, SignInStartError):
            raise HTTPException(
                503, "The ChatGPT credential store is unavailable."
            ) from None
        current = active_account()
        if (
            current is None
            or current.id != account.id
            or observer.execute("PRAGMA data_version").fetchone()[0] != version
        ):
            raise HTTPException(409, "The active account changed. Please retry.")
        response.headers["Cache-Control"] = "no-store"
        return [ChatGPTModel(**model) for model in models]
