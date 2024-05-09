import logging

import orjson
from jsonschema import Draft7Validator
from jsonschema.exceptions import ValidationError as SchemaValidationError
from jsonschema.exceptions import best_match

logger = logging.getLogger(__name__)

SCHEMA = {
    "type": "object",
    "definitions": {
        # Property Types
        "uri": {"type": "string", "format": "uri", "pattern": r"^\/"},
        "options": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "array",
                "minItems": 2,
                "maxItems": 2,
                "items": [{"type": "string"}, {"anyOf": [{"type": "string"}, {"type": "number"}]}],
            },
        },
        "fieldset": {
            "type": "array",
            "minItems": 1,
            "items": {
                "anyOf": [
                    {"$ref": "#/definitions/select"},
                    {"$ref": "#/definitions/text"},
                    {"$ref": "#/definitions/textarea"},
                ]
            },
        },
        # Form Components
        "select": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["select"]},
                "label": {"type": "string"},
                "name": {"type": "string"},
                "async": {"type": "boolean"},
                "skip_load_on_open": {"type": "boolean"},
                "uri": {"$ref": "#/definitions/uri"},
                "options": {"$ref": "#/definitions/options"},
                "depends_on": {"type": "array", "minItems": 1, "items": {"type": "string"}},
            },
            "required": ["type", "name", "label"],
            "oneOf": [{"required": ["uri"]}, {"required": ["options"]}],
        },
        "text": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["text"]},
                "label": {"type": "string"},
                "name": {"type": "string"},
                "default": {"type": "string", "enum": ["issue.title", "issue.description"]},
            },
            "required": ["type", "label", "name"],
        },
        "textarea": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["textarea"]},
                "label": {"type": "string"},
                "name": {"type": "string"},
                "default": {"type": "string", "enum": ["issue.title", "issue.description"]},
            },
            "required": ["type", "label", "name"],
        },
        # Composable Components
        "header": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["header"]},
                "text": {"type": "string"},
            },
            "required": ["type", "text"],
        },
        "image": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["image"]},
                "url": {"type": "string", "format": "uri", "pattern": r"^(?:https?|\/)"},
                "alt": {"type": "string"},
            },
            "required": ["type", "url"],
        },
        "video": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["video"]},
                "url": {"type": "string", "format": "uri", "pattern": r"^(?:https?|\/)"},
            },
            "required": ["type", "url"],
        },
        "markdown": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["markdown"]},
                "text": {"type": "string"},
            },
            "required": ["type", "text"],
        },
        # Feature Components
        "issue-link": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["issue-link"]},
                "link": {
                    "type": "object",
                    "properties": {
                        "uri": {"$ref": "#/definitions/uri"},
                        "required_fields": {"$ref": "#/definitions/fieldset"},
                        "optional_fields": {"$ref": "#/definitions/fieldset"},
                    },
                    "required": ["uri", "required_fields"],
                },
                "create": {
                    "type": "object",
                    "properties": {
                        "uri": {"$ref": "#/definitions/uri"},
                        "required_fields": {"$ref": "#/definitions/fieldset"},
                        "optional_fields": {"$ref": "#/definitions/fieldset"},
                    },
                    "required": ["uri", "required_fields"],
                },
            },
            "required": ["type", "link", "create"],
        },
        "alert-rule-settings": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["alert-rule-settings"]},
                "description": {"type": "string", "maxLength": 140, "minLength": 1},
                "uri": {"$ref": "#/definitions/uri"},
                "required_fields": {"$ref": "#/definitions/fieldset"},
                "optional_fields": {"$ref": "#/definitions/fieldset"},
            },
            "required": ["type", "uri", "required_fields"],
        },
        "alert-rule-action": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["alert-rule-action"]},
                "title": {"type": "string"},
                "settings": {"$ref": "#/definitions/alert-rule-settings"},
            },
            "required": ["type", "title", "settings"],
        },
        "issue-media": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["issue-media"]},
                "title": {"type": "string"},
                "elements": {
                    "type": "array",
                    "minItems": 1,
                    "items": {
                        "anyOf": [
                            {"$ref": "#/definitions/header"},
                            {"$ref": "#/definitions/markdown"},
                            {"$ref": "#/definitions/image"},
                            {"$ref": "#/definitions/video"},
                        ]
                    },
                },
            },
            "required": ["type", "title", "elements"],
        },
        "stacktrace-link": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["stacktrace-link"]},
                "uri": {"$ref": "#/definitions/uri"},
            },
            "required": ["type", "uri"],
        },
    },
    "properties": {
        "elements": {
            "type": "array",
            "minItems": 1,
            "items": {
                "anyOf": [
                    {"$ref": "#/definitions/issue-link"},
                    {"$ref": "#/definitions/alert-rule-action"},
                    {"$ref": "#/definitions/issue-media"},
                    {"$ref": "#/definitions/stacktrace-link"},
                ]
            },
        }
    },
    "required": ["elements"],
}

