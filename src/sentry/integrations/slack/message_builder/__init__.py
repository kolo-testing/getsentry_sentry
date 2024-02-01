from typing import Any, Mapping, Union

from sentry.issues.grouptype import GroupCategory

# TODO(mgaeta): Continue fleshing out these types.
SlackAttachment = Mapping[str, Any]
SlackBlock = Mapping[str, Any]
SlackBody = Union[SlackAttachment, SlackBlock, list[SlackAttachment]]

# Attachment colors used for issues with no actions take.
LEVEL_TO_COLOR = {
    "_actioned_issue": "#EDEEEF",
    "_incident_resolved": "#4DC771",
    "debug": "#FBE14F",
    "error": "#E03E2F",
    "fatal": "#FA4747",
    "info": "#2788CE",
    "warning": "#FFC227",
}

INCIDENT_COLOR_MAPPING = {
    "Resolved": "_incident_resolved",
    "Warning": "warning",
    "Critical": "fatal",
}

SLACK_URL_FORMAT = "<{url}|{text}>"

LEVEL_TO_EMOJI = {
    "_actioned_issue": ":white_check_mark:",
    "_incident_resolved": ":green_circle:",
    "debug": ":bug:",
    "error": ":exclamation:",
    "fatal": ":skull_and_crossbones:",
    "info": ":information_source:",
    "warning": ":warning:",
}

CATEGORY_TO_EMOJI = {
    GroupCategory.PERFORMANCE: ":chart_with_upwards_trend:",
    GroupCategory.FEEDBACK: ":busts_in_silhouette:",
    GroupCategory.CRON: ":spiral_calendar_pad:",
}
