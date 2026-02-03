# PeaceMusic

Discord‑бот, который умеет общаться (Gemini) и управлять музыкой в голосовых каналах. Поддерживает воспроизведение ссылок (YouTube и др. через yt‑dlp), перемотку и изменение громкости.

## Возможности
- AI‑чат на базе Google Gemini (включая обработку изображений/видео‑вложений)
- Музыкальный плеер: `play` (очередь), `skip`, `stop`, `seek`, `set_volume`, `summon`/`disconnect`
- Очередь треков с информативными эмбедами

## Требования
- Python 3.10+
- FFmpeg в `PATH` (для `discord.FFmpegPCMAudio`)
- **Deno** или **Node.js** (необходим для работы `yt-dlp` с YouTube)
- Действующие ключи/токены: Discord Bot Token, Gemini API Key

## Структура проекта
- `main.py` — запуск бота (инициализация когов)
- `cogs/ai_cog.py` — чат‑ассистент и обработка вложений
- `cogs/music_cog.py` — логика плеера, очередь, голосовой канал
- `utils/` — утилиты: голос Gemini (`gemini_voice.py`), инструменты для Gemini Tool Calling (`tools.py`), дефолтный системный промпт
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
    docker-compose up -d --build
    ```
    Бот запустится в фоне и будет автоматически подниматься при перезагрузке сервера.

### Полезные команды
- **Перезапуск**: `docker-compose restart` (например, после смены конфига)
- **Логи**: `docker-compose logs -f --tail=100`
- **Остановка**: `docker-compose down`


## Переменные окружения
Заполняются в `.env` (см. шаблон `.env.example`).

- `DISCORD_BOT_TOKEN` — токен Discord‑бота
- `CHATBOT_CHANNEL_ID` — ID текстового канала для общения с ассистентом (опционально; если пусто — слушает все)
- `GEMINI_API_KEY` — ключ Gemini Developer API
- `MUSIC_DIRECTORY` — путь для кэша/локальных файлов (по умолчанию `music_files`)

## Команды/возможности (в чате)
Ассистент сам вызывает музыкальные функции через Tool Calling — просто пиши: «включи <трек>», «перемотай на 1:23», «сделай громкость 50%», «пропусти трек», «останови музыку», «зайди ко мне в голосовой» и т.п.

## Обновление
```bash
git pull
pip install -r requirements.txt
```
