from django.db import models

from sentry.backup.scopes import RelocationScope
from sentry.db.models import DefaultFieldsModel, FlexibleForeignKey, region_silo_model


@region_silo_model
class DetectorState(DefaultFieldsModel):
    __relocation_scope__ = RelocationScope.Organization

    class Type(models.TextChoices):
        ACTIVE = "active"
        INACTIVE = "inactive"

    detetor_id = FlexibleForeignKey("sentry.Detector")
    detector_group_key = models.CharField(max_length=200, blank=True, null=True)
    status = models.CharField(max_length=200, choices=Type.choices)
