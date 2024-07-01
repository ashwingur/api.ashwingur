from marshmallow import ValidationError

# Ensure a list of strings does not contain empty strings
def validate_non_empty_string_list(value):
    for item in value:
        if not item.strip():
            raise ValidationError("Strings in the list cannot be empty.")
