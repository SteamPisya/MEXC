"""
Pattern detection engine for stackable consolidations.
Uses vectorized pandas operations for O(n) performance.
"""

from dataclasses import dataclass
from typing import List, Optional

import pandas as pd

from config import config


@dataclass
class Consolidation:
    """Represents a single consolidation zone"""
    start_idx: int
    end_idx: int
    low: float
    high: float
    time_start: pd.Timestamp
    time_end: pd.Timestamp
    duration: int
    amplitude_pct: float


@dataclass
class StackablePattern:
    """Represents a stackable consolidations pattern"""
    consol1: Consolidation
    consol2: Consolidation
    entry_price: float
    tp_price: float
    sl_price: float
    direction: str  # 'LONG' or 'SHORT'
    time_start: pd.Timestamp
    time_end: pd.Timestamp


class PatternEngine:
    """Vectorized pattern detection for stackable consolidations"""

    def __init__(self):
        self.min_amplitude = config.pattern.min_amplitude_pct
        self.max_amplitude = config.pattern.max_amplitude_pct
        self.min_length = config.pattern.min_consolidation_length
        self.y_gap_pct = config.pattern.y_gap_pct
        self.x_gap_candles = config.pattern.x_gap_candles
        self.max_candles_after = config.pattern.max_candles_after

    def find_consolidations(
        self,
        df: pd.DataFrame,
        min_amp_pct: float = None,
        max_amp_pct: float = None,
        min_len: int = None
    ) -> List[Consolidation]:
        """
        Find consolidation zones in price data using vectorized operations.
        
        A consolidation is defined as a series of candles where:
        - Price amplitude (high-low)/low is within specified range
        - Minimum number of consecutive candles
        
        Args:
            df: DataFrame with OHLCV data
            min_amp_pct: Minimum amplitude percentage
            max_amp_pct: Maximum amplitude percentage
            min_len: Minimum consolidation length
            
        Returns:
            List of Consolidation objects
        """
        if df.empty or len(df) < 5:
            return []

        min_amp = min_amp_pct or self.min_amplitude
        max_amp = max_amp_pct or self.max_amplitude
        min_length = min_len or self.min_length

        # Calculate amplitude for each candle: (high - low) / low * 100
        amplitudes = (df['high'] - df['low']) / df['low'] * 100

        # Create boolean mask for candles within amplitude range
        in_range = (amplitudes >= min_amp) & (amplitudes <= max_amp)

        # Find consecutive groups using diff and cumsum
        # This is O(n) vectorized operation
        group_changes = in_range.astype(int).diff().fillna(0).abs()
        groups = group_changes.cumsum()

        consolidations = []
        
        # Group by consecutive True values
        for group_id in groups[in_range].unique():
            indices = df.index[(groups == group_id) & in_range]
            
            if len(indices) < min_length:
                continue

            start_idx = indices[0]
            end_idx = indices[-1]

            # Get consolidation statistics
            subset = df.loc[start_idx:end_idx]
            consol_low = subset['low'].min()
            consol_high = subset['high'].max()
            amplitude = (consol_high - consol_low) / consol_low * 100

            # Validate amplitude for the entire consolidation
            if amplitude < min_amp or amplitude > max_amp:
                continue

            consol = Consolidation(
                start_idx=int(start_idx),
                end_idx=int(end_idx),
                low=consol_low,
                high=consol_high,
                time_start=subset['timestamp'].iloc[0],
                time_end=subset['timestamp'].iloc[-1],
                duration=len(subset),
                amplitude_pct=amplitude
            )
            consolidations.append(consol)

        return consolidations

    def find_stackable_patterns(
        self,
        df: pd.DataFrame,
        y_gap_pct: float = None,
        x_gap_candles: int = None
    ) -> List[StackablePattern]:
        """
        Find stackable consolidation patterns.
        
        A stackable pattern consists of two consolidations where:
        - Second consolidation is above first (for bullish) or below (for bearish)
        - Vertical gap between consolidations is within threshold
        - Horizontal gap (candles between) is within threshold
        
        Args:
            df: DataFrame with OHLCV data
            y_gap_pct: Maximum vertical gap percentage
            x_gap_candles: Maximum horizontal gap in candles
            
        Returns:
            List of StackablePattern objects
        """
        if df.empty or len(df) < 10:
            return []

        y_gap = y_gap_pct or self.y_gap_pct
        x_gap = x_gap_candles or self.x_gap_candles

        # Find all consolidations
        consolidations = self.find_consolidations(df)
        
        if len(consolidations) < 2:
            return []

        patterns = []

        # Check pairs of consolidations - O(n) since consolidations are limited
        for i in range(len(consolidations) - 1):
            c1 = consolidations[i]
            c2 = consolidations[i + 1]

            # Check horizontal gap
            h_gap = c2.start_idx - c1.end_idx - 1
            if h_gap < 0 or h_gap > x_gap:
                continue

            # Calculate vertical gap percentage
            # For bullish: c2 is above c1
            v_gap_bullish = (c2.low - c1.high) / c1.high * 100 if c1.high > 0 else 999
            
            # For bearish: c2 is below c1
            v_gap_bearish = (c1.low - c2.high) / c1.low * 100 if c1.low > 0 else 999

            # Check if pattern is valid (bullish or bearish)
            direction = None
            if 0 <= v_gap_bullish <= y_gap:
                direction = 'LONG'
            elif 0 <= v_gap_bearish <= y_gap:
                direction = 'SHORT'

            if not direction:
                continue

            # Calculate entry, TP, SL
            if direction == 'LONG':
                entry_price = c2.high  # Breakout above second consolidation
                sl_price = c1.low * 0.995  # Below first consolidation
                tp_distance = entry_price - sl_price
                tp_price = entry_price + tp_distance * config.trading.risk_reward_ratio
            else:  # SHORT
                entry_price = c2.low  # Breakdown below second consolidation
                sl_price = c1.high * 1.005  # Above first consolidation
                tp_distance = sl_price - entry_price
                tp_price = entry_price - tp_distance * config.trading.risk_reward_ratio

            pattern = StackablePattern(
                consol1=c1,
                consol2=c2,
                entry_price=entry_price,
                tp_price=tp_price,
                sl_price=sl_price,
                direction=direction,
                time_start=c1.time_start,
                time_end=c2.time_end
            )
            patterns.append(pattern)

        return patterns

    def detect_pattern(
        self,
        df: pd.DataFrame
    ) -> Optional[StackablePattern]:
        """
        Detect the most recent valid stackable pattern.
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            StackablePattern if found, None otherwise
        """
        if df.empty or len(df) < 20:
            return None

        patterns = self.find_stackable_patterns(df)
        
        if not patterns:
            return None

        # Return the most recent pattern
        return patterns[-1]

    def validate_entry_window(
        self,
        df: pd.DataFrame,
        pattern: StackablePattern,
        max_candles_after: int = None
    ) -> bool:
        """
        Validate that we're still within the entry window.
        
        Args:
            df: Current DataFrame
            pattern: Detected pattern
            max_candles_after: Maximum candles after pattern end
            
        Returns:
            True if still within entry window
        """
        max_after = max_candles_after or self.max_candles_after
        
        if df.empty:
            return False

        last_timestamp = df['timestamp'].iloc[-1]
        candles_after = len(df[df['timestamp'] > pattern.time_end])
        
        return candles_after <= max_after


# Global pattern engine instance
pattern_engine = PatternEngine()
