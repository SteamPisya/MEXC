# 🚀 Crypto Trading Scanner - Stacked Consolidations Detector

A professional Streamlit-based desktop application for detecting "Stacked Consolidations" (Bullish Staircase) patterns on MEXC Futures exchange.

## 📋 Features

- **Optimized Data Loading**: Fetches only missing candles from MEXC, stores in SQLite database
- **Pattern Detection**: Finds consolidation zones and links them into staircase patterns
- **Signal Tracking**: Stores signals in database with status tracking (Pending/Win/Lose)
- **Winrate System**: Automatically checks signal outcomes based on price movement
- **Telegram Notifications**: Sends signal alerts and winrate updates to Telegram
- **Interactive Charts**: Plotly candlestick charts with pattern visualization
- **Real-time UI**: Streamlit interface with controls, stats, and logs

## 🛠️ Installation

### Prerequisites
- Python 3.8+
- pip package manager

### Install Dependencies

```bash
pip install streamlit pandas ccxt plotly requests kaleido
```

### Configure Telegram (Optional)

Edit `crypto_scanner.py` and replace these values at the top of the file:

```python
TG_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
TG_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID_HERE"
```

To get your bot token:
1. Message @BotFather on Telegram
2. Send `/newbot` and follow instructions
3. Copy the API token

To get your chat ID:
1. Message @userinfobot on Telegram
2. It will reply with your user ID

## 🚀 Running the Application

```bash
streamlit run crypto_scanner.py
```

The app will open in your browser at `http://localhost:8501`

## 📖 How to Use

### 1. Load Trading Pairs
- Click **"🔄 Загрузить пары MEXC"** to fetch available futures pairs
- Select pairs from the multiselect dropdown

### 2. Configure Settings
- **Timeframe**: Choose between 15m, 1h, or 1d
- **Block Parameters**:
  - Y-gap %: Minimum vertical gap between blocks (default 1.0%)
  - Max candles between blocks: Maximum horizontal gap (default 20)
  - Amplitude Min/Max %: Consolidation zone volatility range
  - Min candles in block: Minimum duration of consolidation
  - Max candles after pattern: Pattern validity window
- **Winrate Settings**:
  - Drop >= N% for Win: Price drop threshold for winning signal
  - Rise >= N% for Lose: Price rise threshold for losing signal

### 3. Start Scanning
- Click **"▶️ Начать анализ"** to begin scanning selected pairs
- Monitor progress in the logs section
- Click **"⏹️ Остановить"** to stop scanning

### 4. View Signals
- Active signals appear in the right column
- Click a signal to view its chart in the center column
- Chart shows all consolidation zones and detected pattern

### 5. Telegram Notifications
- Toggle **"📱 Уведомления Telegram"** to enable/disable
- New signals are sent as photos with chart attached
- Winrate updates reply to original signal message

## 🗄️ Database Structure

The app creates `trading_scanner.db` with two tables:

### candles
Stores historical OHLCV data to avoid re-downloading:
- symbol, timeframe, timestamp (composite primary key)
- open, high, low, close, volume

### signals
Tracks detected patterns and their outcomes:
- id, timestamp_sent, symbol, timeframe, price
- type (Пробой/Breakout or вЗоне/In Zone)
- blocks (number of consolidation blocks)
- status (Pending, Win, Lose)
- notified_winrate, msg_id (for Telegram threading)

## 🔍 Pattern Detection Logic

### Consolidation Zones
- Amplitude (High-Low)/Low must be between min_amp and max_amp percent
- Duration must be >= min_len candles
- Look-ahead up to 80 candles to expand the zone

### Stacked Patterns (Bullish Staircase)
- Links consolidation zones vertically
- Each next block must start AFTER previous ends
- Y-gap: (next.low - prev.high) / prev.high * 100 >= y_gap
- X-gap: next.start - prev.end <= x_gap candles
- Each block must be HIGHER than previous (bullish structure)

### Pattern Validation
- **Пробой (Breakout)**: Price > last_block.high * 1.01
- **вЗоне (In Zone)**: Price >= support level (last_block.low * 0.99)
- **УСТАРЕЛ (Stale)**: Too many candles since pattern end
- **СЛОМАН (Broken)**: Price broke below support

## 📊 Winrate System

For Pending signals:
- Fetches last 200 candles
- Calculates drop/rise percentages from signal price
- **Win**: Price dropped >= drop_pct% (default 20%)
- **Lose**: Price rose >= rise_pct% (default 33%)
- Anti-spam: Only notifies once per signal

## 🎨 UI Layout

### Column 1 (Controls & Stats)
- Bot control buttons
- Telegram toggle
- Pair selection
- Analysis settings
- Winrate settings
- Statistics dashboard

### Column 2 (Chart & Logs)
- Interactive Plotly chart
- Signal details
- Expandable logs section

### Column 3 (Signals List)
- Radio button list of pending signals
- Table view with all signal details

## ⚠️ Important Notes

1. **API Rate Limits**: MEXC has rate limits. Use appropriate delays between pairs.
2. **Data Quality**: Minimum 50 candles required for analysis.
3. **Telegram Optional**: App works without Telegram configuration.
4. **Database Persistence**: All data persists in `trading_scanner.db`.
5. **Stop Button**: Checks between pairs, not during API calls.

## 📝 Logging Format

Logs appear in format: `HH:MM:SS | Message`

Examples:
```
14:23:45 | Анализ: BTC/USDT:USDT (1/50)
14:23:46 | 📍 [300] BTC/USDT:USDT | Свечей в БД: 300
14:23:47 | ✅ 3 ступ. | Пробой
14:23:47 | 🚀 BTC/USDT:USDT: Сигнал создан | Тип: Пробой
```

## 🐛 Troubleshooting

**No patterns found:**
- Adjust amplitude settings (try wider range)
- Lower Y-gap percentage
- Increase max candles between blocks

**Telegram errors:**
- Verify token and chat ID are correct
- Check bot is not blocked
- Ensure chat ID is numeric

**Slow performance:**
- Reduce number of selected pairs
- Increase delay between pairs
- Use higher timeframe

## 📄 License

This project is provided as-is for educational purposes. Use at your own risk.

## 🙏 Credits

Built with:
- Streamlit
- CCXT (CryptoCurrency eXchange Trading Library)
- Plotly
- Pandas
- SQLite
