# PeaceMusic

Discord‑бот, который умеет общаться (Gemini) и управлять музыкой в голосовых каналах. Поддерживает воспроизведение ссылок (YouTube и др. через yt‑dlp), перемотку и изменение громкости.

## Возможности
- AI‑чат на базе Google Gemini (включая обработку изображений/видео‑вложений)
- Музыкальный плеер: `play` (очередь), `skip`, `stop`, `seek`, `set_volume`, `summon`/`disconnect`
- SQLite‑память чата: последние реплики, семантическое воспоминание и фоновое глобальное summary

## Требования
- Python 3.10+
- FFmpeg в `PATH` (для `discord.FFmpegPCMAudio`)
- **Deno 2.3+** или **Node.js 22+** (нужен `yt-dlp` для YouTube; Docker-образ уже содержит Deno)
- Действующие ключи/токены: Discord Bot Token, Gemini API Key

## Структура проекта
- `main.py` — запуск бота (инициализация когов)
- `cogs/ai_cog.py` — совместимый re-export основного AI-кога
- `cogs/ai/` — AI-чат, вызовы Gemini, память, эмбеддинги и обработка вложений
- `cogs/music_cog.py` — логика плеера, очередь, голосовой канал
- `utils/` — схема Gemini Tool Calling (`tools.py`) и системные промпты
- `config.py` — типизированные настройки, загрузка переменных окружения из `.env`

## Установка и запуск (локально)
```bash
# 1) Клонируем репозиторий и заходим в папку
git clone https://github.com/Akinara666/PeaceMusic.git && cd PeaceMusic

# 2) Виртуальное окружение
python -m venv .venv
# Linux/macOS
source .venv/bin/activate
# Windows (PowerShell)
# .\.venv\Scripts\Activate.ps1

# 3) Зависимости
python -m pip install --upgrade pip
pip install -r requirements.txt

# 4) Конфигурация
cp .env.example .env  # Windows: copy .env.example .env
# Открой .env и заполни ключи/идентификаторы (см. раздел ниже)

# 5) Старт
python main.py
```

## Запуск через Docker (Рекомендуется для сервера)

1.  **Установите Docker и Docker Compose** на сервер.
2.  **Настройте .env** (как описано выше).
3.  **Запустите**:
    ```bash
    docker compose up -d --build
    ```
    Бот запустится в фоне и будет автоматически подниматься при перезагрузке сервера.

### Полезные команды
- **Пересоздание после изменения `.env`**: `docker compose up -d --force-recreate`
- **Логи**: `docker compose logs -f --tail=100`
- **Остановка**: `docker compose down`
- **Обновление готового образа**: `git pull && docker compose pull && docker compose up -d --force-recreate`
- **Пересборка из исходников**: `git pull && docker compose up -d --build`

### Переход со старых bind mounts на named volumes

Сначала проверьте, откуда работающий контейнер читает данные:

```bash
docker inspect "$(docker compose ps -q peacemusic)" \
  --format '{{range .Mounts}}{{println .Type .Source "->" .Destination}}{{end}}'
```

Если `/app/data` имеет тип `bind`, актуальная база находится в `./data`. Перед
первым запуском нового Compose выполните:

```bash
docker compose down
cp -a data "data.backup-$(date +%F-%H%M%S)"
cp -a music_files "music_files.backup-$(date +%F-%H%M%S)"

docker compose run --rm --user root \
  -v "$PWD/data:/source:ro" \
  --entrypoint sh peacemusic \
  -c 'cp -a /source/. /app/data/ && chown -R peacemusic:peacemusic /app/data'

docker compose run --rm --user root \
  -v "$PWD/music_files:/source:ro" \
  --entrypoint sh peacemusic \
  -c 'cp -a /source/. /app/music_files/ && chown -R peacemusic:peacemusic /app/music_files'

docker compose up -d --build
```

Не используйте `docker compose down -v`: `-v` удаляет named volumes.

### SOCKS-прокси на Docker-хосте

