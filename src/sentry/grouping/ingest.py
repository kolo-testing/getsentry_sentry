from __future__ import annotations

import copy
import random
import time
from typing import TYPE_CHECKING, Any, MutableMapping

import sentry_sdk
from django.conf import settings
from django.core.cache import cache

from sentry import options
from sentry.grouping.api import (
    BackgroundGroupingConfigLoader,
    GroupingConfig,
    GroupingConfigNotFound,
    apply_server_fingerprinting,
    detect_synthetic_exception,
    get_fingerprinting_config_for_project,
    get_grouping_config_dict_for_project,
    load_grouping_config,
)
from sentry.grouping.result import CalculatedHashes
from sentry.locks import locks
from sentry.models.project import Project
from sentry.projectoptions.defaults import BETA_GROUPING_CONFIG, DEFAULT_GROUPING_CONFIG
from sentry.utils import metrics
from sentry.utils.metrics import MutableTags
from sentry.utils.tag_normalization import normalized_sdk_tag_from_event

if TYPE_CHECKING:
    from sentry.eventstore.models import Event

Job = MutableMapping[str, Any]


def update_grouping_config_if_needed(project: Project) -> None:
    if _project_should_update_grouping(project):
        _auto_update_grouping(project)


def _project_should_update_grouping(project: Project) -> bool:
    should_update_org = (
        project.organization_id % 1000 < float(settings.SENTRY_GROUPING_AUTO_UPDATE_ENABLED) * 1000
    )
    return bool(project.get_option("sentry:grouping_auto_update")) and should_update_org


def _auto_update_grouping(project: Project) -> None:
    current_config = project.get_option("sentry:grouping_config")
    new_config = DEFAULT_GROUPING_CONFIG

    if current_config == new_config or current_config == BETA_GROUPING_CONFIG:
        return

    # Because the way the auto grouping upgrading happening is racy, we want to
    # try to write the audit log entry and project option change just once.
    # For this a cache key is used.  That's not perfect, but should reduce the
    # risk significantly.
    cache_key = f"grouping-config-update:{project.id}:{current_config}"
    lock_key = f"grouping-update-lock:{project.id}"
    if cache.get(cache_key) is not None:
        return

    with locks.get(lock_key, duration=60, name="grouping-update-lock").acquire():
        if cache.get(cache_key) is None:
            cache.set(cache_key, "1", 60 * 5)
        else:
            return

        from sentry import audit_log
        from sentry.utils.audit import create_system_audit_entry

        # This is when we will stop calculating both old hashes (which we do in an effort to
        # preserve group continuity).
        expiry = int(time.time()) + settings.SENTRY_GROUPING_UPDATE_MIGRATION_PHASE

        changes = {
            "sentry:secondary_grouping_config": current_config,
            "sentry:secondary_grouping_expiry": expiry,
            "sentry:grouping_config": new_config,
        }
        for key, value in changes.items():
            project.update_option(key, value)

        create_system_audit_entry(
            organization=project.organization,
            target_object=project.id,
            event=audit_log.get_event_id("PROJECT_EDIT"),
            data={**changes, **project.get_audit_log_data()},
        )


def calculate_event_grouping(
    project: Project, event: Event, grouping_config: GroupingConfig
) -> CalculatedHashes:
    """
    Main entrypoint for modifying/enhancing and grouping an event, writes
    hashes back into event payload.
    """
    metric_tags: MutableTags = {
        "grouping_config": grouping_config["id"],
        "platform": event.platform or "unknown",
        "sdk": normalized_sdk_tag_from_event(event),
    }

    with metrics.timer("save_event.calculate_event_grouping", tags=metric_tags):
        with metrics.timer("event_manager.normalize_stacktraces_for_grouping", tags=metric_tags):
            with sentry_sdk.start_span(op="event_manager.normalize_stacktraces_for_grouping"):
                event.normalize_stacktraces_for_grouping(load_grouping_config(grouping_config))

        # Detect & set synthetic marker if necessary
        detect_synthetic_exception(event.data, grouping_config)

        with metrics.timer("event_manager.apply_server_fingerprinting", tags=metric_tags):
            # The active grouping config was put into the event in the
            # normalize step before.  We now also make sure that the
            # fingerprint was set to `'{{ default }}' just in case someone
            # removed it from the payload.  The call to get_hashes will then
            # look at `grouping_config` to pick the right parameters.
            event.data["fingerprint"] = event.data.data.get("fingerprint") or ["{{ default }}"]
            apply_server_fingerprinting(
                event.data.data,
                get_fingerprinting_config_for_project(project),
                allow_custom_title=True,
            )

        with metrics.timer("event_manager.event.get_hashes", tags=metric_tags):
            # Here we try to use the grouping config that was requested in the
            # event. If that config has since been deleted (because it was an
            # experimental grouping config) we fall back to the default.
            try:
                hashes = event.get_hashes(grouping_config)
            except GroupingConfigNotFound:
                event.data["grouping_config"] = get_grouping_config_dict_for_project(project)
                hashes = event.get_hashes()

        hashes.write_to_event(event.data)
        return hashes


def run_background_grouping(project: Project, job: Job) -> None:
    """Optionally run a fraction of events with a third grouping config
    This can be helpful to measure its performance impact.
    This does not affect actual grouping.
    """
    try:
        sample_rate = options.get("store.background-grouping-sample-rate")
        if sample_rate and random.random() <= sample_rate:
            config = BackgroundGroupingConfigLoader().get_config_dict(project)
            if config["id"]:
                copied_event = copy.deepcopy(job["event"])
                _calculate_background_grouping(project, copied_event, config)
    except Exception:
        sentry_sdk.capture_exception()


def _calculate_background_grouping(
    project: Project, event: Event, config: GroupingConfig
) -> CalculatedHashes:
    metric_tags: MutableTags = {
        "grouping_config": config["id"],
        "platform": event.platform or "unknown",
        "sdk": normalized_sdk_tag_from_event(event),
    }
    with metrics.timer("event_manager.background_grouping", tags=metric_tags):
        return calculate_event_grouping(project, event, config)


def should_run_secondary_grouping(project: Project) -> bool:
    result = False
    secondary_grouping_config = project.get_option("sentry:secondary_grouping_config")
    secondary_grouping_expiry = project.get_option("sentry:secondary_grouping_expiry")
    if secondary_grouping_config and (secondary_grouping_expiry or 0) >= time.time():
        result = True
    return result


def calculate_secondary_hash(
    project: Project, job: Job, secondary_grouping_config: GroupingConfig
) -> None | CalculatedHashes:
    """Calculate secondary hash for event using a fallback grouping config for a period of time.
    This happens when we upgrade all projects that have not opted-out to automatic upgrades plus
    when the customer changes the grouping config.
    This causes extra load in save_event processing.
    """
    secondary_hashes = None
    try:
        with sentry_sdk.start_span(
            op="event_manager",
            description="event_manager.save.secondary_calculate_event_grouping",
        ):
            # create a copy since `_calculate_event_grouping` modifies the event to add all sorts
            # of grouping info and we don't want the backup grouping data in there
            event_copy = copy.deepcopy(job["event"])
            secondary_hashes = calculate_event_grouping(
                project, event_copy, secondary_grouping_config
            )
    except Exception:
        sentry_sdk.capture_exception()

    return secondary_hashes


def calculate_primary_hash(
    project: Project, job: Job, grouping_config: GroupingConfig
) -> CalculatedHashes:
    """
    Get the primary hash for the event.

    This is pulled out into a separate function mostly in order to make testing easier.
    """
    return calculate_event_grouping(project, job["event"], grouping_config)
