from __future__ import annotations

from typing import TYPE_CHECKING

from django.db import models
from django.utils.translation import gettext_lazy as _

from sentry.backup.scopes import RelocationScope
from sentry.db.models import (
    BoundedPositiveIntegerField,
    FlexibleForeignKey,
    Model,
    region_silo_model,
)
from sentry.db.models.base import sane_repr

if TYPE_CHECKING:
    from sentry.models.grouphashmetadata import GroupHashMetadata


@region_silo_model
class GroupHash(Model):
    __relocation_scope__ = RelocationScope.Excluded

    class State:
        UNLOCKED = None
        LOCKED_IN_MIGRATION = 1

        # This hierarchical grouphash should be ignored/skipped for finding the group.
        SPLIT = 2

    project = FlexibleForeignKey("sentry.Project", null=True)
    hash = models.CharField(max_length=32)
    group = FlexibleForeignKey("sentry.Group", null=True)

    # not-null => the event should be discarded
    group_tombstone_id = BoundedPositiveIntegerField(db_index=True, null=True)
    state = BoundedPositiveIntegerField(
        choices=[(State.LOCKED_IN_MIGRATION, _("Locked (Migration in Progress)"))], null=True
    )

    class Meta:
        app_label = "sentry"
        db_table = "sentry_grouphash"
        unique_together = (("project", "hash"),)

    @property
    def metadata(self) -> GroupHashMetadata | None:
        try:
            return self._metadata
        except AttributeError:
            return None

    __repr__ = sane_repr("group_id", "hash")
