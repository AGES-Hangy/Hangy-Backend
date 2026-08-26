"""Import SQLAlchemy models here so Alembic can discover their metadata."""

from app.infrastructure.repository.base import Base
from app.infrastructure.repository.models.user_model import (
    UserModel,
    user_tag,
    user_follows,
)
from app.infrastructure.repository.models.person_profile_model import PersonProfileModel
from app.infrastructure.repository.models.business_profile_model import (
    BusinessProfileModel,
)
from app.infrastructure.repository.models.event_model import EventModel, event_tag
from app.infrastructure.repository.models.tag_model import TagModel
from app.infrastructure.repository.models.event_participant_model import (
    EventParticipantModel,
)
from app.infrastructure.repository.models.event_experience_model import (
    EventExperienceModel,
)
from app.infrastructure.repository.models.experience_images_model import (
    ExperienceImagesModel,
)
from app.infrastructure.repository.models.user_connection_model import (
    UserConnectionModel,
)
from app.infrastructure.repository.models.event_invite_link_model import (
    EventInviteLinkModel,
)
from app.infrastructure.repository.models.report_model import ReportModel
from app.infrastructure.repository.models.notification_model import (
    NotificationModel,
    ConnectionNotificationModel,
    EventInviteNotificationModel,
    EventParticipantNotificationModel,
    EventCancelledNotificationModel,
)

__all__ = [
    "Base",
    "UserModel",
    "user_tag",
    "user_follows",
    "PersonProfileModel",
    "BusinessProfileModel",
    "EventModel",
    "event_tag",
    "TagModel",
    "EventParticipantModel",
    "EventExperienceModel",
    "ExperienceImagesModel",
    "UserConnectionModel",
    "EventInviteLinkModel",
    "ReportModel",
    "NotificationModel",
    "ConnectionNotificationModel",
    "EventInviteNotificationModel",
    "EventParticipantNotificationModel",
    "EventCancelledNotificationModel",
]