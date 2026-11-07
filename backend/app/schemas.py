from datetime import date, datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict


class RegisterIn(BaseModel):
    nickname: str = Field(min_length=2, max_length=32)
    device_uuid: str = Field(min_length=8, max_length=128)


class LoginIn(BaseModel):
    device_uuid: str = Field(min_length=8, max_length=128)
    nickname: str | None = None


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    nickname: str
    created_at: datetime


class AuthOut(BaseModel):
    token: str
    user: UserOut


class RoomCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class RoomOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    invite_code: str
    created_by: UUID
    created_at: datetime


class JoinRoomIn(BaseModel):
    invite_code: str


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    room_id: UUID | None
    name: str
    icon: str | None
    is_default: bool


class CategoryCreateIn(BaseModel):
    room_id: UUID
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = None


class TransactionCreateIn(BaseModel):
    room_id: UUID
    category_id: UUID | None = None
    amount_kop: int = Field(gt=0)
    is_unplanned: bool = False
    happened_at: datetime
    note: str | None = None


class TransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    user_id: UUID
    room_id: UUID
    category_id: UUID | None
    amount_kop: int
    is_unplanned: bool
    happened_at: datetime
    created_at: datetime
    is_voided: bool
    voided_reason: str | None
    user_nickname: str | None = None
    category_name: str | None = None

class ProposalOut(BaseModel):
    id: UUID
    proposed_by_nickname: str
    weekly_limit_kop: int
    unplanned_budget_kop: int
    is_mine: bool = False
    votes_for: int = 0
    votes_against: int = 0
    expires_at: datetime

class VoidIn(BaseModel):
    reason: str = Field(min_length=1, max_length=256)

class UpdateProfileIn(BaseModel):
    nickname: str = Field(min_length=2, max_length=32)

class UserSummary(BaseModel):
    user_id: UUID
    nickname: str
    week_spent_kop: int
    month_spent_kop: int
    unplanned_spent_kop: int


class RoomSummary(BaseModel):
    pending_proposal: ProposalOut | None = None
    room_id: UUID
    month_start: date
    week_start: date
    week_end: date
    weekly_limit_kop: int
    unplanned_budget_kop: int
    users: list[UserSummary]
    room_week_total_kop: int
    room_unplanned_total_kop: int
    is_fallback: bool
    invite_code: str