В bridge-режиме `127.0.0.1` означает сам контейнер. Compose явно добавляет
`host.docker.internal` через `host-gateway`, поэтому в `.env` нужно указать:

```env
GEMINI_SOCKS_PROXY=socks5://host.docker.internal:40000
```

xray должен слушать адрес Docker gateway или `0.0.0.0`, а не только
`127.0.0.1`. Закройте порт 40000 от внешнего интернета firewall-ом, разрешив
доступ только из Docker-сети.

Проверка из контейнера:

```bash
docker compose exec peacemusic python -c \
  "import socket; s=socket.create_connection(('host.docker.internal',40000),5); print('SOCKS reachable'); s.close()"
```

### Кастомный prompt в Docker

По умолчанию Compose монтирует `./utils/default_prompt.txt`. Для своего файла
добавьте в `.env`:

```env
BOT_PROMPT_HOST_FILE=./prompt.txt
```

Файл должен существовать до создания контейнера. Внутри контейнера он доступен
как `/app/config/prompt.txt`; значение `BOT_PROMPT_FILE` Compose выставляет
автоматически. У пользователя контейнера должно быть право чтения файла
(например, `chmod 644 prompt.txt`). После изменения пути или содержимого
выполните `docker compose up -d --force-recreate`: это корректно перемонтирует
файл, даже если редактор заменил его inode.


## Переменные окружения
Заполняются в `.env` (см. шаблон `.env.example`).

- `DISCORD_BOT_TOKEN` — токен Discord‑бота
- `CHATBOT_CHANNEL_ID` — ID текстового канала; если пусто, на сервере бот отвечает только на упоминания
- `GEMINI_API_KEY` — ключ Gemini Developer API
- `GEMINI_SOCKS_PROXY` — опциональный SOCKS5-прокси; для прокси на Docker-хосте используйте `socks5://host.docker.internal:40000`
- `CHAT_MEMORY_DB` — путь к SQLite‑базе памяти (по умолчанию `chat_memory.sqlite3`; в Docker переопределяется на `/app/data/chat_memory.sqlite3`)
- `GEMINI_RESPONSE_MODEL` — модель генерации ответов (по умолчанию `gemini-3.1-flash-lite`)
- `GEMINI_SUMMARY_MODEL` — модель для фонового summary (по умолчанию `gemini-3.1-flash-lite`)
- `GEMINI_EMBEDDING_MODEL` — модель эмбеддингов для семантической памяти (по умолчанию `gemini-embedding-2`)
- `GEMINI_EMBEDDING_DIMENSIONS` — размерность эмбеддингов (по умолчанию `768`)
- `GEMINI_THINKING_BUDGET` — бюджет reasoning-токенов (по умолчанию `8192`)
- `GEMINI_TEMPERATURE` / `GEMINI_TOP_P` — параметры генерации (`1.0` / `0.95`)
- `GEMINI_REQUEST_TIMEOUT_MS` — тайм-аут одного запроса Gemini в миллисекундах (`24000`)
- `MUSIC_DIRECTORY` — путь для кэша/локальных файлов (по умолчанию `music_files`)
- `BOT_PROMPT_FILE` — путь к prompt при локальном запуске
- `BOT_PROMPT_HOST_FILE` — host-путь к prompt для Docker Compose
- `YTDL_USE_COOKIES` — включает cookies для `yt-dlp` (по умолчанию `false`)
- `YTDL_COOKIE_FILE` — путь к cookies-файлу в формате Netscape для локального запуска; внутри Docker Compose задаёт путь автоматически
- `YTDL_COOKIE_HOST_FILE` — путь к cookies-файлу на Docker-хосте, например `./data/cookies.txt`
- `YTDL_CACHE_DIR` — постоянный кэш yt-dlp (по умолчанию `data/ytdl_cache`)
- `MUSIC_QUEUE_MAX_SIZE` — максимальный размер очереди (`50`)
- `MUSIC_ATTACHMENT_MAX_BYTES` — максимальный размер музыкального вложения (`25000000`)
- `MEDIA_ALLOWED_DOMAINS` — разрешённые домены для удалённых медиа
- `AI_RATE_LIMIT_MAX_REQUESTS` / `AI_RATE_LIMIT_WINDOW_SECONDS` — лимит AI-запросов (`20` за `60` секунд)
- `AI_ATTACHMENT_MAX_BYTES` / `AI_ATTACHMENT_MAX_COUNT` — лимиты AI-вложений (`25000000`, `4`)
- `AI_MAX_CONCURRENT_TURNS` — число одновременно обрабатываемых AI-диалогов (`4`)
- `AI_TURN_TIMEOUT_SECONDS` — общий тайм-аут AI-диалога (`120` секунд)
- `AI_REQUIRE_MENTION_WHEN_UNSCOPED` — требовать упоминание, если канал не закреплён (`true`)
- `MEMORY_RECENT_MESSAGES` — число последних сообщений в контексте (`12`)
- `MEMORY_SEMANTIC_RESULTS` / `MEMORY_SEMANTIC_MIN_SCORE` — число и минимальная релевантность семантических результатов (`6`, `0.35`)
- `MEMORY_SUMMARY_TRIGGER` / `MEMORY_SUMMARY_WINDOW` — порог и размер окна фонового summary (`30`, `40`)
- `MEMORY_SEMANTIC_HALF_LIFE_DAYS` — период полураспада весов старых воспоминаний (`30`; `0` отключает decay)
- `MEMORY_SEMANTIC_CANDIDATES` — максимум кандидатов семантического поиска (`1000`)
- `MEMORY_RAW_RETENTION_DAYS` — хранение уже суммаризированных сырых сообщений (`90`; `0` отключает очистку по возрасту)

