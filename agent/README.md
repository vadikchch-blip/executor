# Mac Agent (Railway UI Job Queue Poller)

Агент для опроса очереди UI-задач на Railway и выполнения их через локальный UI executor на Mac.

## Требования

1. **Локальная репа executor** (эта репа)
2. **Запущенный локальный UI executor** (Flask) на `127.0.0.1`, порт по выбору (например 5050 или 8787)
3. **Переменные окружения** (см. ниже)

Никакой зависимости от репы бота на локальном Mac.

## Переменные окружения

### Обязательные

| Переменная | Описание | Пример |
|-----------|----------|--------|
| `RAILWAY_URL` | URL бота на Railway | `https://magatron-trello-bot-production.up.railway.app` |
| `UI_AGENT_TOKEN` | Секрет для `/ui/next` и `/ui/result` | *(секрет)* |
| `LOCAL_UI_EXECUTOR_URL` | URL локального executor | `http://127.0.0.1:5050` |
| `LOCAL_UI_EXECUTOR_TOKEN` | Секрет для X-Executor-Token | *(секрет)* |

### Опциональные (дефолты)

| Переменная | Default | Описание |
|-----------|---------|----------|
| `AGENT_ID` | hostname | Идентификатор агента |
| `POLL_INTERVAL_SEC` | 2 | Интервал опроса при 204 |
| `LOCAL_EXECUTOR_CONNECT_TIMEOUT` | 5 | Таймаут подключения к executor (сек) |
| `LOCAL_EXECUTOR_READ_TIMEOUT` | 120 | Таймаут чтения ответа executor (сек) |
| `RAILWAY_CONNECT_TIMEOUT` | 5 | Таймаут Railway (сек) |
| `RAILWAY_READ_TIMEOUT` | 30 | Таймаут чтения Railway (сек) |
| `MAX_RETRIES` | 3 | Повторы при ошибке сети |
| `BACKOFF_BASE_SEC` | 1 | База экспоненциального backoff |

## Запуск

### Зависимости

```bash
pip install -r agent/requirements-agent.txt
```

### Запуск одной командой

```bash
cd /path/to/executor-repo

export RAILWAY_URL="https://magatron-trello-bot-production.up.railway.app"
export UI_AGENT_TOKEN="your-secret"
export LOCAL_UI_EXECUTOR_URL="http://127.0.0.1:5050"
export LOCAL_UI_EXECUTOR_TOKEN="your-local-secret"

python3 agent/mac_agent_poll.py
```

Или через скрипт:

```bash
cd /path/to/executor-repo
export RAILWAY_URL=... UI_AGENT_TOKEN=... LOCAL_UI_EXECUTOR_URL=... LOCAL_UI_EXECUTOR_TOKEN=...
./agent/run_mac_agent.sh
```

## Smoke test

1. **Проверить, что локальный executor работает:**
   ```bash
   curl -H "X-Executor-Token: $LOCAL_UI_EXECUTOR_TOKEN" http://127.0.0.1:5050/health
   ```

2. **Проверить /ui/next (должен вернуть 204 или job):**
   ```bash
   curl -H "X-UI-Agent-Token: $UI_AGENT_TOKEN" \
     "$RAILWAY_URL/ui/next?agent_id=test"
   ```
   Ожидаемый ответ: 204 No Content (если очередь пуста) или JSON с job_id и steps.

3. **Запустить агент:**
   ```bash
   python3 agent/mac_agent_poll.py
   ```

4. **Создать job через Telegram** («Мага …») и убедиться:
   - агент забрал job (в логах: "Executing job ... with N step(s)")
   - локально появились свежие png в artifacts
   - в Telegram пришёл отчёт и свежий скриншот, а не старый
