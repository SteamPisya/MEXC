# MEXC Futures Stackable Consolidations Scanner

Асинхронный торговый бот для сканирования фьючерсов MEXC, поиска паттерна «стекающиеся консолидации», отслеживания результатов (TP/SL) и отправки уведомлений в Telegram с графиками.

## 🏗 Архитектура

```
[Config] → [AsyncExchange (Rate-Limited)] → [CandleFetcher]
                                                                           ↓
                                                                   [PatternEngine (Vectorized)]
                                                                           ↓
                                                                   [SignalManager (SQLite WAL)]
                                                                           ↓
                                                                   [ResultTracker (TP/SL Checker)]
                                                                           ↓
                                                                   [TelegramNotifier (aiogram)]
                                                                           ↓
                                                                   [StatsReporter (Image-Only)]
```

## 📦 Установка

1. **Клонируйте репозиторий:**
```bash
cd /workspace
```

2. **Установите зависимости:**
```bash
pip install -r requirements.txt
```

3. **Настройте переменные окружения:**
```bash
cp .env.example .env
```

4. **Заполните `.env` файл:**
```env
# MEXC API Credentials (опционально для публичных данных)
MEXC_API_KEY=your_api_key
MEXC_API_SECRET=your_api_secret

# Telegram Bot Configuration
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Database Settings
DATABASE_PATH=signals.db

# Bot Settings
SCAN_INTERVAL_MINUTES=1
LOG_LEVEL=INFO

# Pattern Detection
MIN_AMPLITUDE_PCT=0.5
MAX_AMPLITUDE_PCT=3.0
MIN_CONSOLIDATION_LENGTH=5
Y_GAP_PCT=0.3
X_GAP_CANDLES=3

# Trading Parameters
TP_PERCENT=2.0
SL_PERCENT=1.0
```

## 🚀 Запуск

```bash
python main.py
```

## 📁 Структура проекта

```
/workspace
├── config.py           # Конфигурация через pydantic-settings
├── database.py         # SQLite с WAL режимом
├── exchange.py         # CCXT async клиент для MEXC
├── pattern_engine.py   # Векторизованный поиск паттернов
├── result_tracker.py   # Проверка TP/SL
├── chart_generator.py  # Генерация графиков в ThreadPool
├── telegram_bot.py     # aiogram 3.x уведомления
├── main.py             # Оркестратор
├── requirements.txt    # Зависимости
├── .env.example        # Шаблон конфигурации
└── README.md           # Документация
```

## 🔧 Модули

### config.py
Типизированная конфигурация через pydantic-settings с поддержкой .env файлов.

### exchange.py
- Асинхронный клиент ccxt.mexc
- Rate limiting (250ms между запросами)
- Экспоненциальный backoff при ошибках 510
- Семафор для ограничения параллельных запросов (5 максимум)

### pattern_engine.py
- Векторизованный поиск консолидаций через pandas rolling windows
- O(n) сложность вместо O(n²)
- Параметры: min/max амплитуда, длина консолидации, gap между зонами

### database.py
- SQLite с journal_mode=WAL и synchronous=NORMAL
- Таблица signals с индексами по статусу и времени
- Методы: save_signal, get_pending_by_symbol, update_status, get_stats

### result_tracker.py
- Проверка TP/SL по теням свечей (low/high)
- Фильтрация по entry_time (не по индексу!)
- Расчет PnL для закрытых сигналов

### chart_generator.py
- Генерация в ThreadPoolExecutor(max_workers=2)
- Таймаут 15 секунд на график
- Валидация границ: start_idx = max(0, entry_idx - 60)
- Аннотации с вертикальным смещением (ax=0, ay=±30)

### telegram_bot.py
- aiogram 3.x с retry-логикой (3 попытки)
- reply_to_message_id для тредирования результатов
- Fallback на текст при ошибке генерации графика
- Статистика отправляется только картинкой

### main.py
- Бесконечный цикл с asyncio.sleep(60)
- Параллельное обновление свечей (Semaphore=5)
- Приоритет проверки pending сигналов над поиском новых
- Graceful shutdown по Ctrl+C

## ⚡ Ключевые особенности

### Надежность
- ✅ Никаких `df.iloc[saved_index]` после обновления данных
- ✅ Поиск свечи входа всегда по `entry_time`
- ✅ Валидация всех границ перед доступом к DataFrame
- ✅ Обработка `if df.empty: return`

### Производительность
- ✅ Полностью асинхронная архитектура
- ✅ Векторизованные операции pandas
- ✅ Ограничение параллельных запросов
- ✅ Графики в отдельном thread pool

### Уведомления
- ✅ Гарантированная доставка с retry
- ✅ Графики с аннотациями
- ✅ Тредирование результатов
- ✅ Статистика изображением

## 📊 Паттерн «Стекающиеся консолидации»

Паттерн состоит из двух консолидаций:
1. Первая зона накопления (амплитуда 0.5-3%)
2. Вторая зона выше/ниже первой (gap ≤ 0.3%)
3. Вход на пробой второй консолидации
4. TP/SL с соотношением риск/прибыль 2:1

**LONG:**
- Entry: пробой highs второй консолидации
- SL: ниже lows первой консолидации
- TP: entry + (entry - SL) * 2

**SHORT:**
- Entry: пробой lows второй консолидации
- SL: выше highs первой консолидации
- TP: entry - (SL - entry) * 2

## ⚠️ Важные замечания

1. **Не используйте Streamlit** — бот работает в headless режиме
2. **Не сохраняйте индексы DataFrame** — используйте timestamp
3. **Всегда проверяйте границы** перед `iloc`
4. **Графики могут не генерироваться** — бот отправит текст с пометкой
5. **Telegram токен обязателен** для работы уведомлений

## 📝 Логирование

Логи пишутся в:
- Консоль (stdout)
- Файл `bot.log` (UTF-8 кодировка)

Уровень логирования настраивается в `.env`:
```env
LOG_LEVEL=INFO  # DEBUG, INFO, WARNING, ERROR
```

## 🛑 Graceful Shutdown

Бот корректно завершает работу по сигналам:
- Ctrl+C (SIGINT)
- SIGTERM

Все активные соединения закрываются, данные сохраняются.

## 📈 Мониторинг

Статистика отправляется автоматически при изменении количества закрытых сигналов:
- Всего сигналов
- Wins / Losses
- Win Rate %
- Average PnL %

## 🔐 Безопасность

- API ключи хранятся только в `.env`
- `.env` добавлен в `.gitignore`
- Нет хардкода чувствительных данных

## 📄 Лицензия

MIT License