Для секретов можно использовать `DISCORD_BOT_TOKEN_FILE` и
`GEMINI_API_KEY_FILE` вместо размещения значений непосредственно в окружении.

`GEMINI_SOCKS_PROXY` применяется ко всем вызовам Gemini SDK: генерации ответов, эмбеддингам, проверкам файлов и фоновому summary.

## Cookies для yt-dlp
- По умолчанию cookies выключены.
- Для Docker выставь `YTDL_USE_COOKIES=true` и `YTDL_COOKIE_HOST_FILE=./data/cookies.txt`. Compose монтирует файл с хоста read-only как `/app/config/cookies.txt`; в named volume он не копируется.
- После изменения пути или содержимого файла выполни `docker compose up -d --force-recreate`: редактор может заменить inode файла, а обычный `restart` не пересоздаёт bind mount.
- Файл должен начинаться с `# Netscape HTTP Cookie File` и быть доступен пользователю контейнера для чтения (например, `chmod 644 data/cookies.txt`).

## Команды/возможности (в чате)
Ассистент сам вызывает музыкальные функции через Tool Calling — просто пиши: «включи <трек>», «перемотай на 1:23», «сделай громкость 50%», «пропусти трек», «останови музыку», «зайди ко мне в голосовой» и т.п.

## Slash-команды
- `/bot_access action:<Отключить|Включить|Статус> member:<пользователь>` — управляет тем, может ли выбранный участник сервера общаться с ботом в текстовом чате. Нужны права `Manage Server` или администратора.
- `/bot_speech action:<Mute|Unmute|Status>` — Включает или отключает тихий режим (бот не реагирует на сообщения) для текущего канала. Нужны права `Manage Messages`.

## Обновление

Локальный запуск:

```bash
git pull
pip install -r requirements.txt
```

Docker с опубликованным образом:

```bash
git pull
docker compose pull
docker compose up -d --force-recreate
```

Чтобы собрать текущие исходники прямо на сервере вместо загрузки готового
образа:

```bash
docker compose up -d --build
```

Если в логах осталась строка `No supported JavaScript runtime`, убедитесь, что
запущен новый контейнер: `docker compose exec peacemusic deno --version`.
