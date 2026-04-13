"""
🚀 Crypto Trading Scanner - Stacked Consolidations Detector
Detects "Stacked Consolidations" (Bullish Staircase) patterns on MEXC Futures
"""

import streamlit as st
import sqlite3
import pandas as pd
import ccxt
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import requests
from datetime import datetime
import time
import os
from io import BytesIO

# ============================================================================
# 🔐 TELEGRAM CONFIGURATION - REPLACE WITH YOUR VALUES
# ============================================================================
TG_TOKEN = "YOUR_TELEGRAM_BOT_TOKEN_HERE"
TG_CHAT_ID = "YOUR_TELEGRAM_CHAT_ID_HERE"

# ============================================================================
# 📊 GLOBAL CONSTANTS
# ============================================================================
TIMEFRAME_MS = {
    '15m': 900000,
    '1h': 3600000,
    '1d': 86400000
}

DB_PATH = "trading_scanner.db"

# ============================================================================
# 🗄️ DATABASE FUNCTIONS
# ============================================================================

def init_db():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create candles table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS candles (
            symbol TEXT,
            timeframe TEXT,
            timestamp INTEGER,
            open REAL,
            high REAL,
            low REAL,
            close REAL,
            volume REAL,
            PRIMARY KEY (symbol, timeframe, timestamp)
        )
    ''')
    
    # Create signals table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY,
            timestamp_sent TEXT,
            symbol TEXT,
            timeframe TEXT,
            price REAL,
            type TEXT,
            blocks INTEGER,
            status TEXT,
            notified_winrate INTEGER DEFAULT 0,
            msg_id INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

def get_candles_from_db(symbol, timeframe):
    """Get all candles from DB for a symbol/timeframe"""
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query(
        "SELECT * FROM candles WHERE symbol=? AND timeframe=? ORDER BY timestamp",
        conn,
        params=(symbol, timeframe)
    )
    conn.close()
    return df

def save_candles_to_db(df, symbol, timeframe):
    """Save candles to DB using INSERT OR IGNORE"""
    if df.empty:
        return
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    for _, row in df.iterrows():
        cursor.execute('''
            INSERT OR IGNORE INTO candles 
            (symbol, timeframe, timestamp, open, high, low, close, volume)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ''', (symbol, timeframe, int(row['timestamp']), row['open'], 
              row['high'], row['low'], row['close'], row['volume']))
    
    conn.commit()
    conn.close()

def get_signals_from_db(status=None):
    """Get signals from DB, optionally filtered by status"""
    conn = sqlite3.connect(DB_PATH)
    if status:
        df = pd.read_sql_query(
            "SELECT * FROM signals WHERE status=? ORDER BY timestamp_sent DESC",
            conn,
            params=(status,)
        )
    else:
        df = pd.read_sql_query("SELECT * FROM signals ORDER BY timestamp_sent DESC", conn)
    conn.close()
    return df

def update_signal_status(signal_id, status, notified_winrate=None):
    """Update signal status in DB"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    if notified_winrate is not None:
        cursor.execute('''
            UPDATE signals SET status=?, notified_winrate=? WHERE id=?
        ''', (status, notified_winrate, signal_id))
    else:
        cursor.execute('''
            UPDATE signals SET status=? WHERE id=?
        ''', (status, signal_id))
    conn.commit()
    conn.close()

def create_signal(symbol, timeframe, price, sig_type, blocks, msg_id=None):
    """Create a new signal in DB"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    timestamp_sent = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute('''
        INSERT INTO signals (timestamp_sent, symbol, timeframe, price, type, blocks, status, msg_id)
        VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)
    ''', (timestamp_sent, symbol, timeframe, price, sig_type, blocks, msg_id))
    signal_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return signal_id

def check_existing_signal(symbol, timeframe):
    """Check if there's an existing pending signal for this pair"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT id, status, price, blocks, type, msg_id FROM signals 
        WHERE symbol=? AND timeframe=? AND status='Pending'
        ORDER BY timestamp_sent DESC LIMIT 1
    ''', (symbol, timeframe))
    result = cursor.fetchone()
    conn.close()
    return result

