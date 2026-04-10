"""
Приложение для анализа криптовалютных паттернов на бирже MEXC Futures.
Паттерн "Бычья Лестница" (Bullish Staircase).

Автор: Senior Python Developer & UX/UI Designer
Стек: Streamlit, Plotly, CCXT, Pandas, Numpy
"""

import streamlit as st
import ccxt
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import logging
from datetime import datetime
import io

# ============================================================================
# НАСТРОЙКА ЛОГИРОВАНИЯ
# ============================================================================

# Создаем кастомный обработчик для вывода логов в Streamlit
class StreamlitLogHandler(logging.Handler):
    def __init__(self, log_container):
        super().__init__()
        self.log_container = log_container
    
    def emit(self, record):
        msg = self.format(record)
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_container.markdown(f"`[{timestamp}] {msg}`")

def setup_logging(log_container):
    """Настройка системы логирования с выводом в интерфейс Streamlit."""
    logger = logging.getLogger("MEXC_Analyzer")
    logger.setLevel(logging.INFO)
    
    # Очищаем предыдущие обработчики
    logger.handlers.clear()
    
    # Добавляем наш кастомный обработчик
    handler = StreamlitLogHandler(log_container)
    formatter = logging.Formatter("%(message)s")
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    return logger

# ============================================================================
# ФУНКЦИИ ПОЛУЧЕНИЯ ДАННЫХ (CCXT + MEXC)
# ============================================================================

