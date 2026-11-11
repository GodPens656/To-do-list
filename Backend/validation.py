MAX_TEXT_LENGTH = 1000
MAX_GROUP_NAME_LENGTH = 100


def text_length_error(text, max_length=MAX_TEXT_LENGTH):
    """Count the original text, including whitespace, before storage encoding."""
    length = len(text or "")
    if length > max_length:
        return f"Максимум {max_length} символов. Сейчас: {length}."
    return None