# ============================================================================
# ⚡ OPTIMIZED DATA LOADING
# ============================================================================

def fetch_and_store_candles(symbol, timeframe, limit=300, log_func=None):
    """
    Fetch candles from MEXC with optimization to avoid re-downloading
    """
    exchange = ccxt.mexc()
    exchange.set_sandbox_mode(False)
    
    # Check existing candles in DB
    existing_df = get_candles_from_db(symbol, timeframe)
    
    if existing_df.empty:
        # First time download
        if log_func:
            log_func(f"📥 Первая загрузка: {symbol}")
        
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df['timestamp'] = df['timestamp'].astype(int)
        
        save_candles_to_db(df, symbol, timeframe)
        
        if log_func:
            log_func(f"📍 Загружено и сохранено: {len(df)} свечей")
        
        return df.sort_values('timestamp').reset_index(drop=True)
    else:
        # Calculate missing candles
        last_timestamp = existing_df['timestamp'].max()
        current_time = int(datetime.now().timestamp() * 1000)
        interval_ms = TIMEFRAME_MS.get(timeframe, 900000)
        
        # Estimate how many candles are missing
        candles_needed = int((current_time - last_timestamp) / interval_ms) + 5
        
        if candles_needed <= 0:
            if log_func:
                log_func(f"✅ {symbol}: Данные актуальны")
            return existing_df.sort_values('timestamp').reset_index(drop=True)
        
        if log_func:
            log_func(f"📥 {symbol}: Недостающих свечей ~{candles_needed}")
        
        # Fetch only missing candles + buffer
        bars = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=min(candles_needed + 5, limit))
        
        # Filter out already existing candles
        new_candles = []
        for bar in bars:
            if bar[0] > last_timestamp:
                new_candles.append(bar)
        
        if new_candles:
            new_df = pd.DataFrame(new_candles, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            new_df['timestamp'] = new_df['timestamp'].astype(int)
            save_candles_to_db(new_df, symbol, timeframe)
            
            if log_func:
                log_func(f"📍 {symbol}: Добавлено {len(new_candles)} новых свечей")
            
            # Combine with existing
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            return combined.sort_values('timestamp').reset_index(drop=True)
        else:
            if log_func:
                log_func(f"✅ {symbol}: Нет новых данных")
            return existing_df.sort_values('timestamp').reset_index(drop=True)

# ============================================================================
# 🔍 PATTERN DETECTION LOGIC
# ============================================================================

def find_consolidations(df, min_amp, max_amp, min_len):
    """
    Scan price data for consolidation zones (sideways movement)
    Returns list of dicts with consolidation info
    """
    consolidations = []
    n = len(df)
    cons_id = 0
    
    i = 0
    while i < n - min_len:
        # Look for a starting point where volatility is low
        window_start = i
        
        # Try to find end of consolidation within a limited window
        best_end = -1
        
        # Scan forward looking for consolidation zone
        for j in range(window_start + min_len - 1, min(window_start + 80, n)):
            segment = df.iloc[window_start:j+1]
            amp = (segment['high'].max() - segment['low'].min()) / segment['low'].min() * 100
            
            if amp > max_amp:
                # If we already found a valid consolidation, save it
                if best_end > window_start:
                    break
                # Otherwise, move start point forward
                window_start += 1
                break
            
            if amp >= min_amp and (j - window_start + 1) >= min_len:
                best_end = j
        
        if best_end > window_start:
            # Found valid consolidation
            final_segment = df.iloc[window_start:best_end+1]
            final_amp = (final_segment['high'].max() - final_segment['low'].min()) / final_segment['low'].min() * 100
            
            consolidations.append({
                'id': cons_id,
                'start': window_start,
                'end': best_end,
                'low': final_segment['low'].min(),
                'high': final_segment['high'].max(),
                't0': df.iloc[window_start]['timestamp'],
                't1': df.iloc[best_end]['timestamp'],
                'dur': best_end - window_start + 1,
                'amp': final_amp
            })
            cons_id += 1
            i = best_end + 1  # Move past this consolidation
        else:
            i += 1
    
    return consolidations

def find_stacked(consolidations, y_gap, x_gap):
    """
    Link consolidation zones into a "staircase" pattern
    Each next block must be HIGHER than previous (bullish structure)
    """
    if not consolidations:
        return []
    
    patterns = []
    n = len(consolidations)
    
    def find_sequences(start_idx, current_seq):
        sequences = []
        last_block = current_seq[-1] if current_seq else None
        
        for i in range(start_idx, n):
            curr = consolidations[i]
            
            if last_block:
                # Next block must start AFTER previous block ends
                if curr['start'] <= last_block['end']:
                    continue
                
                # Y-gap check: (next.low - prev.high) / prev.high * 100 >= y_gap
                y_gap_pct = (curr['low'] - last_block['high']) / last_block['high'] * 100
                if y_gap_pct < y_gap:
                    continue
                
                # X-gap check: next.start - prev.end <= x_gap candles
                x_gap_actual = curr['start'] - last_block['end']
                if x_gap_actual > x_gap:
                    continue
                
                # Each next block must be HIGHER (bullish structure)
                if curr['low'] <= last_block['low']:
                    continue
                
                # Valid continuation
                new_seq = current_seq + [curr]
                sub_sequences = find_sequences(i + 1, new_seq)
                sequences.extend(sub_sequences)
            else:
                # Start a new sequence
                new_seq = [curr]
                sub_sequences = find_sequences(i + 1, new_seq)
                sequences.extend(sub_sequences)
        
        if not sequences and current_seq:
            sequences.append(current_seq)
        
        return sequences
    
    # Find all possible sequences
    all_sequences = find_sequences(0, [])
    
    # Filter to keep only sequences with 2+ blocks
    valid_patterns = [seq for seq in all_sequences if len(seq) >= 2]
    
    # Sort by most recent (highest end index) first
    valid_patterns.sort(key=lambda p: p[-1]['end'], reverse=True)
    
    return valid_patterns

def validate_pattern(pattern, df, max_candles_after):
    """
    Check the last block in the pattern against current price
    Returns: "Пробой", "вЗоне", "УСТАРЕЛ", or "СЛОМАН"
    """
    if not pattern:
        return "СЛОМАН"
    
    last_block = pattern[-1]
    current_idx = len(df) - 1
    candles_passed = current_idx - last_block['end']
    
    if candles_passed > max_candles_after:
        return "УСТАРЕЛ"
    
    current_price = df.iloc[-1]['close']
    support_level = last_block['low'] * 0.99  # 1% buffer
    
    if current_price >= support_level:
        if current_price > last_block['high'] * 1.01:
            return "Пробой"
        else:
            return "вЗоне"
    else:
        return "СЛОМАН"

# ============================================================================
# 📊 WINRATE CHECKING SYSTEM
# ============================================================================

def check_winrates(pending_signals_df, drop_pct, rise_pct, log_func=None):
    """
    Check winrates for pending signals
    Win: price dropped >= drop_pct%
    Lose: price rose >= rise_pct%
    """
    updated = []
    exchange = ccxt.mexc()
    
    for _, signal in pending_signals_df.iterrows():
        symbol = signal['symbol']
        signal_price = signal['price']
        signal_id = signal['id']
        
        try:
            # Fetch last 200 candles
            bars = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=200)
            df = pd.DataFrame(bars, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
            
            current_price = df.iloc[-1]['close']
            current_min = df['low'].min()
            current_max = df['high'].max()
            
            # Calculate percentages from signal price
            drop = (signal_price - current_min) / signal_price * 100
            rise = (current_max - signal_price) / signal_price * 100
            
            new_status = None
            if drop >= drop_pct:
                new_status = "Win"
            elif rise >= rise_pct:
                new_status = "Lose"
            
            if new_status:
                update_signal_status(signal_id, new_status, notified_winrate=1)
                updated.append({
                    'id': signal_id,
                    'symbol': symbol,
                    'timeframe': signal['timeframe'],
                    'signal_price': signal_price,
                    'current_price': current_price,
                    'drop': drop,
                    'rise': rise,
                    'status': new_status,
                    'msg_id': signal['msg_id']
                })
                
                if log_func:
                    log_func(f"📊 {symbol}: {new_status} | Падение: {drop:.1f}% | Рост: {rise:.1f}%")
            else:
                if log_func:
                    log_func(f"⏳ {symbol}: Ожидание винрейта")
                    
        except Exception as e:
            if log_func:
                log_func(f"❌ {symbol}: Ошибка проверки винрейта - {str(e)}")
    
    return updated

# ============================================================================
# 📱 TELEGRAM INTEGRATION
# ============================================================================

def send_tg(text, photo=None, reply_to=None, chat_id=TG_CHAT_ID, token=TG_TOKEN):
    """
    Send Telegram message
    Returns message_id for tracking
    """
    if TG_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN_HERE":
        return None
    
    url = f"https://api.telegram.org/bot{token}/"
    
    try:
        if photo:
            # Send as photo with caption
            files = {'photo': photo}
            data = {
                'chat_id': chat_id,
                'caption': text,
                'parse_mode': 'Markdown'
            }
            if reply_to:
                data['reply_to_message_id'] = reply_to
            
            response = requests.post(f"{url}sendPhoto", data=data, files=files)
        else:
            # Send text message
            data = {
                'chat_id': chat_id,
                'text': text,
                'parse_mode': 'Markdown'
            }
            if reply_to:
                data['reply_to_message_id'] = reply_to
            
            response = requests.post(f"{url}sendMessage", json=data)
        
        if response.status_code == 200:
            result = response.json().get('result', {})
            return result.get('message_id')
        else:
            print(f"Telegram API error: {response.text}")
            return None
            
    except Exception as e:
        print(f"Telegram send error: {str(e)}")
        return None

# ============================================================================
# 📈 CHART GENERATION (Plotly)
# ============================================================================

def generate_chart(df, pattern, consolidations, symbol, timeframe):
    """
    Create candlestick chart with full historical context
    Returns Plotly figure and PNG bytes
    """
    # Create subplot
    fig = make_subplots(rows=1, cols=1, shared_xaxes=True)
    
    # Add candlestick chart
    fig.add_trace(go.Candlestick(
        x=list(range(len(df))),
        open=df['open'],
        high=df['high'],
        low=df['low'],
        close=df['close'],
        name='Price',
        increasing_line_color='#00ff00',
        decreasing_line_color='#ff0000'
    ))
    
    # Add all consolidation zones (gray, dashed, opacity 0.04)
    for cons in consolidations:
        fig.add_shape(
            type="rect",
            x0=cons['start'],
            x1=cons['end'],
            y0=cons['low'],
            y1=cons['high'],
            fillcolor="gray",
            opacity=0.04,
            line=dict(color="gray", width=1, dash="dash"),
            layer='below'
        )
    
    # Add pattern blocks (blue/cyan, solid border, opacity 0.3)
    if pattern:
        for i, block in enumerate(pattern):
            fig.add_shape(
                type="rect",
                x0=block['start'],
                x1=block['end'],
                y0=block['low'],
                y1=block['high'],
                fillcolor="cyan",
                opacity=0.3,
                line=dict(color="blue", width=2),
                layer='below'
            )
            
            # Annotation on block: amplitude + duration
            fig.add_annotation(
                x=(block['start'] + block['end']) / 2,
                y=block['high'],
                text=f"📦 {block['amp']:.1f}%<br>{block['dur']} св.",
                showarrow=False,
                font=dict(size=9, color="white"),
                bgcolor="rgba(0,0,0,0.7)",
                borderpad=2
            )
        
        # Connection lines between blocks (yellow, dashed)
        for i in range(len(pattern) - 1):
            curr = pattern[i]
            next_b = pattern[i + 1]
            
            y_gap_pct = (next_b['low'] - curr['high']) / curr['high'] * 100
            x_gap_candles = next_b['start'] - curr['end']
            
            fig.add_shape(
                type="line",
                x0=curr['end'],
                y0=curr['high'],
                x1=next_b['start'],
                y1=next_b['low'],
                line=dict(color="yellow", width=2, dash="dash"),
                layer='above'
            )
            
            # Annotation on connection
            mid_x = (curr['end'] + next_b['start']) / 2
            mid_y = (curr['high'] + next_b['low']) / 2
            fig.add_annotation(
                x=mid_x,
                y=mid_y,
                text=f"⬆️ +{y_gap_pct:.1f}%<br>{x_gap_candles} св.",
                showarrow=False,
                font=dict(size=8, color="yellow"),
                bgcolor="rgba(0,0,0,0.7)",
                borderpad=1
            )
    
    # Update layout
    current_price = df.iloc[-1]['close']
    blocks_count = len(pattern) if pattern else 0
    
    fig.update_layout(
        title=f"{symbol} ({timeframe}) | {blocks_count} БЛОКОВ | 💰 {current_price:.6f}",
        yaxis_title="Price",
        xaxis_title="Candle Index",
        template="plotly_dark",
        height=550,
        showlegend=False,
        xaxis=dict(rangeslider_visible=False),
        margin=dict(l=50, r=50, t=70, b=50)
    )
    
    # Generate PNG for Telegram
    png_bytes = None
    try:
        png_buffer = BytesIO()
        fig.write_image(png_buffer, format='png', width=1100, height=550, scale=2)
        png_buffer.seek(0)
        png_bytes = png_buffer.getvalue()
    except Exception as e:
        print(f"Error generating PNG: {str(e)}")
    
    return fig, png_bytes

# ============================================================================
# 🖥️ USER INTERFACE (Streamlit)
# ============================================================================

@st.cache_resource
def get_logger():
    """Cached logger function"""
    return []

def add_log(message):
    """Add a log entry"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    log_entry = f"{timestamp} | {message}"
    
    if 'logs' not in st.session_state:
        st.session_state.logs = []
    
    st.session_state.logs.append(log_entry)
    # Keep only last 50 entries
    st.session_state.logs = st.session_state.logs[-50:]

def main():
    st.set_page_config(
        page_title="🚀 Crypto Scanner",
        page_icon="🚀",
        layout="wide"
    )
    
    # Initialize session state
    if 'running' not in st.session_state:
        st.session_state.running = False
    if 'selected_sig' not in st.session_state:
        st.session_state.selected_sig = None
    if 'pairs_list' not in st.session_state:
        st.session_state.pairs_list = []
    if 'tg_enabled' not in st.session_state:
        st.session_state.tg_enabled = False
    if 'logs' not in st.session_state:
        st.session_state.logs = []
    
    # Initialize database
    init_db()
    
    # Custom CSS
    st.markdown("""
        <style>
        .stMetric {background-color: #1e1e1e; padding: 10px; border-radius: 5px;}
        </style>
    """, unsafe_allow_html=True)
    
    # Header
    st.title("🚀 Crypto Trading Scanner")
    st.subheader("Stacked Consolidations (Bullish Staircase) Detector")
    
    # Main layout: 3 columns
    col1, col2, col3 = st.columns([1, 3, 1])
    
    # ========================================================================
    # COLUMN 1: Controls & Stats
    # ========================================================================
    with col1:
        st.header("🎮 Управление")
        
        # Bot Control
        if not st.session_state.running:
            if st.button("▶️ Начать анализ", use_container_width=True, type="primary"):
                st.session_state.running = True
                st.rerun()
        else:
            if st.button("⏹️ Остановить", use_container_width=True):
                st.session_state.running = False
                st.success("Анализ остановлен")
                st.rerun()
        
        # Telegram toggle
        tg_enabled = st.toggle("📱 Уведомления Telegram", value=st.session_state.tg_enabled)
        st.session_state.tg_enabled = tg_enabled
        
        st.divider()
        
        # Pair Selection
        st.header("📊 Пары")
        
        if st.button("🔄 Загрузить пары MEXC", use_container_width=True):
            try:
                exchange = ccxt.mexc()
                markets = exchange.load_markets()
                futures_pairs = [
                    sym for sym in markets.keys() 
                    if 'USDT' in sym and markets[sym].get('type') == 'future'
                ]
                st.session_state.pairs_list = sorted(futures_pairs)
                st.success(f"Загружено {len(futures_pairs)} пар")
            except Exception as e:
                st.error(f"Ошибка загрузки пар: {str(e)}")
        
        if st.session_state.pairs_list:
            selected_pairs = st.multiselect(
                "Выберите пары",
                st.session_state.pairs_list,
                default=st.session_state.pairs_list[:10] if len(st.session_state.pairs_list) >= 10 else st.session_state.pairs_list
            )
        else:
            selected_pairs = []
            st.warning("Нажмите 'Загрузить пары'")
        
        st.divider()
        
        # Analysis Settings
        st.header("⚙️ Настройки анализа")
        
        timeframe = st.selectbox("Таймфрейм", ['15m', '1h', '1d'])
        
        st.subheader("Параметры блоков")
        y_gap = st.number_input("Y-gap %", min_value=0.1, max_value=50.0, value=1.0, step=0.1)
        x_gap = st.number_input("Макс. свечей между блоками", min_value=1, max_value=100, value=20)
        amp_min = st.number_input("Амплитуда Min %", min_value=0.1, max_value=50.0, value=2.0, step=0.1)
        amp_max = st.number_input("Амплитуда Max %", min_value=1.0, max_value=100.0, value=15.0, step=0.1)
        min_len = st.number_input("Мин. свечей в блоке", min_value=1, max_value=50, value=3)
        max_after = st.number_input("Макс. свечей после паттерна", min_value=1, max_value=100, value=20)
        delay = st.number_input("Задержка между парами (сек)", min_value=0, max_value=60, value=2)
        
        st.divider()
        
        # Winrate Settings
        st.header("📊 Настройки винрейта")
        drop_threshold = st.number_input("Падение >= % для Win", min_value=1.0, max_value=100.0, value=20.0, step=0.1)
        rise_threshold = st.number_input("Рост >= % для Lose", min_value=1.0, max_value=100.0, value=33.0, step=0.1)
        
        if st.button("📤 Отправить статистику в TG", use_container_width=True):
            stats_df = get_signals_from_db()
            total = len(stats_df)
            wins = len(stats_df[stats_df['status'] == 'Win']) if not stats_df.empty else 0
            losses = len(stats_df[stats_df['status'] == 'Lose']) if not stats_df.empty else 0
            pending = len(stats_df[stats_df['status'] == 'Pending']) if not stats_df.empty else 0
            
            winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0
            
            stats_text = f"""
📊 *Статистика Сканера*

📈 Всего сигналов: {total}
✅ Wins: {wins}
❌ Losses: {losses}
⏳ Pending: {pending}

🎯 Winrate: {winrate:.1f}%
            """
            
            if st.session_state.tg_enabled:
                msg_id = send_tg(stats_text)
                if msg_id:
                    st.success("Статистика отправлена в Telegram")
                else:
                    st.error("Ошибка отправки в Telegram")
            else:
                st.info("Включите уведомления Telegram")
                st.code(stats_text)
        
        st.divider()
        
        # Stats Dashboard
        st.header("📈 Статистика")
        
        signals_df = get_signals_from_db()
        total_signals = len(signals_df)
        pending_count = len(signals_df[signals_df['status'] == 'Pending']) if not signals_df.empty else 0
        wins_count = len(signals_df[signals_df['status'] == 'Win']) if not signals_df.empty else 0
        losses_count = len(signals_df[signals_df['status'] == 'Lose']) if not signals_df.empty else 0
        
        c1, c2 = st.columns(2)
        c1.metric("Всего", total_signals)
        c2.metric("⏳ Pending", pending_count)
        
        c3, c4 = st.columns(2)
        c3.metric("✅ Wins", wins_count)
        c4.metric("❌ Losses", losses_count)
        
        if wins_count + losses_count > 0:
            winrate_pct = wins_count / (wins_count + losses_count) * 100
            st.metric("🎯 Winrate", f"{winrate_pct:.1f}%")
    
    # ========================================================================
    # COLUMN 2: Chart & Logs
    # ========================================================================
    with col2:
        st.header("📈 График")
        
        if st.session_state.selected_sig:
            sig = st.session_state.selected_sig
            
            # Get candles for chart
            try:
                candles_df = get_candles_from_db(sig['symbol'], sig['timeframe'])
                
                if not candles_df.empty:
                    # Find consolidations for display
                    cons = find_consolidations(candles_df, amp_min, amp_max, min_len)
                    
                    # Rebuild pattern from signal data
                    # For simplicity, we'll just show the consolidations
                    pattern = cons[-sig['blocks']:] if len(cons) >= sig['blocks'] else cons
                    
                    fig, _ = generate_chart(
                        candles_df, 
                        pattern, 
                        cons, 
                        sig['symbol'], 
                        sig['timeframe']
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                    
                    # Signal info
                    st.info(f"""
                    **Сигнал:** {sig['symbol']} | {sig['timeframe']}  
                    **Тип:** {sig['type']} | **Блоков:** {sig['blocks']}  
                    **Цена:** {sig['price']:.6f} | **Статус:** {sig['status']}
                    """)
                else:
                    st.warning("Нет данных свечей для отображения")
                    
            except Exception as e:
                st.error(f"Ошибка построения графика: {str(e)}")
        else:
            st.info("👈 Выберите сигнал справа")
            # Show placeholder chart
            fig = go.Figure()
            fig.add_annotation(
                text="Выберите сигнал из списка справа<br>для отображения графика",
                xref="paper", yref="paper",
                x=0.5, y=0.5,
                showarrow=False,
                font=dict(size=16)
            )
            fig.update_layout(
                template="plotly_dark",
                height=550,
                xaxis=dict(visible=False),
                yaxis=dict(visible=False)
            )
            st.plotly_chart(fig, use_container_width=True)
        
        # Expandable Logs Section
        st.divider()
        with st.expander("📜 Выпадающий блок (Логи)", expanded=False):
            if st.session_state.logs:
                logs_text = "\n".join(st.session_state.logs[-50:])
                st.code(logs_text)
            else:
                st.info("Логи появятся во время анализа")
            
            st.caption(f"Всего логов: {len(st.session_state.logs)}")
    
    # ========================================================================
    # COLUMN 3: Signals List
    # ========================================================================
    with col3:
        st.header("🔔 Активные сигналы")
        
        pending_df = get_signals_from_db(status='Pending')
        
        if not pending_df.empty:
            # Radio button list
            options = []
            for _, row in pending_df.iterrows():
                opt = f"{row['symbol']} | {row['blocks']} Бл. | {row['type']}"
                options.append(opt)
            
            selected_option = st.radio(
                "Выберите сигнал",
                options,
                index=None
            )
            
            if selected_option:
                # Find corresponding signal
                idx = options.index(selected_option)
                sig_row = pending_df.iloc[idx]
                st.session_state.selected_sig = sig_row.to_dict()
            
            st.divider()
            
            # Table view
            display_df = pending_df[['timestamp_sent', 'symbol', 'price', 'blocks', 'type', 'status']].copy()
            display_df.columns = ['Время', 'Пара', 'Цена', 'Блоки', 'Тип', 'Статус']
            st.dataframe(display_df, hide_index=True, use_container_width=True)
        else:
            st.success("✅ Нет активных сигналов. Бот чист!")
            st.session_state.selected_sig = None
    
    # ========================================================================
    # MAIN EXECUTION LOOP
    # ========================================================================
    if st.session_state.running and selected_pairs:
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        total_pairs = len(selected_pairs)
        
        for i, pair in enumerate(selected_pairs):
            if not st.session_state.running:
                break
            
            status_text.text(f"Анализ: {pair} ({i+1}/{total_pairs})")
            add_log(f"Анализ: {pair} ({i+1}/{total_pairs})")
            
            try:
                # Fetch/store candles (optimized)
                candles_df = fetch_and_store_candles(pair, timeframe, limit=300, log_func=add_log)
                
                if len(candles_df) < 50:
                    add_log(f"⚠️ {pair}: Недостаточно данных ({len(candles_df)} свечей)")
                    continue
                
                add_log(f"📍 [{len(candles_df)}] {pair} | Свечей в БД: {len(candles_df)}")
                
                # Find consolidations
                consolidations = find_consolidations(candles_df, amp_min, amp_max, min_len)
                
                if not consolidations:
                    add_log(f"⚪ {pair}: Нет консолидаций")
                    continue
                
                # Find stacked patterns
                patterns = find_stacked(consolidations, y_gap, x_gap)
                
                if not patterns:
                    add_log(f"⚪ {pair}: Нет ступенчатых паттернов")
                    continue
                
                # Process each pattern (take best one)
                for pattern in patterns[:1]:  # Process top pattern
                    # Validate pattern
                    validation = validate_pattern(pattern, candles_df, max_after)
                    
                    if validation in ["УСТАРЕЛ", "СЛОМАН"]:
                        add_log(f"❌ {pair}: {validation}")
                        continue
                    
                    blocks_count = len(pattern)
                    last_block = pattern[-1]
                    current_price = candles_df.iloc[-1]['close']
                    candles_passed = (len(candles_df) - 1) - last_block['end']
                    
                    add_log(f"✅ {blocks_count} ступ. | {validation}")
                    
                    # Check DB for existing signal
                    existing = check_existing_signal(pair, timeframe)
                    
                    if existing:
                        ex_id, ex_status, ex_price, ex_blocks, ex_type, ex_msg_id = existing
                        
                        if ex_status in ["Win", "Lose"]:
                            add_log(f"⏭️ {pair}: Уже есть решенный сигнал")
                            continue
                        elif ex_status == "Pending":
                            # Check winrate instead of creating duplicate
                            add_log(f"⏳ {pair}: Ожидание винрейта")
                            
                            # Quick winrate check
                            pending_check = pd.DataFrame([{
                                'id': ex_id,
                                'symbol': pair,
                                'timeframe': timeframe,
                                'price': ex_price,
                                'msg_id': ex_msg_id
                            }])
                            
                            updated = check_winrates(pending_check, drop_threshold, rise_threshold, add_log)
                            
                            if updated and st.session_state.tg_enabled:
                                for upd in updated:
                                    winrate_text = f"""
📊 *Винрейт обновлен*
🔹 {upd['symbol']} ({timeframe})
💰 Цена сигнала: {upd['signal_price']:.6f}
📉 Текущая: {upd['current_price']:.6f}
🏁 Результат: {upd['status']}
⬇️ Падение: {upd['drop']:.1f}% | ⬆️ Рост: {upd['rise']:.1f}%
                                    """
                                    send_tg(winrate_text, reply_to=ex_msg_id)
                            continue
                    
                    # Create new signal
                    signal_id = create_signal(
                        pair, timeframe, current_price, 
                        validation, blocks_count
                    )
                    
                    add_log(f"🚀 {pair}: Сигнал создан | Тип: {validation}")
                    
                    # Send Telegram notification
                    if st.session_state.tg_enabled:
                        # Generate chart
                        _, png_bytes = generate_chart(
                            candles_df, pattern, consolidations, pair, timeframe
                        )
                        
                        signal_text = f"""
🚀 *Новый Сигнал*
🔹 {pair} ({timeframe})
💰 Цена: {current_price:.6f}
📦 Блоков: {blocks_count}
📈 Тип: {validation}
⏳ После: {candles_passed} св.
                        """
                        
                        if png_bytes:
                            msg_id = send_tg(signal_text, photo=('chart.png', png_bytes))
                        else:
                            msg_id = send_tg(signal_text)
                        
                        if msg_id:
                            # Update signal with msg_id
                            conn = sqlite3.connect(DB_PATH)
                            cursor = conn.cursor()
                            cursor.execute('UPDATE signals SET msg_id=? WHERE id=?', (msg_id, signal_id))
                            conn.commit()
                            conn.close()
                
            except Exception as e:
                add_log(f"❌ {pair}: Ошибка - {str(e)}")
                print(f"Error processing {pair}: {str(e)}")
            
            # Progress bar
            progress_bar.progress((i + 1) / total_pairs)
            
            # Delay
            if delay > 0 and i < total_pairs - 1:
                time.sleep(delay)
        
        st.session_state.running = False
        progress_bar.empty()
        status_text.empty()
        st.success("✅ Анализ завершен")
        st.rerun()
    
    elif st.session_state.running and not selected_pairs:
        st.warning("⚠️ Выберите пары для анализа")
        st.session_state.running = False

if __name__ == "__main__":
    main()