ELEMENT_TYPES = ["issue-link", "alert-rule-action", "issue-media", "stacktrace-link"]
DEFAULT_TEXT_TYPES = ["issue.title", "issue.description"]
TEXT_COMPONENTS = ["text", "textarea"]


def validate_component(schema):
    """
    In order to test individual components, that aren't normally allowed at the
    top-level of a schema, we just plop all `definitions` into `properties`.
    This makes the validator think they're all valid top-level elements.
    """
    component_schema = SCHEMA.copy()
    component_schema["properties"] = component_schema["definitions"]
    del component_schema["required"]
    validate(instance={schema["type"]: schema}, schema=component_schema)


def check_elements_is_array(instance):
    if "elements" in instance and not isinstance(instance["elements"], list):
        raise SchemaValidationError("'elements' should be an array of objects")


def check_each_element_for_error(instance):
    if "elements" not in instance:
        return

    for element in instance["elements"]:
        if "type" not in element:
            raise SchemaValidationError("Each element needs a 'type' field")
        found_type = element["type"]
        if found_type not in ELEMENT_TYPES:
            raise SchemaValidationError(
                f"Element has type '{found_type}'. Type must be one of the following: {ELEMENT_TYPES}"
            )
        validate_text_component_defaults(element, found_type)
        try:
            validate_component(element)
        except SchemaValidationError as e:
            # catch the validation error and re-write the error so the user knows which element has the issue
            raise SchemaValidationError(f"{e.message} for element of type '{found_type}'")


def validate_text_component_defaults(element, found_type):
    data = element["settings"] if found_type == "alert-rule-action" else element
    optional_fields = data.get("optional_fields", [])
    required_fields = data.get("required_fields", [])

    for field in optional_fields + required_fields:
        if field.get("type") in TEXT_COMPONENTS:
            default = field.get("default")
            if default and default not in DEFAULT_TEXT_TYPES:
                raise SchemaValidationError(
                    f"Elements of type {TEXT_COMPONENTS} may only have a default value of the following: {DEFAULT_TEXT_TYPES}, but {default} was found."
                )


def check_only_one_of_each_element(instance):
    if "elements" not in instance:
        return
    found = {}
    for element in instance["elements"]:
        if element["type"]:
            if element["type"] not in found:
                found[element["type"]] = 1
            else:
                raise SchemaValidationError(f"Multiple elements of type: {element['type']}")


def validate_ui_element_schema(instance):
    try:
        # schema validator will catch elements missing
        check_elements_is_array(instance)
        check_each_element_for_error(instance)
        check_only_one_of_each_element(instance)
    except SchemaValidationError:
        raise
    except Exception as e:
        logger.warning(
            "Unexpected error validating schema: %s",
            e,
            exc_info=True,
            extra={"schema": orjson.dumps(instance).decode()},
        )
        # pre-validators might have unexpected errors if the format is not what they expect in the check
        # if that happens, we should eat the error and let the main validator find the schema error
    validate(instance, SCHEMA)


def validate(instance, schema):
    v = Draft7Validator(schema)
    if not v.is_valid(instance):
        raise best_match(v.iter_errors(instance))
