from pydantic import BaseModel, Field
from typing import List, Optional

class RegisterRequest(BaseModel):
    full_name: str
    whatsapp_number: str
    username: Optional[str] = None
    pin: Optional[str] = "1234"
    applied_role: str = "MEMBER"
    school_organization: Optional[str] = ""
    photo_url: Optional[str] = ""

class LoginRequest(BaseModel):
    whatsapp_number: str
    pin: Optional[str] = ""

class RoleApprovalRequest(BaseModel):
    user_id: int
    status: str

class TeamCreateRequest(BaseModel):
    name: str
    school_organization: Optional[str] = ""

class TeamApplyRequest(BaseModel):
    team_id: int
    name: Optional[str] = None
    custom_name: Optional[str] = None
    photo_url: Optional[str] = None
    speaker1_id: Optional[int] = None
    speaker2_id: Optional[int] = None
    speaker3_id: Optional[int] = None


class TeamApprovalRequest(BaseModel):
    team_id: int
    status: str

class TeamRatingRequest(BaseModel):
    team_id: int
    rating: str

class TeamOfficialToggleRequest(BaseModel):
    team_id: int
    is_official: bool

class TeamSelectOfficialRequest(BaseModel):
    team_ids: List[int]

class UpdateProfileRequest(BaseModel):
    photo_url: Optional[str] = None
    avatar_url: Optional[str] = None

class DirectScoreRequest(BaseModel):
    team1_score: float
    team2_score: float
    winner_id: int
    publish_now: Optional[bool] = False

class ResolveTieRequest(BaseModel):
    match_id: Optional[int] = None
    winner_id: int
    reason: str

class BracketManualSwapRequest(BaseModel):
    match_id_1: int
    slot_1: int
    match_id_2: int
    slot_2: int

class ManualMatchPair(BaseModel):
    match_number: int
    team1_id: int
    team2_id: int

class ManualBracketSetupRequest(BaseModel):
    matches: List[ManualMatchPair]

class JudgeAssignRequest(BaseModel):
    match_id: int
    judge_ids: List[int]
    override_clashes: bool = False

class RoundUpdateRequest(BaseModel):
    motion_en: Optional[str] = ""
    motion_bn: Optional[str] = ""
    prep_time_minutes: Optional[int] = 15
    speaking_time_seconds: Optional[int] = 180

class RoomCreateRequest(BaseModel):
    name: str
    description: Optional[str] = ""

class ScoreCriterionInput(BaseModel):
    id: Optional[int] = None
    name: str
    name_bn: Optional[str] = ""
    max_marks: float

class SpeakerScoreInput(BaseModel):
    criterion_id: int
    team_id: int
    speaker_position: int
    score: float

class ScorecardSaveRequest(BaseModel):
    criteria: List[ScoreCriterionInput]
    scores: List[SpeakerScoreInput]

class ScorecardSubmitRequest(BaseModel):
    criteria: List[ScoreCriterionInput]
    scores: List[SpeakerScoreInput]
    tie_choice_team_id: Optional[int] = None

class AdminDeadlockTieRequest(BaseModel):
    match_id: int
    winner_id: int
    reason: str

class TimerSettingsRequest(BaseModel):
    speaking_time_seconds: int = 180
    warning_1_seconds: int = 120
    warning_2_seconds: int = 150
    final_bell_seconds: int = 180
    sound_enabled: int = 1
