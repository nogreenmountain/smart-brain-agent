from fastapi import HTTPException
import gotrue
import supabase_auth


class AuthException(HTTPException):
    """Shared status_code for all auth exceptions"""

    # TODO don't return detailed messages to the client in production
    def __init__(self, detail: str = "Failed to authenticate user."):
        super().__init__(status_code=401, detail=detail)

    @classmethod
    def from_gotrue_autherror(cls, exc):
        """
        Create an AuthException from a GoTrue / supabase_auth exception.

        Accepts either gotrue.errors.AuthApiError or
        supabase_auth.errors.AuthApiError via duck-typing on `.message`.
        This avoids a hard dependency on the deprecated gotrue package.
        """
        message = getattr(exc, "message", None)
        if message == "Email not confirmed":
            return AuthUnconfirmedEmailException()
        return cls()  # don't bubble messages we don't explicitly approve


class AuthUnconfirmedEmailException(AuthException):
    """Raised when the user has not confirmed their email address"""

    def __init__(self):
        super().__init__(
            detail=(
                "Your email address has not been confirmed. "
                "Check your inbox for a confirmation email and click the link "
                "before signing in for the first time."
            )
        )
