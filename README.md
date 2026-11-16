# Marcos bot (Python)

Личный Telegram-бот Marcos: ответы ИИ, голос, поиск, напоминания, утренняя сводка и автоответы за тебя (Telegram Business).

**Репозиторий держи PRIVATE**: в `bot.py` лежат ключи.

## Файлы
- `bot.py` — сам бот
- `requirements.txt` — зависимости (`pip install -r requirements.txt`)
- `.gitignore` — не пускает в репозиторий `data.json`, `.env` и кэш

## Запуск
```
pip install -r requirements.txt
python bot.py
```
Переменные окружения (необязательно): `TG_TOKEN`, `TG_ALLOWED` (id владельца), `KEY_*`.

## Новое в v49: автоответы за тебя
1. Нужен Telegram Premium.
2. В @BotFather: твой бот → Bot Settings → Business Mode → включить.
3. В Telegram: Настройки → Telegram для бизнеса → Чат-боты → выбери бота.
4. Боту в личку: `/auto on` (включить) / `/auto off` (выключить), `/persona текст` задаёт, как отвечать.
Копии ответов бот присылает тебе в чат с ним.

Бот запускается на любом сервере с Python 3.9+ (Render, Railway, VPS, свой ПК). Он работает через long polling и сам снимает вебхук. Не запускай его одновременно с Netlify-ботом на одном токене.
