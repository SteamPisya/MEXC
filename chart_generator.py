"""
Chart generator using matplotlib with thread pool execution.
Creates signal and result charts with proper validation.
"""

import asyncio
import io
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, Optional

import matplotlib
matplotlib.use('Agg')  # Non-interactive backend
import matplotlib.pyplot as plt
import pandas as pd

from config import config


class ChartGenerator:
    """Generate trading charts with thread pool execution"""

    def __init__(self):
        self.max_workers = config.bot.chart_workers
        self.timeout = config.bot.chart_timeout_seconds
        self._executor = ThreadPoolExecutor(max_workers=self.max_workers)

    async def generate_signal_chart(
        self,
        df: pd.DataFrame,
        pattern: Any,
        symbol: str
    ) -> Optional[bytes]:
        """
        Generate chart for a detected pattern.
        
        Args:
            df: DataFrame with OHLCV data
            pattern: StackablePattern object
            symbol: Trading pair symbol
            
        Returns:
            PNG image bytes or None if generation fails
        """
        try:
            loop = asyncio.get_event_loop()
            
            # Run in thread pool with timeout
            func = self._generate_signal_chart_sync
            args = (df, pattern, symbol)
            
            chart_bytes = await asyncio.wait_for(
                loop.run_in_executor(self._executor, func, *args),
                timeout=self.timeout
            )
            
            return chart_bytes
            
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    def _generate_signal_chart_sync(
        self,
        df: pd.DataFrame,
        pattern: Any,
        symbol: str
    ) -> Optional[bytes]:
        """Synchronous chart generation for signal"""
        try:
            if df.empty:
                return None

            # Get pattern indices safely
            consol1_start = pattern.consol1.start_idx
            consol2_end = pattern.consol2.end_idx

            # Calculate safe view window with strict validation
            start_idx = max(0, consol1_start - 60)
            end_idx = min(len(df), consol2_end + 40)

            # Critical validation: ensure valid range
            if start_idx >= end_idx:
                return None

            view_df = df.iloc[start_idx:end_idx].copy()

            if view_df.empty or len(view_df) < 5:
                return None

            # Reset index for consistent plotting
            view_df = view_df.reset_index(drop=True)

            # Recalculate pattern indices relative to view
            view_consol1_start = consol1_start - start_idx
            view_consol2_end = consol2_end - start_idx

            # Validate recalculated indices
            if view_consol1_start < 0 or view_consol1_start >= len(view_df):
                return None
            if view_consol2_end < 0 or view_consol2_end >= len(view_df):
                return None

            # Create figure
            fig, ax = plt.subplots(figsize=(14, 8))
            fig.patch.set_facecolor('#1a1a2e')
            ax.set_facecolor('#16213e')

            # Plot candlesticks
            self._plot_candlesticks(ax, view_df)

            # Draw consolidation zones
            # Consolidation 1
            ax.axhspan(
                pattern.consol1.low,
                pattern.consol1.high,
                alpha=0.3,
                color='gray',
                label=f'Consol 1: {pattern.consol1.amplitude_pct:.1f}%'
            )

            # Consolidation 2
            ax.axhspan(
                pattern.consol2.low,
                pattern.consol2.high,
                alpha=0.3,
                color='gray'
            )

            # Draw entry, TP, SL lines
            entry_idx = view_consol2_end
            
            # Entry line
            ax.axhline(
                y=pattern.entry_price,
                color='yellow',
                linestyle='--',
                linewidth=1.5,
                label=f'Entry: {pattern.entry_price:.4f}'
            )

            # TP line
            ax.axhline(
                y=pattern.tp_price,
                color='green',
                linestyle='--',
                linewidth=1.5,
                label=f'TP: {pattern.tp_price:.4f}'
            )

            # SL line
            ax.axhline(
                y=pattern.sl_price,
                color='red',
                linestyle='--',
                linewidth=1.5,
                label=f'SL: {pattern.sl_price:.4f}'
            )

            # Add annotations with vertical offset to avoid overlap
            # Entry annotation
            ax.annotate(
                'ENTRY',
                xy=(entry_idx, pattern.entry_price),
                xytext=(0, 30),
                textcoords='offset points',
                ha='center',
                fontsize=9,
                fontweight='bold',
                color='yellow',
                arrowprops=dict(arrowstyle='->', color='yellow', lw=1.5)
            )

            # TP annotation
            ax.annotate(
                'TP',
                xy=(entry_idx, pattern.tp_price),
                xytext=(0, 30),
                textcoords='offset points',
                ha='center',
                fontsize=9,
                fontweight='bold',
                color='green',
                arrowprops=dict(arrowstyle='->', color='green', lw=1.5)
            )

            # SL annotation
            ax.annotate(
                'SL',
                xy=(entry_idx, pattern.sl_price),
                xytext=(0, -30),
                textcoords='offset points',
                ha='center',
                fontsize=9,
                fontweight='bold',
                color='red',
                arrowprops=dict(arrowstyle='->', color='red', lw=1.5)
            )

            # Title and labels
            direction_color = 'green' if pattern.direction == 'LONG' else 'red'
            ax.set_title(
                f'{symbol} - {pattern.direction} Stackable Pattern\n'
                f'R:R = {config.trading.risk_reward_ratio}:1',
                color='white',
                fontsize=14,
                fontweight='bold'
            )
            ax.set_xlabel('Candles', color='white')
            ax.set_ylabel('Price', color='white')

            # Style grid and ticks
            ax.grid(True, alpha=0.3, color='gray')
            ax.tick_params(colors='white')
            for spine in ax.spines.values():
                spine.set_color('gray')

            # Legend
            ax.legend(loc='upper left', facecolor='#16213e', edgecolor='gray', labelcolor='white')

            # Save to bytes
            buf = io.BytesIO()
            plt.savefig(
                buf,
                format='png',
                dpi=100,
                bbox_inches='tight',
                facecolor=fig.patch.get_facecolor()
            )
            buf.seek(0)
            plt.close(fig)

            return buf.getvalue()

        except Exception:
            return None

    async def generate_result_chart(
        self,
        df: pd.DataFrame,
        signal: Dict[str, Any],
        outcome: str,
        exit_price: float
    ) -> Optional[bytes]:
        """
        Generate chart for a closed signal result.
        
        Args:
            df: DataFrame with OHLCV data
            signal: Signal dictionary from database
            outcome: WIN or LOSE
            exit_price: Exit price
            
        Returns:
            PNG image bytes or None if generation fails
        """
        try:
            loop = asyncio.get_event_loop()
            
            func = self._generate_result_chart_sync
            args = (df, signal, outcome, exit_price)
            
            chart_bytes = await asyncio.wait_for(
                loop.run_in_executor(self._executor, func, *args),
                timeout=self.timeout
            )
            
            return chart_bytes
            
        except asyncio.TimeoutError:
            return None
        except Exception:
            return None

    def _generate_result_chart_sync(
        self,
        df: pd.DataFrame,
        signal: Dict[str, Any],
        outcome: str,
        exit_price: float
    ) -> Optional[bytes]:
        """Synchronous chart generation for result"""
        try:
            if df.empty:
                return None

            # Find entry candle by timestamp
            entry_time_str = signal['entry_time']
            try:
                entry_time = pd.to_datetime(entry_time_str)
            except Exception:
                return None

            # Find entry index safely
            entry_indices = df.index[df['timestamp'] == entry_time]
            if len(entry_indices) == 0:
                # Try to find closest timestamp
                time_diffs = (df['timestamp'] - entry_time).abs()
                entry_idx = time_diffs.idxmin()
            else:
                entry_idx = entry_indices[0]

            # Calculate safe view window with strict validation
            start_idx = max(0, int(entry_idx) - 60)
            end_idx = min(len(df), int(entry_idx) + 40)

            # Critical validation
            if start_idx >= end_idx:
                return None

            view_df = df.iloc[start_idx:end_idx].copy()

            if view_df.empty or len(view_df) < 5:
                return None

            view_df = view_df.reset_index(drop=True)

            # Recalculate entry index relative to view
            view_entry_idx = int(entry_idx) - start_idx

            if view_entry_idx < 0 or view_entry_idx >= len(view_df):
                return None

            # Create figure
            fig, ax = plt.subplots(figsize=(14, 8))
            fig.patch.set_facecolor('#1a1a2e')
            ax.set_facecolor('#16213e')

            # Plot candlesticks
            self._plot_candlesticks(ax, view_df)

            # Get prices from signal
            entry_price = signal['entry_price']
            tp_price = signal['tp_price']
            sl_price = signal['sl_price']

            # Draw levels
            ax.axhline(y=entry_price, color='yellow', linestyle='--', linewidth=1.5, label=f'Entry: {entry_price:.4f}')
            ax.axhline(y=tp_price, color='green', linestyle='--', linewidth=1.5, label=f'TP: {tp_price:.4f}')
            ax.axhline(y=sl_price, color='red', linestyle='--', linewidth=1.5, label=f'SL: {sl_price:.4f}')
            ax.axhline(y=exit_price, color='white', linestyle='-', linewidth=2, label=f'Exit: {exit_price:.4f}')

            # Annotations with vertical offset
            ax.annotate(
                'ENTRY',
                xy=(view_entry_idx, entry_price),
                xytext=(0, 30),
                textcoords='offset points',
                ha='center',
                fontsize=9,
                fontweight='bold',
                color='yellow',
                arrowprops=dict(arrowstyle='->', color='yellow', lw=1.5)
            )

            # Exit annotation
            exit_color = 'green' if outcome == 'WIN' else 'red'
            result_text = 'WIN' if outcome == 'WIN' else 'LOSE'
            
            # Find exit candle (approximate)
            exit_idx = view_entry_idx + 10  # Approximate
            if exit_idx >= len(view_df):
                exit_idx = len(view_df) - 1

            ax.annotate(
                f'{result_text}',
                xy=(exit_idx, exit_price),
                xytext=(0, -30 if exit_price < entry_price else 30),
                textcoords='offset points',
                ha='center',
                fontsize=10,
                fontweight='bold',
                color=exit_color,
                arrowprops=dict(arrowstyle='->', color=exit_color, lw=2)
            )

            # Calculate PnL
            pnl = (exit_price - entry_price) / entry_price * 100
            if tp_price < entry_price:  # Short position
                pnl = (entry_price - exit_price) / entry_price * 100

            pnl_sign = '+' if pnl > 0 else ''
            
            # Title
            ax.set_title(
                f'{signal["symbol"]} - {result_text}\n'
                f'PnL: {pnl_sign}{pnl:.2f}%',
                color='white',
                fontsize=14,
                fontweight='bold'
            )
            
            ax.set_xlabel('Candles', color='white')
            ax.set_ylabel('Price', color='white')

            # Style
            ax.grid(True, alpha=0.3, color='gray')
            ax.tick_params(colors='white')
            for spine in ax.spines.values():
                spine.set_color('gray')

            ax.legend(loc='upper left', facecolor='#16213e', edgecolor='gray', labelcolor='white')

            # Save to bytes
            buf = io.BytesIO()
            plt.savefig(
                buf,
                format='png',
                dpi=100,
                bbox_inches='tight',
                facecolor=fig.patch.get_facecolor()
            )
            buf.seek(0)
            plt.close(fig)

            return buf.getvalue()

        except Exception:
            return None

    def _plot_candlesticks(self, ax, df):
        """Plot candlestick chart"""
        if df.empty or len(df) < 1:
            return

        # Calculate colors
        colors = ['green' if df['close'].iloc[i] >= df['open'].iloc[i] else 'red' 
                  for i in range(len(df))]

        # Plot candles
        for i in range(len(df)):
            row = df.iloc[i]
            
            # Wick
            ax.plot(
                [i, i],
                [row['low'], row['high']],
                color=colors[i],
                linewidth=1
            )
            
            # Body
            body_bottom = min(row['open'], row['close'])
            body_height = abs(row['close'] - row['open'])
            
            if body_height > 0:
                ax.bar(
                    i,
                    body_height,
                    bottom=body_bottom,
                    color=colors[i],
                    width=0.8
                )

    def close(self):
        """Close the thread pool executor"""
        self._executor.shutdown(wait=False)


# Global chart generator instance
chart_generator = ChartGenerator()
