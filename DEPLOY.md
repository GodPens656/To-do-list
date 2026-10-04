# Деплой на VPS

Перед запуском скопируйте `secret.example.py` в `secret.py` и заполните
секреты по [README.md](README.md). Этот файл не хранится в Git: его нужно
отдельно перенести на сервер. В текущем `main.py` по умолчанию выбран
настольный режим. Для этой инструкции раскомментируйте `view`, `host` и
`port` в вызове `ft.run(...)`, как показано в README.

## Что было изменено (кратко)

1. **Уведомления на сайте отключены полностью** (`Backend/notifications.py`,
   параметр `web=True`). Причина: в актуальной версии Flet (проверено на
   0.86.2) у `page` больше нет `eval_js`/`run_javascript` — выполнить
   произвольный JS и дёрнуть browser Notification API из Python сейчас
   нечем. Ни на телефоне, ни на ПК в браузере уведомления показываться не
   будут — это осознанное решение по вашей просьбе.

2. **Локальные дела и настройки** хранятся в браузере посетителя через
   `page.shared_preferences` (`Backend/webstorage.py`) — это актуальный аналог
   `client_storage` в вашей версии Flet (сам `client_storage` в 0.86.2 уже
   убран из API). Работает так же, как вы просили: у каждого, кто открыл
   сайт, свои дела/настройки, отдельно от остальных посетителей и отдельно
   от файлов на сервере.

3. **Телефон/ПК определяется по `page.client_user_agent`** — но **только
   влияет на вёрстку** интерфейса, как вы и уточнили. К уведомлениям это
   больше никак не относится.

## Важный нюанс, который стоит знать

В текущей веб-ветке локальные данные, настройки и состояние входа хранятся
через `WebSessionStore`, отдельно для каждой браузерной сессии. Облачная
синхронизация использует общий токен из `secret.py` и аккаунты в каталоге
`/For_to-do` на Яндекс Диске. Название папки аккаунта включает логин и
пароль; это ограничение текущей схемы, описанное в README.

## requirements.txt

Находится в корне репозитория. **Не** включает `flet_permission_handler` и
`flet_local_notifications` — это Android-плагины, из-за которых `pip`
откатывает Flet до старой версии 0.28.3 (проверил на практике). Для сайта
они не нужны — код уже не пытается их импортировать, когда работает как
сайт.

Если у вас есть отдельная мобильная сборка этого же проекта — держите её
зависимости в отдельном requirements-файле/venv, не смешивайте с этим.

## Локальная проверка перед деплоем

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
python3 main.py
```

Приложение поднимется на `http://0.0.0.0:8550`. Порт и хост можно менять
переменными окружения `ND_PORT` и `ND_HOST` — код это уже поддерживает.

## Деплой на VPS (Ubuntu, systemd + Nginx)

### 1. Подготовка

```bash
sudo apt update && sudo apt install -y python3-venv nginx
sudo mkdir -p /opt/nd
# скопируйте сюда файлы проекта (все .py, requirements.txt, assets/ если есть)
cd /opt/nd
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
deactivate
```

### 2. systemd-сервис

Файл `/etc/systemd/system/nd-todo.service`:

```ini
[Unit]
Description=ND To-Do (Flet web)
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/nd
Environment=ND_HOST=127.0.0.1
Environment=ND_PORT=8550
Environment=ND_ASSETS_DIR=/opt/nd/assets
ExecStart=/opt/nd/venv/bin/python3 /opt/nd/main.py
Restart=on-failure
RestartSec=3
User=www-data

[Install]
WantedBy=multi-user.target
```

Слушаем на `127.0.0.1`, наружу отдаёт Nginx — это безопаснее и позволяет
навесить HTTPS.

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now nd-todo
sudo systemctl status nd-todo
```

### 3. Nginx как reverse proxy (с поддержкой WebSocket)

Flet-клиент общается с сервером через WebSocket — без этих заголовков
приложение просто не подключится. Файл
`/etc/nginx/sites-available/nd-todo`:

```nginx
server {
    listen 80;
    server_name your-domain.example;

    location / {
        proxy_pass http://127.0.0.1:8550;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_read_timeout 3600s;
    }
}
```

```bash
sudo ln -s /etc/nginx/sites-available/nd-todo /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

### 4. HTTPS

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d your-domain.example
```

После этого сайт будет доступен по `https://your-domain.example`.

## Как проверить, что хранилище в браузере реально работает

1. Откройте сайт, добавьте пару дел.
2. Откройте DevTools → Application → Local Storage → ваш домен — там
   должен появиться ключ `nd_appdata` (или похожий, в зависимости от того,
   как Flet называет ключи shared_preferences в вашей версии).
3. Откройте сайт в режиме инкогнито / другом браузере — там будет
   пустой список дел (это отдельный посетитель, отдельное хранилище).
4. Перезагрузите обычную вкладку — дела должны остаться на месте.
