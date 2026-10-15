"""Скопируйте в secret.py и заполните локальные значения перед запуском."""

# Общий Dropbox для синхронизации. Это не логин/пароль внутри дневника.
# Быстрая проверка: Generated access token из Dropbox App Console.
# Такой токен истекает; для постоянной работы используйте refresh token.
DROPBOX_ACCESS_TOKEN = ""
# App key из App Console и результат python configure_dropbox.py.
DROPBOX_APP_KEY = ""
DROPBOX_REFRESH_TOKEN = ""
# Не нужен для PKCE (configure_dropbox.py). Нужен для refresh token,
# полученного обычным OAuth code flow с секретом приложения.
DROPBOX_APP_SECRET = ""

# Непустая секретная фраза. На всех устройствах одного аккаунта — одинаковая.
# Для существующих сохранений используйте прежнее значение:
# новое слово не сможет расшифровать старые данные и резервные копии.
ENCRYPTION_KEYWORD = ""
