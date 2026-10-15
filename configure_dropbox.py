"""Получить Dropbox refresh token через PKCE без секрета приложения."""

from getpass import getpass

from dropbox import DropboxOAuth2FlowNoRedirect


SCOPES = ["files.metadata.read", "files.content.read", "files.content.write"]


def main():
    app_key = input("App key из Dropbox App Console: ").strip()
    if not app_key:
        print("App key не указан.")
        return 1
    flow = DropboxOAuth2FlowNoRedirect(
        app_key, use_pkce=True, token_access_type="offline", scope=SCOPES,
    )
    print("Откройте ссылку в браузере и разрешите доступ к Dropbox:")
    print(flow.start())
    code = getpass("Вставьте код авторизации (ввод скрыт): ").strip()
    try:
        result = flow.finish(code)
    except Exception:
        print("Не удалось получить токен. Проверьте код, разрешения и интернет; "
              "запустите скрипт заново.")
        return 1
    if not result.refresh_token:
        print("Dropbox не вернул refresh token. Повторите авторизацию.")
        return 1
    print("Добавьте эти строки в существующий secret.py, сохранив ENCRYPTION_KEYWORD:")
    print(f"DROPBOX_APP_KEY = {app_key!r}")
    print(f"DROPBOX_REFRESH_TOKEN = {result.refresh_token!r}")
    print('DROPBOX_ACCESS_TOKEN = ""')
    print('DROPBOX_APP_SECRET = ""')
    print("Храните токен приватно. Перезапустите дневник после настройки.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
