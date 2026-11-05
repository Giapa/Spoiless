"""Local non-secret account registry; tokens stay in the system keyring."""

from dataclasses import dataclass
from uuid import uuid4

from spoiless.chatgpt.auth import DYNAMIC_CLIENT, VerifiedIdentity, _client_id
from spoiless.chatgpt.credentials import load_credentials
from spoiless.library import connect


class AccountError(Exception):
    """The saved registration is missing, invalid, or belongs to another identity."""


@dataclass(frozen=True, repr=False)
class SavedAccount:
    id: str
    client_id: str
    subject: str
    email: str | None
    active: bool


def remember_verified(client_id: str, identity: VerifiedIdentity) -> str:
    """Record a verified registration before storing tokens, so it is recoverable."""
    if (
        not isinstance(client_id, str)
        or not _client_id(client_id)
        or client_id == DYNAMIC_CLIENT
        or not isinstance(identity, VerifiedIdentity)
        or not isinstance(identity.subject, str)
        or not identity.subject.strip()
        or len(identity.subject) > 2048
        or (
            identity.email is not None
            and (not isinstance(identity.email, str) or len(identity.email) > 2048)
        )
    ):
        raise AccountError("Invalid verified account.")
    with connect() as db, db:
        db.execute("BEGIN IMMEDIATE")
        row = db.execute(
            "SELECT id, subject FROM chatgpt_accounts WHERE client_id = ?", (client_id,)
        ).fetchone()
        if row:
            if row[1] != identity.subject:
                raise AccountError("The registered client belongs to another account.")
            account_id = row[0]
            db.execute(
                "UPDATE chatgpt_accounts SET email = ? WHERE id = ?",
                (identity.email, account_id),
            )
        else:
            account_id = str(uuid4())
            db.execute(
                "INSERT INTO chatgpt_accounts (id, client_id, subject, email) "
                "VALUES (?, ?, ?, ?)",
                (account_id, client_id, identity.subject, identity.email),
            )
    return account_id


def list_accounts() -> list[SavedAccount]:
    with connect() as db:
        rows = db.execute(
            """SELECT a.id, a.client_id, a.subject, a.email,
                      COALESCE(a.id = (SELECT value FROM app_settings
                                       WHERE key = 'active_chatgpt_account'), 0)
               FROM chatgpt_accounts a ORDER BY a.created_at, a.rowid"""
        ).fetchall()
    return [
        SavedAccount(account_id, client_id, subject, email, bool(active))
        for account_id, client_id, subject, email, active in rows
    ]


def get_account(account_id: str) -> SavedAccount:
    account = next((item for item in list_accounts() if item.id == account_id), None)
    if account is None:
        raise AccountError("Saved account not found.")
    return account


def active_account() -> SavedAccount | None:
    return next((account for account in list_accounts() if account.active), None)


def _mark_active(account_id: str) -> None:
    with connect() as db, db:
        db.execute("BEGIN IMMEDIATE")
        if (
            db.execute(
                "SELECT 1 FROM chatgpt_accounts WHERE id = ?", (account_id,)
            ).fetchone()
            is None
        ):
            raise AccountError("Saved account not found.")
        db.execute(
            """INSERT INTO app_settings (key, value)
               VALUES ('active_chatgpt_account', ?)
               ON CONFLICT(key) DO UPDATE SET value = excluded.value""",
            (account_id,),
        )


def activate_after_storage(account_id: str) -> None:
    """Mark active only after this sign-in has successfully stored its tokens."""
    _mark_active(account_id)


def select_saved_account(account_id: str) -> None:
    """Select a saved account only if the keyring has its matching registration.

    This selects a saved account, not a guarantee that its tokens remain valid.
    """
    account = get_account(account_id)
    record = load_credentials(account.client_id)
    if record is None or record.subject != account.subject:
        raise AccountError("This account needs to sign in again.")
    _mark_active(account_id)


def clear_active_account() -> None:
    """Forget the active selection while retaining saved registrations."""
    with connect() as db, db:
        db.execute("DELETE FROM app_settings WHERE key = 'active_chatgpt_account'")
