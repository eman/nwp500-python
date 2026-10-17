"""Models for the account and app-level REST endpoints."""

from .._base import NavienBaseModel


class UserProfile(NavienBaseModel):
    """Account profile from ``POST /user/info``.

    Distinct from :class:`nwp500.auth.UserInfo`, which is the subset the
    sign-in response carries; this adds the phone number and e-mail.
    """

    #: ``"O"`` owner, ``"M"`` member, or an installer type.
    user_type: str = ""
    user_first_name: str = ""
    #: The cloud sends ``null`` for an account without a last name; the
    #: NaviLink app treats that as an empty string, as does this model.
    user_last_name: str | None = ""
    user_phone_number: str | None = None
    user_seq: int = 0
    user_email: str = ""

    @property
    def full_name(self) -> str:
        """Return the user's full name."""
        return f"{self.user_first_name} {self.user_last_name or ''}".strip()


class AppVersionInfo(NavienBaseModel):
    """Answer to ``POST /app/version``.

    ``app_version`` is the latest NaviLink release and ``app_force_version``
    the oldest one the cloud still serves. When the backend is down for
    maintenance it answers 403 with ``server_check_text`` instead, which
    :meth:`~nwp500.NavienAPIClient.get_app_version` returns rather than
    raising.
    """

    app_version: str | None = None
    app_force_version: str | None = None
    #: Maintenance notice, present only on a 403 response.
    server_check_text: str | None = None

    @property
    def is_under_maintenance(self) -> bool:
        """True when the cloud answered with a maintenance notice."""
        return self.server_check_text is not None
