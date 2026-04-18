"""
Result tracker for monitoring TP/SL levels on active signals.
Checks price action against target levels using candle shadows.
"""

from datetime import datetime
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from config import config
from database import SignalStatus


class ResultTracker:
    """Track and evaluate signal outcomes based on TP/SL levels"""

    def __init__(self):
        self.tp_pct = config.trading.tp_percent
        self.sl_pct = config.trading.sl_percent

    def check_signal_outcome(
        self,
        df: pd.DataFrame,
        signal: Dict[str, Any]
    ) -> Tuple[Optional[str], Optional[float], Optional[str]]:
        """
        Check if a signal has reached TP or SL.
        
        Uses candle shadows (low/high) for accurate detection.
        Falls back to close price if no shadow trigger.
        
        Args:
            df: DataFrame with OHLCV data (must include candles after entry)
            signal: Signal dictionary from database
            
        Returns:
            Tuple of (outcome, exit_price, exit_timestamp)
            outcome: 'WIN', 'LOSE', or None if still pending
            exit_price: Price at which signal was closed
            exit_timestamp: ISO timestamp of exit
        """
        if df.empty:
            return None, None, None

        entry_time_str = signal['entry_time']
        entry_price = signal['entry_price']
        tp_price = signal['tp_price']
        sl_price = signal['sl_price']

        # Parse entry time
        try:
            entry_time = pd.to_datetime(entry_time_str)
        except Exception:
            return None, None, None

        # Filter candles from entry time onwards
        future_candles = df[df['timestamp'] >= entry_time]

        if future_candles.empty:
            return None, None, None

        # Check each candle for TP/SL trigger using shadows
        for idx, row in future_candles.iterrows():
            candle_low = row['low']
            candle_high = row['high']
            candle_time = row['timestamp']

            # For LONG positions: check if high >= TP or low <= SL
            # For SHORT positions: check if low <= TP or high >= SL
            # Note: In our pattern, TP is always the profitable target
            
            # Determine direction from prices
            is_long = tp_price > entry_price

            if is_long:
                # Long position: TP above, SL below
                if candle_high >= tp_price:
                    return SignalStatus.WIN, tp_price, candle_time.isoformat()
                if candle_low <= sl_price:
                    return SignalStatus.LOSE, sl_price, candle_time.isoformat()
            else:
                # Short position: TP below, SL above
                if candle_low <= tp_price:
                    return SignalStatus.WIN, tp_price, candle_time.isoformat()
                if candle_high >= sl_price:
                    return SignalStatus.LOSE, sl_price, candle_time.isoformat()

        # If no trigger found, check last candle close for potential manual exit
        last_row = future_candles.iloc[-1]
        last_close = last_row['close']
        last_time = last_row['timestamp']

        # Optional: Check if we should exit based on close price
        # This handles cases where price crossed but shadow didn't capture it
        is_long = tp_price > entry_price
        
        if is_long:
            if last_close >= tp_price * 0.998:  # Within 0.2% of TP
                return SignalStatus.WIN, last_close, last_time.isoformat()
            if last_close <= sl_price * 1.002:  # Within 0.2% of SL
                return SignalStatus.LOSE, last_close, last_time.isoformat()
        else:
            if last_close <= tp_price * 1.002:  # Within 0.2% of TP
                return SignalStatus.WIN, last_close, last_time.isoformat()
            if last_close >= sl_price * 0.998:  # Within 0.2% of SL
                return SignalStatus.LOSE, last_close, last_time.isoformat()

        # Still pending
        return None, None, None

    def calculate_pnl(
        self,
        entry_price: float,
        exit_price: float,
        outcome: str
    ) -> float:
        """
        Calculate PnL percentage.
        
        Args:
            entry_price: Entry price
            exit_price: Exit price
            outcome: WIN or LOSE
            
        Returns:
            PnL percentage (positive for win, negative for loss)
        """
        if not exit_price or not entry_price:
            return 0.0

        pnl_pct = (exit_price - entry_price) / entry_price * 100
        
        # For wins, ensure positive; for losses, ensure negative
        if outcome == SignalStatus.WIN:
            return abs(pnl_pct)
        else:
            return -abs(pnl_pct)

    def get_current_unrealized_pnl(
        self,
        df: pd.DataFrame,
        signal: Dict[str, Any]
    ) -> float:
        """
        Calculate current unrealized PnL based on latest price.
        
        Args:
            df: DataFrame with OHLCV data
            signal: Signal dictionary
            
        Returns:
            Unrealized PnL percentage
        """
        if df.empty:
            return 0.0

        current_price = df['close'].iloc[-1]
        entry_price = signal['entry_price']
        tp_price = signal['tp_price']

        is_long = tp_price > entry_price

        if is_long:
            pnl_pct = (current_price - entry_price) / entry_price * 100
        else:
            pnl_pct = (entry_price - current_price) / entry_price * 100

        return pnl_pct


# Global result tracker instance
result_tracker = ResultTracker()
