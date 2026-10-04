"""Проверка отдельного пароля для входа в приложение."""

import hashlib
import hmac
import secrets


ITERATIONS = 600_000
MAX_PASSWORD_LENGTH = 1024


def validate_password(password):
    if not isinstance(password, str) or not password.strip():
        raise ValueError("Введите пароль.")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError("Пароль слишком длинный (максимум 1024 символа).")


def hash_password(password):
    validate_password(password)
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"pbkdf2_sha256${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password, encoded):
    if not isinstance(password, str) or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256" or int(iterations) != ITERATIONS:
            return False
        salt, expected = bytes.fromhex(salt), bytes.fromhex(expected)
        if len(salt) != 16 or len(expected) != 32:
            return False
    except (AttributeError, TypeError, ValueError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return hmac.compare_digest(actual, expected)
