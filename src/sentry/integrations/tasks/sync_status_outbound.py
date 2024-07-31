from sentry import analytics, features
from sentry.integrations.models.external_issue import ExternalIssue
from sentry.integrations.models.integration import Integration
from sentry.integrations.services.integration import integration_service
from sentry.models.group import Group, GroupStatus
from sentry.silo.base import SiloMode
from sentry.tasks.base import instrumented_task, retry, track_group_async_operation


@instrumented_task(
    name="sentry.integrations.tasks.sync_status_outbound",
    queue="integrations",
    default_retry_delay=60 * 5,
    max_retries=5,
    silo_mode=SiloMode.REGION,
)
@retry(exclude=(Integration.DoesNotExist,))
@track_group_async_operation
def sync_status_outbound(group_id: int, external_issue_id: int) -> bool | None:
    groups = Group.objects.filter(
        id=group_id, status__in=[GroupStatus.UNRESOLVED, GroupStatus.RESOLVED]
    )
    if not groups:
        return False

    group = groups[0]
    has_issue_sync = features.has("organizations:integrations-issue-sync", group.organization)
    if not has_issue_sync:
        return False

    try:
        external_issue = ExternalIssue.objects.get(id=external_issue_id)
    except ExternalIssue.DoesNotExist:
        # Issue link could have been deleted while sync job was in the queue.
        return None

    integration = integration_service.get_integration(integration_id=external_issue.integration_id)

    assert integration, "Integration must exist to get an installation"
    installation = integration.get_installation(organization_id=external_issue.organization_id)

    if hasattr(installation, "should_sync") and installation.should_sync("outbound_status"):
        if hasattr(installation, "sync_status_outbound"):
            installation.sync_status_outbound(
                external_issue, group.status == GroupStatus.RESOLVED, group.project_id
            )
            analytics.record(
                "integration.issue.status.synced",
                provider=integration.provider,
                id=integration.id,
                organization_id=external_issue.organization_id,
            )
    return None
