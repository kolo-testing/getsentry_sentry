from collections.abc import Callable, Iterable, Mapping
from typing import Any, TypeVar

# A list of common builtin custom field types for Jira for easy reference.
JIRA_CUSTOM_FIELD_TYPES = {
    "select": "com.atlassian.jira.plugin.system.customfieldtypes:select",
    "textarea": "com.atlassian.jira.plugin.system.customfieldtypes:textarea",
    "multiuserpicker": "com.atlassian.jira.plugin.system.customfieldtypes:multiuserpicker",
    "tempo_account": "com.tempoplugin.tempo-accounts:accounts.customfield",
    "sprint": "com.pyxis.greenhopper.jira:gh-sprint",
    "epic": "com.pyxis.greenhopper.jira:gh-epic-link",
    "team": "com.atlassian.jira.plugin.system.customfieldtypes:atlassian-team",
    "rank": "com.pyxis.greenhopper.jira:gh-lexo-rank",
    "development": "com.atlassian.jira.plugins.jira-development-integration-plugin:devsummarycf",
}
from sentry.integrations.jira.models.create_issue_metadata import JiraField, JiraSchemaTypes
from sentry.shared_integrations.exceptions import IntegrationFormError


class JiraSchemaParseError(Exception):
    pass


def parse_number_field(num_str: str) -> int | float:
    try:
        if "." in num_str:
            return float(num_str)

        return int(num_str)
    except ValueError:
        raise JiraSchemaParseError(f"Invalid number value provided for field: '{num_str}'")


TransformerType = Mapping[str, Callable[[Any], Any]]

T = TypeVar("T")


def identity_transformer(input_val: T) -> T:
    return input_val


def id_obj_transformer(input_val: Any) -> dict[str, Any]:
    return {"id": input_val}


def get_type_transformer_mappings(user_id_field: str) -> TransformerType:
    transformers = {
        JiraSchemaTypes.user.value: lambda x: {user_id_field: x},
        JiraSchemaTypes.issue_type.value: id_obj_transformer,
        JiraSchemaTypes.option.value: lambda x: {"value": x},
        JiraSchemaTypes.issue_link.value: lambda x: {"key": x},
        JiraSchemaTypes.project.value: id_obj_transformer,
        JiraSchemaTypes.number.value: parse_number_field,
    }

    return transformers


def get_custom_field_transformer_mappings() -> TransformerType:
    transformers = {
        # JIRA_CUSTOM_FIELD_TYPES["select"]: identity_transformer,
        # JIRA_CUSTOM_FIELD_TYPES["textarea"]: identity_transformer,
        # JIRA_CUSTOM_FIELD_TYPES["multiuserpicker"]: identity_transformer,
        JIRA_CUSTOM_FIELD_TYPES["tempo_account"]: parse_number_field,
        # JIRA_CUSTOM_FIELD_TYPES["sprint"]: identity_transformer,
        # JIRA_CUSTOM_FIELD_TYPES["epic"]: identity_transformer,
        JIRA_CUSTOM_FIELD_TYPES["rank"]: id_obj_transformer,
    }

    return transformers


def get_transformer_for_field(
    type_transformers: TransformerType, custom_transformers: TransformerType, jira_field: JiraField
) -> Callable[[Any], Any]:
    transformer = None
    if jira_field.is_custom_field():
        assert jira_field.schema.custom
        transformer = custom_transformers.get(jira_field.schema.custom)

    if not transformer:
        field_type = jira_field.get_field_type()

        if field_type:
            transformer = type_transformers.get(field_type)

    if not transformer:
        transformer = identity_transformer

    return transformer


def transform_fields(
    user_id_field: str, jira_fields: Iterable[JiraField], **data
) -> Mapping[str, Any]:
    transformed_data = {}

    # Special handling for fields that don't map cleanly to the transformer logic
    data["summary"] = data.get("title")
    if labels := data.get("labels"):
        data["labels"] = [label.strip() for label in labels.split(",") if label.strip()]

    type_transformers = get_type_transformer_mappings(user_id_field)
    custom_field_transformers = get_custom_field_transformer_mappings()

    for field in jira_fields:
        field_data = data.get(field.key)

        # We don't have a mapping for this field, so it's probably extraneous
        if field_data is None:
            continue

        field_transformer = get_transformer_for_field(
            type_transformers, custom_field_transformers, field
        )

        try:
            if field.schema.schema_type.lower() == JiraSchemaTypes.array:
                transformed_value = []

                if not isinstance(field_data, list):
                    field_data = [field_data]

                # Bulk transform the individual data fields
                for val in field_data:
                    transformed_value.append(field_transformer(val))
            else:
                transformed_value = field_transformer(field_data)

        except JiraSchemaParseError as e:
            raise IntegrationFormError(field_errors={field.name: str(e)}) from e

        if transformed_value:
            transformed_data[field.key] = transformed_value

    return transformed_data
