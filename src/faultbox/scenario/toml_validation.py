"""Check fields and types in values returned by tomllib."""


def expect_array(value: object, field: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field}: expected an array")

    return value


def expect_table(value: object, field: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field}: expected a table")

    return value


def expect_only_known_fields(
    table: dict[str, object], allowed_fields: set[str], field: str = ""
) -> None:
    unknown_fields = table.keys() - allowed_fields

    if not unknown_fields:
        return

    field_name = min(unknown_fields)

    if field_name.isidentifier():
        field_path = f"{field}.{field_name}" if field else field_name
    else:
        # Quoting keeps dots and control characters inside a single key.
        field_path = f"{field}[{field_name!r}]"

    raise ValueError(f"{field_path}: unknown field")


def expect_string_table(value: object, field: str) -> dict[str, str]:
    table = expect_table(value, field)

    return {name: expect_string(item, f"{field}[{name!r}]") for name, item in table.items()}


def expect_string(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}: expected a string")

    return value


def expect_optional_string(value: object, field: str) -> str | None:
    if value is None:
        return None

    return expect_string(value, field)


def expect_integer(value: object, field: str) -> int:
    # bool is a subclass of int in Python, but a separate type in TOML.
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError(f"{field}: expected an integer")

    return value
