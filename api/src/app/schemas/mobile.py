from __future__ import annotations

from pydantic import BaseModel

from app.schemas.clients import ClientAdminProfileResponse, ClientProfileResponse


class MobileSessionResponse(BaseModel):
    user_email: str | None
    role: str | None
    is_admin: bool
    is_guest: bool
    can_upload_documents: bool
    can_manage_data: bool
    clients: list[ClientAdminProfileResponse]
    selected_client: ClientProfileResponse | None