def fetch_mexc_data(symbol: str, timeframe: str = '15m', limit: int = 200) -> pd.DataFrame:
    """
    Скачивает данные свечей с биржи MEXC Futures.
    
    Параметры:
    - symbol: Торговая пара (например, 'BTC/USDT')
    - timeframe: Таймфрейм (по умолчанию 15m)
    - limit: Количество свечей (по умолчанию 200)
    
    Возвращает:
    - DataFrame с колонками: timestamp, open, high, low, close, volume
    """
    # Инициализация_exchange с настройкой для фьючерсов (swap)
    exchange = ccxt.mexc({
        'options': {
            'defaultType': 'swap'  # Используем фьючерсный рынок
        }
    })
    
    try:
        # Загрузка OHLCV данных
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        
        # Преобразование в DataFrame
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Конвертация таймстемпа в читаемый формат
        df['datetime'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        return df
    
    except Exception as e:
        raise Exception(f"Ошибка получения данных: {str(e)}")

# ============================================================================
# ИНДИКАТОРЫ
# ============================================================================

def calculate_supertrend(df: pd.DataFrame, atr_period: int = 10, multiplier: float = 3.0) -> pd.DataFrame:
    """
    Рассчитывает индикатор SuperTrend.
    
    Логика:
    1. HL2 = (High + Low) / 2 - средняя цена свечи
    2. ATR = Average True Range - волатильность
    3. Upper Band = HL2 + (multiplier * ATR)
    4. Lower Band = HL2 - (multiplier * ATR)
    5. Trend определяется по тому, какая граница активна
    
    Параметры:
    - df: DataFrame с OHLCV данными
    - atr_period: Период для расчета ATR (по умолчанию 10)
    - multiplier: Множитель для ATR (по умолчанию 3.0)
    
    Возвращает:
    - DataFrame с добавленными колонками: hl2, atr, upper_band, lower_band, supertrend, trend
    """
    df = df.copy()
    
    # Расчет HL2 (средняя цена)
    df['hl2'] = (df['high'] + df['low']) / 2
    
    # Расчет True Range (TR)
    df['tr1'] = df['high'] - df['low']
    df['tr2'] = abs(df['high'] - df['close'].shift(1))
    df['tr3'] = abs(df['low'] - df['close'].shift(1))
    df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
    
    # Расчет ATR (Average True Range)
    df['atr'] = df['tr'].rolling(window=atr_period).mean()
    
    # Расчет верхней и нижней границ
    df['upper_band'] = df['hl2'] + (multiplier * df['atr'])
    df['lower_band'] = df['hl2'] - (multiplier * df['atr'])
    
    # Инициализация колонок SuperTrend
    df['supertrend'] = 0.0
    df['trend'] = 1  # 1 = Green/Buy, -1 = Red/Sell
    
    # Проход по данным для расчета SuperTrend
    # SuperTrend переключается только когда цена пробивает противоположную границу
    for i in range(1, len(df)):
        if df['trend'].iloc[i-1] == 1:
            # Если предыдущий тренд восходящий (зеленый)
            if df['close'].iloc[i] < df['lower_band'].iloc[i]:
                # Цена упала ниже нижней границы - разворот вниз
                df.loc[df.index[i], 'trend'] = -1
                df.loc[df.index[i], 'supertrend'] = df['upper_band'].iloc[i]
            else:
                # Тренд продолжается вверх
                df.loc[df.index[i], 'trend'] = 1
                # SuperTrend следует за нижней границей, но не уменьшается
                df.loc[df.index[i], 'supertrend'] = max(df['lower_band'].iloc[i], 
                                                         df['supertrend'].iloc[i-1])
        else:
            # Если предыдущий тренд нисходящий (красный)
            if df['close'].iloc[i] > df['upper_band'].iloc[i]:
                # Цена выросла выше верхней границы - разворот вверх
                df.loc[df.index[i], 'trend'] = 1
                df.loc[df.index[i], 'supertrend'] = df['lower_band'].iloc[i]
            else:
                # Тренд продолжается вниз
                df.loc[df.index[i], 'trend'] = -1
                # SuperTrend следует за верхней границей, но не увеличивается
                df.loc[df.index[i], 'supertrend'] = min(df['upper_band'].iloc[i], 
                                                         df['supertrend'].iloc[i-1])
    
    # Для первой свечи устанавливаем начальное значение
    df.loc[df.index[0], 'supertrend'] = df['lower_band'].iloc[0]
    df.loc[df.index[0], 'trend'] = 1
    
    return df

def calculate_roc(df: pd.DataFrame, period: int = 3) -> pd.DataFrame:
    """
    Рассчитывает индикатор ROC (Rate of Change).
    
    Формула: ((Close - Close[period]) / Close[period]) * 100
    
    Параметры:
    - df: DataFrame с ценовыми данными
    - period: Период для расчета (по умолчанию 3)
    
    Возвращает:
    - DataFrame с добавленной колонкой 'roc'
    """
    df = df.copy()
    
    # Расчет ROC
    df['roc'] = ((df['close'] - df['close'].shift(period)) / df['close'].shift(period)) * 100
    
    return df

# ============================================================================
# АЛГОРИТМ ПОИСКА ПАТТЕРНА "БЫЧЬЯ ЛЕСТНИЦА"
# ============================================================================

def scan_bullish_staircase(df: pd.DataFrame, 
                           roc_threshold: float = 5.0,
                           max_retrace_pct: float = 50.0,
                           max_consol_candles: int = 50,
                           logger=None) -> dict:
    """
    Алгоритм поиска паттерна "Бычья Лестница" (Bullish Staircase).
    
    Логика работы (слева направо):
    1. Поиск Импульса (Impulse): Рост цены на заданный % за 1-5 свечей
    2. Поиск Консолидации (Consolidation): Зона отдыха до 50 свечей
       - Главное правило: Low не должен опускаться ниже 50% от размера импульса
    3. Поиск Следующей Ступени (Breakout): Новый High выше предыдущего
    4. Подсчет ступеней: Если Steps >= 2, паттерн валиден
    
    Параметры:
    - df: DataFrame с данными (должен содержать OHLCV + ROC)
    - roc_threshold: Минимальный % роста для импульса (по умолчанию 5%)
    - max_retrace_pct: Максимальный % отката от вершины импульса (по умолчанию 50%)
    - max_consol_candles: Максимальная длительность консолидации (по умолчанию 50)
    - logger: Объект логгера для вывода сообщений
    
    Возвращает:
    - dict с результатами анализа:
      - impulses: список найденных импульсов
      - consolidations: список зон консолидации
      - steps_count: общее количество ступеней
      - pattern_found: булево значение (найден ли паттерн)
      - markers: данные для визуализации маркеров на графике
      - shapes: данные для визуализации зон (прямоугольники)
    """
    
    result = {
        'impulses': [],
        'consolidations': [],
        'steps_count': 0,
        'pattern_found': False,
        'markers': {'x': [], 'y': [], 'text': [], 'color': []},
        'shapes': []
    }
    
    if logger:
        logger.info("🔍 Начало сканирования паттерна 'Бычья Лестница'...")
    
    n = len(df)
    i = 0
    current_step = 0
    last_impulse_high = None
    last_impulse_size = None
    consolidation_start = None
    min_allowed_price = None
    
    while i < n - 1:
        # ================================================================
        # ШАГ 1: ПОИСК ИМПУЛЬСА (IMPULSE)
        # ================================================================
        # Проверяем рост цены за 1-5 свечей
        impulse_found = False
        
        for lookback in range(1, 6):  # 1 to 5 candles
            if i + lookback >= n:
                break
            
            open_start = df.iloc[i]['open']
            close_end = df.iloc[i + lookback]['close']
            
            # Расчет % изменения
            price_change_pct = ((close_end - open_start) / open_start) * 100
            
            if price_change_pct >= roc_threshold:
                # Импульс найден!
                impulse_high = df.iloc[i:i+lookback+1]['high'].max()
                impulse_size = close_end - open_start
                
                if logger:
                    logger.info(f"📈 Импульс найден на индексе {i}: "
                               f"рост {price_change_pct:.2f}% за {lookback} свечей")
                
                # Сохраняем информацию об импульсе
                impulse_data = {
                    'start_idx': i,
                    'end_idx': i + lookback,
                    'start_price': open_start,
                    'high_price': impulse_high,
                    'size': impulse_size,
                    'change_pct': price_change_pct
                }
                result['impulses'].append(impulse_data)
                
                # Добавляем маркер на график (стрелка вверх)
                result['markers']['x'].append(df.iloc[i + lookback]['datetime'])
                result['markers']['y'].append(impulse_high)
                result['markers']['text'].append(f'Impulse {price_change_pct:.1f}%')
                result['markers']['color'].append('green')
                
                # Обновляем состояние
                last_impulse_high = impulse_high
                last_impulse_size = impulse_size
                min_allowed_price = impulse_high - (impulse_size * (max_retrace_pct / 100))
                consolidation_start = i + lookback + 1
                current_step += 1
                
                if logger:
                    logger.info(f"   Минимальная цена для консолидации: {min_allowed_price:.4f}")
                
                impulse_found = True
                i = i + lookback + 1  # Переходим к поиску консолидации
                break
        
        if not impulse_found:
            i += 1
            continue
        
        # ================================================================
        # ШАГ 2: ПОИСК КОНСОЛИДАЦИИ (CONSOLIDATION)
        # ================================================================
        if logger:
            logger.info(f"💤 Поиск консолидации начиная с индекса {consolidation_start}...")
        
        consolidation_broken = False
        consol_end = consolidation_start
        
        for j in range(consolidation_start, min(consolidation_start + max_consol_candles, n)):
            current_low = df.iloc[j]['low']
            
            # Проверка главного правила: 50% Retracement
            if current_low < min_allowed_price:
                # Консолидация сломана - цена упала слишком низко
                if logger:
                    logger.info(f"❌ Консолидация сломана на индексе {j}: "
                               f"Low={current_low:.4f} < Min={min_allowed_price:.4f}")
                consolidation_broken = True
                consol_end = j
                break
            
            consol_end = j
        
        if not consolidation_broken and consol_end > consolidation_start:
            # Консолидация успешна!
            duration = consol_end - consolidation_start
            
            if logger:
                logger.info(f"✅ Консолидация найдена: {duration} свечей "
                           f"(индексы {consolidation_start}-{consol_end})")
            
            # Сохраняем зону консолидации
            consolidation_data = {
                'start_idx': consolidation_start,
                'end_idx': consol_end,
                'start_datetime': df.iloc[consolidation_start]['datetime'],
                'end_datetime': df.iloc[consol_end]['datetime'],
                'min_price': df.iloc[consolidation_start:consol_end+1]['low'].min(),
                'max_price': df.iloc[consolidation_start:consol_end+1]['high'].max()
            }
            result['consolidations'].append(consolidation_data)
            
            # Добавляем прямоугольник на график (зона консолидации)
            result['shapes'].append({
                'type': 'rect',
                'xref': 'x',
                'yref': 'y',
                'x0': df.iloc[consolidation_start]['datetime'],
                'y0': min_allowed_price,
                'x1': df.iloc[consol_end]['datetime'],
                'y1': last_impulse_high,
                'fillcolor': 'rgba(0, 255, 0, 0.1)',
                'line': {'width': 0},
                'layer': 'below'
            })
            
            # ================================================================
            # ШАГ 3: ПОИСК СЛЕДУЮЩЕЙ СТУПЕНИ (BREAKOUT)
            # ================================================================
            # Проверяем, есть ли пробой выше предыдущего High
            breakout_found = False
            
            for k in range(consol_end + 1, min(consol_end + 20, n)):  # Ищем пробой в следующих 20 свечах
                if df.iloc[k]['close'] > last_impulse_high:
                    # Пробой найден!
                    if logger:
                        logger.info(f"🚀 Пробой найден на индексе {k}: "
                                   f"Close={df.iloc[k]['close']:.4f} > High={last_impulse_high:.4f}")
                    
                    # Добавляем маркер пробоя
                    result['markers']['x'].append(df.iloc[k]['datetime'])
                    result['markers']['y'].append(df.iloc[k]['close'])
                    result['markers']['text'].append(f'Breakout!')
                    result['markers']['color'].append('gold')
                    
                    breakout_found = True
                    
                    # Увеличиваем счетчик ступеней
                    if current_step >= 1:
                        result['steps_count'] += 1
                        
                        if result['steps_count'] >= 2:
                            result['pattern_found'] = True
                            
                            if logger:
                                logger.info(f"⭐ ПАТТЕРН НАЙДЕН! Количество ступеней: {result['steps_count']}")
                        
                        if result['steps_count'] >= 3:
                            if logger:
                                logger.info(f"🔥 УСИЛЕННЫЙ ПАТТЕРН! Ступеней: {result['steps_count']}")
                    
                    # Переходим к поиску следующего импульса
                    i = k + 1
                    last_impulse_high = None
                    break
            
            if not breakout_found:
                if logger:
                    logger.info(f"⏸️ Пробой не найден после консолидации")
                i = consol_end + 1
        else:
            # Консолидация не удалась или сломана
            i = consol_end + 1
    
    # Добавляем финальное сообщение
    if result['pattern_found']:
        if logger:
            logger.info(f"✅ Анализ завершен: Паттерн 'Бычья Лестница' найден!")
            logger.info(f"   Всего ступеней: {result['steps_count']}")
            logger.info(f"   Импульсов: {len(result['impulses'])}")
            logger.info(f"   Консолидаций: {len(result['consolidations'])}")
    else:
        if logger:
            logger.info(f"⚠️ Анализ завершен: Паттерн не найден или недостаточно ступеней")
            logger.info(f"   Найдено ступеней: {result['steps_count']} (требуется >= 2)")
    
    return result

# ============================================================================
# ВИЗУАЛИЗАЦИЯ (PLOTLY)
# ============================================================================

def create_chart(df: pd.DataFrame, scan_result: dict, supertrend_multiplier: float) -> go.Figure:
    """
    Создает интерактивный график с использованием Plotly.
    
    Структура:
    - График 1 (сверху): Candlestick + SuperTrend + Маркеры паттернов + Зоны консолидации
    - График 2 (снизу): ROC индикатор
    
    Параметры:
    - df: DataFrame с данными
    - scan_result: Результаты сканирования паттерна
    - supertrend_multiplier: Множитель SuperTrend для подписи
    
    Возвращает:
    - Plotly Figure объект
    """
    
    # Создаем subplot с 2 рядами (основной график + ROC)
    fig = make_subplots(
        rows=2, 
        cols=1, 
        shared_xaxes=True, 
        vertical_spacing=0.03, 
        row_heights=[0.7, 0.3],
        subplot_titles=('Цена + SuperTrend + Паттерны', 'ROC (Rate of Change)')
    )
    
    # ================================================================
    # ГРАФИК 1: СВЕЧИ + SUPERTREND
    # ================================================================
    
    # Добавляем свечи
    candle_colors = ['green' if row['close'] >= row['open'] else 'red' 
                     for _, row in df.iterrows()]
    
    fig.add_trace(
        go.Candlestick(
            x=df['datetime'],
            open=df['open'],
            high=df['high'],
            low=df['low'],
            close=df['close'],
            name='Цена',
            increasing_line_color='green',
            decreasing_line_color='red'
        ),
        row=1, col=1
    )
    
    # Добавляем линию SuperTrend (цвет зависит от тренда)
    supertrend_colors = ['green' if t == 1 else 'red' for t in df['trend']]
    
    fig.add_trace(
        go.Scatter(
            x=df['datetime'],
            y=df['supertrend'],
            mode='lines',
            name=f'SuperTrend ({supertrend_multiplier})',
            line=dict(color=supertrend_colors, width=2),
            hoverinfo='y'
        ),
        row=1, col=1
    )
    
    # Добавляем маркеры паттернов (импульсы и пробои)
    if scan_result['markers']['x']:
        fig.add_trace(
            go.Scatter(
                x=scan_result['markers']['x'],
                y=scan_result['markers']['y'],
                mode='markers+text',
                name='События паттерна',
                marker=dict(
                    size=12,
                    color=scan_result['markers']['color'],
                    symbol='triangle-up',
                    line=dict(width=2, color='white')
                ),
                text=scan_result['markers']['text'],
                textposition='top center',
                textfont=dict(size=10, color='white'),
                hoverinfo='text+y'
            ),
            row=1, col=1
        )
    
    # Добавляем зоны консолидации (прямоугольники)
    for shape in scan_result['shapes']:
        fig.add_shape(
            type=shape['type'],
            xref=shape['xref'],
            yref=shape['yref'],
            x0=shape['x0'],
            y0=shape['y0'],
            x1=shape['x1'],
            y1=shape['y1'],
            fillcolor=shape['fillcolor'],
            line=shape['line'],
            layer=shape['layer'],
            row=1, col=1
        )
    
    # Добавляем текст о найденном паттерне
    if scan_result['pattern_found']:
        steps = scan_result['steps_count']
        status_text = f"🎯 Staircase Found! Steps: {steps}" if steps >= 2 else "Pattern forming..."
        
        fig.add_annotation(
            x=df['datetime'].iloc[-1],
            y=df['high'].iloc[-10:].max(),
            text=status_text,
            showarrow=True,
            arrowhead=2,
            arrowsize=1.5,
            arrowcolor='gold',
            font=dict(size=14, color='gold', family='Arial Black'),
            bgcolor='rgba(0, 0, 0, 0.7)',
            bordercolor='gold',
            borderwidth=2,
            borderpad=10,
            xanchor='right',
            yanchor='top'
        )
    
    # ================================================================
    # ГРАФИК 2: ROC ИНДИКАТОР
    # ================================================================
    
    fig.add_trace(
        go.Scatter(
            x=df['datetime'],
            y=df['roc'],
            mode='lines',
            name='ROC',
            line=dict(color='blue', width=2),
            fill='tozeroy',
            fillcolor='rgba(0, 100, 255, 0.2)'
        ),
        row=2, col=1
    )
    
    # Горизонтальная линия на уровне 0
    fig.add_hline(
        y=0, 
        line_dash="dash", 
        line_color="gray", 
        row=2, col=1,
        annotation_text="Zero Line"
    )
    
    # ================================================================
    # НАСТРОЙКИ МАКЕТА
    # ================================================================
    
    fig.update_layout(
        height=800,
        template='plotly_dark',
        showlegend=True,
        legend=dict(
            orientation='h',
            yanchor='bottom',
            y=1.02,
            xanchor='right',
            x=1
        ),
        margin=dict(l=50, r=50, t=50, b=50),
        hovermode='x unified'
    )
    
    # Настройки осей
    fig.update_xaxes(
        rangeslider_visible=False,
        title="Время",
        row=2, col=1
    )
    
    fig.update_yaxes(
        title="Цена (USDT)",
        row=1, col=1
    )
    
    fig.update_yaxes(
        title="ROC (%)",
        row=2, col=1
    )
    
    return fig

# ============================================================================
# ЭКСПОРТ В CSV
# ============================================================================

def export_to_csv(df: pd.DataFrame, scan_result: dict, symbol: str) -> str:
    """
    Экспортирует данные анализа в CSV файл.
    
    Параметры:
    - df: DataFrame с основными данными
    - scan_result: Результаты сканирования паттерна
    - symbol: Торговая пара
    
    Возвращает:
    - Строка с содержимым CSV файла
    """
    
    # Создаем копию данных для экспорта
    export_df = df.copy()
    
    # Добавляем информацию о паттернах
    export_df['is_impulse'] = False
    export_df['is_consolidation'] = False
    export_df['is_breakout'] = False
    export_df['pattern_step'] = 0
    
    # Отмечаем импульсы
    for impulse in scan_result['impulses']:
        idx_range = range(impulse['start_idx'], impulse['end_idx'] + 1)
        export_df.loc[export_df.index[idx_range], 'is_impulse'] = True
    
    # Отмечаем консолидации
    for consol in scan_result['consolidations']:
        idx_range = range(consol['start_idx'], consol['end_idx'] + 1)
        export_df.loc[export_df.index[idx_range], 'is_consolidation'] = True
    
    # Отмечаем пробои
    for i, (x, text) in enumerate(zip(scan_result['markers']['x'], 
                                       scan_result['markers']['text'])):
        if 'Breakout' in text:
            mask = export_df['datetime'] == x
            export_df.loc[mask, 'is_breakout'] = True
            export_df.loc[mask, 'pattern_step'] = i + 1
    
    # Добавляем метаданные
    export_df['symbol'] = symbol
    export_df['pattern_found'] = scan_result['pattern_found']
    export_df['steps_count'] = scan_result['steps_count']
    
    # Выбираем нужные колонки
    columns_to_export = [
        'datetime', 'open', 'high', 'low', 'close', 'volume',
        'supertrend', 'trend', 'roc',
        'is_impulse', 'is_consolidation', 'is_breakout', 'pattern_step',
        'symbol', 'pattern_found', 'steps_count'
    ]
    
    # Конвертируем в CSV с разделителем ;
    csv_buffer = io.StringIO()
    export_df[columns_to_export].to_csv(csv_buffer, index=False, sep=';', decimal='.')
    
    return csv_buffer.getvalue()

# ============================================================================
# ИНТЕРФЕЙС STREAMLIT
# ============================================================================

def main():
    """Основная функция приложения Streamlit."""
    
    # Настройка страницы
    st.set_page_config(
        page_title="MEXC Pattern Analyzer",
        page_icon="📊",
        layout="wide",
        initial_sidebar_state="expanded"
    )
    
    # Заголовок приложения
    st.title("📊 MEXC Futures Pattern Analyzer")
    st.subheader("Поиск паттерна 'Бычья Лестница' (Bullish Staircase)")
    
    # ================================================================
    # SIDEBAR - ПАНЕЛЬ НАСТРОЕК
    # ================================================================
    
    with st.sidebar:
        st.header("⚙️ Настройки")
        
        # Выбор символа
        symbol = st.text_input(
            "Торговая пара",
            value="BTC/USDT",
            help="Пример: BTC/USDT, ETH/USDT, SOL/USDT"
        )
        
        st.divider()
        
        # Настройки SuperTrend
        st.subheader("📈 SuperTrend")
        atr_period = st.number_input(
            "ATR Period",
            min_value=1,
            max_value=100,
            value=10,
            step=1
        )
        supertrend_multiplier = st.number_input(
            "Multiplier",
            min_value=0.1,
            max_value=10.0,
            value=3.0,
            step=0.1
        )
        
        st.divider()
        
        # Настройки ROC
        st.subheader("📉 ROC Индикатор")
        roc_period = st.number_input(
            "Period",
            min_value=1,
            max_value=50,
            value=3,
            step=1
        )
        roc_threshold = st.number_input(
            "Threshold % (для импульса)",
            min_value=0.1,
            max_value=50.0,
            value=5.0,
            step=0.5
        )
        
        st.divider()
        
        # Настройки паттерна
        st.subheader("🎯 Паттерн 'Лестница'")
        max_retrace_pct = st.number_input(
            "Max Retrace %",
            min_value=10.0,
            max_value=90.0,
            value=50.0,
            step=5.0,
            help="Максимальный откат от вершины импульса (%)"
        )
        max_consol_candles = st.number_input(
            "Max Consol Candles",
            min_value=10,
            max_value=200,
            value=50,
            step=5,
            help="Максимальная длительность консолидации (свечи)"
        )
        
        st.divider()
        
        # Кнопка запуска анализа
        analyze_button = st.button(
            "🔍 SCAN & ANALYZE",
            type="primary",
            use_container_width=True
        )
        
        # Чекбокс сохранения CSV
        save_csv = st.checkbox(
            "💾 Save CSV",
            value=False,
            help="Сохранить результаты анализа в CSV файл"
        )
        
        st.divider()
        
        # Информация о приложении
        st.info("""
        **Как использовать:**
        1. Введите торговую пару
        2. Настройте параметры индикаторов
        3. Нажмите SCAN & ANALYZE
        4. Изучите график и логи
        5. При необходимости сохраните CSV
        """)
    
    # ================================================================
    # MAIN AREA - ОСНОВНАЯ ОБЛАСТЬ
    # ================================================================
    
    # Контейнер для логов
    log_container = st.container()
    
    # Инициализация состояния сессии
    if 'data_loaded' not in st.session_state:
        st.session_state.data_loaded = False
    if 'df' not in st.session_state:
        st.session_state.df = None
    if 'scan_result' not in st.session_state:
        st.session_state.scan_result = None
    if 'chart' not in st.session_state:
        st.session_state.chart = None
    
    # Обработка нажатия кнопки анализа
    if analyze_button:
        # Контейнер для прогресса
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Контейнер для логов
        with log_container:
            st.subheader("📋 Журнал событий")
            log_box = st.empty()
            logger = setup_logging(log_box)
        
        try:
            # Шаг 1: Загрузка данных
            status_text.text("⏳ Загрузка данных с MEXC...")
            logger.info(f"📡 Запрос данных для {symbol} (таймфрейм 15m, 200 свечей)...")
            df = fetch_mexc_data(symbol, timeframe='15m', limit=200)
            progress_bar.progress(25)
            logger.info(f"✅ Получено {len(df)} свечей")
            
            # Шаг 2: Расчет индикаторов
            status_text.text("📊 Расчет индикаторов...")
            logger.info("🧮 Расчет SuperTrend...")
            df = calculate_supertrend(df, atr_period=atr_period, multiplier=supertrend_multiplier)
            progress_bar.progress(50)
            logger.info(f"✅ SuperTrend рассчитан (ATR={atr_period}, Mult={supertrend_multiplier})")
            
            logger.info("🧮 Расчет ROC...")
            df = calculate_roc(df, period=roc_period)
            progress_bar.progress(60)
            logger.info(f"✅ ROC рассчитан (Period={roc_period})")
            
            # Шаг 3: Сканирование паттерна
            status_text.text("🔍 Сканирование паттерна...")
            logger.info("🎯 Запуск алгоритма поиска 'Бычья Лестница'...")
            scan_result = scan_bullish_staircase(
                df,
                roc_threshold=roc_threshold,
                max_retrace_pct=max_retrace_pct,
                max_consol_candles=max_consol_candles,
                logger=logger
            )
            progress_bar.progress(80)
            
            # Шаг 4: Построение графика
            status_text.text("📈 Построение графика...")
            logger.info("🎨 Генерация визуализации...")
            chart = create_chart(df, scan_result, supertrend_multiplier)
            progress_bar.progress(100)
            logger.info("✅ График готов!")
            
            # Сохранение в session state
            st.session_state.data_loaded = True
            st.session_state.df = df
            st.session_state.scan_result = scan_result
            st.session_state.chart = chart
            
            status_text.text("✅ Анализ завершен!")
            
        except Exception as e:
            st.error(f"❌ Ошибка: {str(e)}")
            logger.error(f"❌ Критическая ошибка: {str(e)}")
            progress_bar.empty()
            status_text.empty()
    
    # Отображение результатов
    if st.session_state.data_loaded and st.session_state.chart is not None:
        # График
        st.plotly_chart(st.session_state.chart, use_container_width=True)
        
        # Дополнительная информация о паттерне
        scan_result = st.session_state.scan_result
        
        col1, col2, col3, col4 = st.columns(4)
        
        with col1:
            st.metric(
                label="Ступеней найдено",
                value=scan_result['steps_count'],
                delta="✓" if scan_result['steps_count'] >= 2 else "✗"
            )
        
        with col2:
            st.metric(
                label="Паттерн найден",
                value="ДА" if scan_result['pattern_found'] else "НЕТ",
                delta="🎯" if scan_result['pattern_found'] else ""
            )
        
        with col3:
            st.metric(
                label="Импульсов",
                value=len(scan_result['impulses'])
            )
        
        with col4:
            st.metric(
                label="Консолидаций",
                value=len(scan_result['consolidations'])
            )
        
        # Детали паттерна
        if scan_result['pattern_found']:
            st.success(f"**🎯 ПАТТЕРН НАЙДЕН!** Количество ступеней: **{scan_result['steps_count']}**")
            
            with st.expander("📊 Детали паттерна", expanded=False):
                st.write("**Импульсы:**")
                for i, impulse in enumerate(scan_result['impulses'], 1):
                    st.write(f"- Импульс #{i}: Рост {impulse['change_pct']:.2f}% "
                            f"(с {impulse['start_price']:.4f} до {impulse['high_price']:.4f})")
                
                st.write("\n**Консолидации:**")
                for i, consol in enumerate(scan_result['consolidations'], 1):
                    duration = consol['end_idx'] - consol['start_idx']
                    st.write(f"- Консолидация #{i}: {duration} свечей "
                            f"(диапазон: {consol['min_price']:.4f} - {consol['max_price']:.4f})")
        
        # Экспорт в CSV
        if save_csv:
            csv_data = export_to_csv(
                st.session_state.df,
                scan_result,
                symbol
            )
            
            st.download_button(
                label="📥 Скачать CSV",
                data=csv_data,
                file_name=f"{symbol.replace('/', '_')}_staircase_analysis_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
                mime="text/csv",
                use_container_width=True
            )
    
    else:
        # Заглушка, если данные еще не загружены
        st.info("👈 Нажмите кнопку **SCAN & ANALYZE** в левой панели для начала анализа")
        
        # Пример графика для демонстрации
        st.markdown("### Пример того, что вы увидите:")
        
        # Создаем демо-данные
        dates = pd.date_range(start='2024-01-01', periods=100, freq='H')
        demo_df = pd.DataFrame({
            'datetime': dates,
            'open': np.random.uniform(100, 110, 100),
            'high': np.random.uniform(110, 115, 100),
            'low': np.random.uniform(95, 100, 100),
            'close': np.random.uniform(100, 110, 100),
            'volume': np.random.uniform(1000, 5000, 100)
        })
        demo_df = calculate_supertrend(demo_df)
        demo_df = calculate_roc(demo_df)
        
        demo_scan_result = {
            'impulses': [],
            'consolidations': [],
            'steps_count': 0,
            'pattern_found': False,
            'markers': {'x': [], 'y': [], 'text': [], 'color': []},
            'shapes': []
        }
        
        demo_chart = create_chart(demo_df, demo_scan_result, 3.0)
        st.plotly_chart(demo_chart, use_container_width=True)

if __name__ == "__main__":
    main()
