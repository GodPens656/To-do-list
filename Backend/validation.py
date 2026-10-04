MAX_TEXT_LENGTH = 700


def text_length_error(text):
    """Count the original text, including whitespace, before storage encoding."""
    length = len(text or "")
    if length > MAX_TEXT_LENGTH:
        return f"Максимум {MAX_TEXT_LENGTH} символов. Сейчас: {length}."
    return None
