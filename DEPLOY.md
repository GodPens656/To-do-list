# Развёртывание сайта на Ubuntu 24.04

Инструкция для исходников в `/home/admin/projects/to-do`. Имя systemd-сервиса —
`to-do`, файл сервиса — `/etc/systemd/system/to-do.service`.

Схема: браузер → Nginx на портах 80/443 → Flet на `127.0.0.1:8550`.
Все команды ниже выполняйте **на VPS под пользователем `admin` с доступом к `sudo`**.
Если вы вошли от `root`, сначала переключитесь командой `su - admin`.
Вместо `todo.example.com` указывайте свой домен.

В проекте закреплён Flet 0.82.0. Веб-режим включим переменными окружения:
менять `main.py` и раскомментировать `view`, `host`, `port` не требуется.
Flet поддерживает принудительный серверный режим и настройку адреса/порта
через [переменные окружения](https://flet.dev/docs/reference/environment-variables/).

## 1. Установить системные пакеты и зависимости

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip nginx curl nano ufw

sudo chown -R admin: /home/admin/projects/to-do

cd /home/admin/projects/to-do
python3 --version
ls main.py requirements.txt secret.example.py assets

python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
```

На стандартной Ubuntu 24.04 используется Python 3.12. Создавайте `.venv`
на самом VPS: виртуальное окружение из Windows для Linux не подходит.
Загружайте проект вместе с каталогами `Frontend`, `Backend` и `assets`.
Команда `chown` назначает `admin` владельцем проекта, включая файлы,
которые могли остаться от прежней установки под `root`. Создание `.venv`,
установку Python-зависимостей и редактирование `secret.py` выполняйте от `admin`.

Используйте версии из `requirements.txt`. Веб-режиму не нужны Android-плагины
`flet_permission_handler` и `flet_local_notifications`.

Для Flet 0.82.0 в `requirements.txt` задано `fastapi>=0.115.12,<0.145`.
В FastAPI 0.145 удалён параметр `openapi_prefix`, который передаёт эта версия
Flet. Без верхнего ограничения новая установка может завершаться ошибкой
`FastAPI.__init__() got an unexpected keyword argument 'openapi_prefix'`.
Разработчики Flet описали причину и обходной путь в
[issue #6984](https://github.com/flet-dev/flet/issues/6984).

## 2. Подготовить secret.py

Если `secret.py` уже перенесён на сервер, сохраните его. Если файла ещё нет,
создайте из шаблона:

```bash
cd /home/admin/projects/to-do
if [ ! -f secret.py ]; then
    cp secret.example.py secret.py
fi
nano secret.py
```

Обязательно задайте непустой `ENCRYPTION_KEYWORD`. Для существующих аккаунтов
и сохранений перенесите **прежнее значение**, иначе данные не расшифруются.
Это значение в текущем коде читается именно из `secret.py`.

Для облачной синхронизации заполните `DROPBOX_APP_KEY` и
`DROPBOX_REFRESH_TOKEN`. Получить refresh token можно так:

```bash
/home/admin/projects/to-do/.venv/bin/python /home/admin/projects/to-do/configure_dropbox.py
```

Откройте выданную ссылку в браузере на своём компьютере, разрешите доступ,
введите код в терминале VPS и перенесите полученные строки в `secret.py`.
Подготовка приложения Dropbox описана в [README.md](README.md#получение-ключа-и-токенов-dropbox).
При использовании этого скрипта `DROPBOX_ACCESS_TOKEN` и `DROPBOX_APP_SECRET`
можно оставить пустыми. Без настройки Dropbox доступны локальные дела;
облачные функции потребуют токены.

После сохранения файла ограничьте доступ и проверьте импорты:

```bash
cd /home/admin/projects/to-do
chmod 600 secret.py
.venv/bin/python -c 'import flet; import flet_web; import main; print("Импорты OK")'
.venv/bin/python -c 'from flet_web.fastapi import FastAPI; FastAPI(on_startup=[]); print("Веб-зависимости OK")'
```

Если команда завершилась с ошибкой, устраните её до запуска сервиса.
`secret.py` исключён из Git: обычный `git clone` его не переносит.

## 3. Создать сервис to-do

Скопируйте блок целиком:

```bash
sudo tee /etc/systemd/system/to-do.service > /dev/null <<'EOF'
[Unit]
Description=To-do Flet website
Wants=network-online.target
After=network-online.target

[Service]
Type=simple
User=admin
WorkingDirectory=/home/admin/projects/to-do
Environment=PYTHONUNBUFFERED=1
Environment=FLET_FORCE_WEB_SERVER=true
Environment=FLET_SERVER_IP=127.0.0.1
Environment=FLET_SERVER_PORT=8550
Environment=ND_ASSETS_DIR=/home/admin/projects/to-do/assets
Environment=ND_TIMEZONE=Europe/Moscow
ExecStart=/home/admin/projects/to-do/.venv/bin/python /home/admin/projects/to-do/main.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemd-analyze verify /etc/systemd/system/to-do.service
sudo systemctl daemon-reload
sudo systemctl enable --now to-do
sudo systemctl status to-do --no-pager --full
```

Ожидаемый статус — `active (running)`. Сервис будет запускаться после
перезагрузки VPS и перезапускаться при аварийном завершении процесса.

Сервис запускается от `admin`; его рабочий каталог — `/home/admin/projects/to-do`.
Nginx получает страницы через HTTP, поэтому ему доступ к исходникам не нужен.

Если сервис уже создан по инструкции со старым путём, замените его содержимое
блоком выше и примените изменения:

```bash
sudo systemctl daemon-reload
sudo systemctl restart to-do
sudo systemctl status to-do --no-pager --full
```

`FLET_FORCE_WEB_SERVER=true` включает веб-режим без открытия графического окна.
`FLET_SERVER_IP` и `FLET_SERVER_PORT` задают адрес и порт напрямую в Flet,
даже когда параметры `host` и `port` в `main.py` закомментированы.

Проверьте приложение из терминала VPS:

```bash
curl -I http://127.0.0.1:8550/
sudo ss -ltnp 'sport = :8550'
```

Ожидается ответ `200 OK` и прослушивание `127.0.0.1:8550`. Если сервер ещё
запускается, повторите проверку через несколько секунд. При ошибке смотрите:

```bash
sudo journalctl -u to-do -n 100 --no-pager
```

## 4. Настроить Nginx

Если используете домен, создайте у DNS-провайдера A-запись на IPv4-адрес VPS.
Если есть AAAA-запись, она должна указывать на рабочий IPv6 этого же VPS.

Откройте конфигурацию сайта:

```bash
sudo nano /etc/nginx/sites-available/to-do
```

Вставьте конфигурацию, заменив домен:

```nginx
server {
    listen 80;
    listen [::]:80;
    server_name todo.example.com;

    client_max_body_size 32m;

    location / {
        proxy_pass http://127.0.0.1:8550;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_buffering off;
        proxy_read_timeout 3600s;
        proxy_send_timeout 3600s;
    }
}
```

Flet использует WebSocket. Заголовки `Upgrade` и `Connection` нужны для
соединения браузера с приложением; настройка описана в
[документации Nginx](https://nginx.org/en/docs/http/websocket.html).

**Если домена пока нет:** вместо `todo.example.com` в `server_name` укажите
реальный публичный IPv4-адрес VPS. Например: `server_name 203.0.113.10;`
(это только пример адреса). Тогда открывайте сайт по `http://ВАШ_IP`.

Включите сайт и проверьте конфигурацию:

```bash
sudo ln -sfn /etc/nginx/sites-available/to-do /etc/nginx/sites-enabled/to-do
sudo nginx -t
```

Если проверка успешна, примените настройки:

```bash
sudo systemctl enable --now nginx
sudo systemctl reload nginx
```

Файлы других сайтов в `sites-enabled` можно оставить. Nginx выберет этот
сайт по значению `server_name`.

## 5. Проверить доступ извне

Посмотрите состояние UFW:

```bash
sudo ufw status
```

Если UFW активен, разрешите веб-трафик:

```bash
sudo ufw allow 80/tcp
sudo ufw allow 443/tcp
```

Если у хостера есть отдельный сетевой фаервол, разрешите в нём входящие
TCP-подключения на 80 и 443. Порт 8550 открывать наружу не требуется.

Откройте в браузере `http://todo.example.com` или `http://ВАШ_IP`,
в зависимости от выбранного `server_name`.

## 6. Подключить HTTPS для домена

Выполняйте этот шаг, когда домен уже указывает на VPS и сайт доступен
снаружи по HTTP. Для варианта с IP-адресом вернитесь к этому шагу после
подключения домена.

Установите Certbot и его Nginx-плагин из репозиториев Ubuntu 24.04:
[certbot](https://packages.ubuntu.com/noble/certbot),
[python3-certbot-nginx](https://packages.ubuntu.com/noble/python3-certbot-nginx).

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx --redirect -d todo.example.com
```

Введите email и примите условия Let's Encrypt. Certbot настроит сертификат
и перенаправление с HTTP на HTTPS. Итоговый адрес — `https://todo.example.com`.

Включите автоматическое продление и проверьте его:

```bash
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

## 7. Проверить приложение в браузере

1. Откройте итоговый адрес сайта и добавьте тестовое дело.
2. Перезагрузите страницу: дело должно сохраниться.
3. Откройте сайт в другом браузере или инкогнито: локальный список будет отдельным.
4. Если настроен Dropbox, проверьте вход и синхронизацию одного аккаунта
   на двух устройствах.

Локальные дела, настройки и состояние входа хранятся у посетителя в браузере
через `page.shared_preferences`, а не в общих файлах `saves/` на VPS.
Очистка данных сайта удаляет локальное хранилище. HTTP, HTTPS, IP-адрес и
домен считаются разными адресами хранилища: переход на итоговый домен с HTTPS
не переносит локальные дела автоматически. Для переноса используйте
синхронизацию аккаунта.

Браузерные уведомления в текущем проекте отключены. Облачная синхронизация
использует общий Dropbox, а имена папок аккаунтов включают логин и пароль;
подробности текущей схемы есть в [README.md](README.md#хранение-данных-и-секретов).

## Управление и обновление

```bash
# Статус
sudo systemctl status to-do --no-pager --full

# Перезапуск после изменения кода или secret.py
sudo systemctl restart to-do

# Остановка
sudo systemctl stop to-do

# Запуск
sudo systemctl start to-do

# Логи в реальном времени; Ctrl+C завершает просмотр
sudo journalctl -u to-do -f
```

Для обновления загрузите новые исходники в `/home/admin/projects/to-do`, сохранив
`secret.py`. Затем выполните:

```bash
cd /home/admin/projects/to-do
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
sudo systemctl restart to-do
sudo systemctl status to-do --no-pager --full
curl -I http://127.0.0.1:8550/
```

После изменения самого `to-do.service` дополнительно нужны
`sudo systemctl daemon-reload` и `sudo systemctl restart to-do`.

## Если что-то не работает

- **Ошибка `unexpected keyword argument 'openapi_prefix'`:** Flet 0.82.0
  несовместим с FastAPI 0.145 и новее. В файле `requirements.txt` на VPS
  должна быть строка `fastapi>=0.115.12,<0.145`. Чтобы исправить уже
  установленное окружение, выполните от `admin`:

  ```bash
  cd /home/admin/projects/to-do
  sudo systemctl stop to-do
  .venv/bin/python -m pip install 'fastapi>=0.115.12,<0.145'
  .venv/bin/python -m pip check
  .venv/bin/python -c 'from flet_web.fastapi import FastAPI; FastAPI(on_startup=[]); print("Веб-зависимости OK")'
  sudo systemctl restart to-do
  sudo systemctl status to-do --no-pager --full
  ```

  При ошибке установки или проверки устраните её перед перезапуском сервиса.
  Исправление в самом Flet выпущено в
  [версии 1.0.5](https://github.com/flet-dev/flet/releases/tag/v1.0.5).
  Переход проекта с 0.82.0 на 1.x требует отдельной проверки кода,
  интерфейса и `flet-color-pickers`; для этого исправления он не требуется.

- **502 Bad Gateway:** проверьте `sudo systemctl status to-do`,
  `sudo journalctl -u to-do -n 100 --no-pager` и `curl -I http://127.0.0.1:8550/`.
- **Страница Welcome to nginx:** проверьте `server_name`, адрес в браузере,
  DNS и наличие ссылки `/etc/nginx/sites-enabled/to-do`.
- **Страница загружается, но интерфейс не подключается:** проверьте WebSocket
  `/ws` в DevTools → Network. При успешном подключении ожидается статус 101.
  Если используется дополнительный прокси/CDN, он тоже должен пропускать WebSocket.
- **Ошибка секретной фразы:** проверьте наличие `secret.py` и непустой
  `ENCRYPTION_KEYWORD`; для прежних данных используйте прежнюю фразу.
- **Не работает облако:** проверьте `DROPBOX_APP_KEY`, refresh token,
  разрешения приложения Dropbox и исходящий доступ VPS в интернет.
- **Ошибка сервиса `CHDIR` или `EXEC`:** проверьте путь `/home/admin/projects/to-do`,
  наличие `.venv/bin/python` и совпадение путей в файле сервиса.
- **Не выдаётся сертификат:** проверьте DNS A/AAAA и доступность порта 80
  снаружи; HTTP-проверка Let's Encrypt должна попадать на этот VPS.
