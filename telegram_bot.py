"""
Telegram bot using aiogram 3.x for async notifications.
Handles signal alerts, result updates, and statistics with retry logic.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from aiogram import Bot, Dispatcher, types
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from aiogram.types import InputFile

from config import config
from database import db


logger = logging.getLogger(__name__)


class TelegramNotifier:
    """Async Telegram notifier with retry logic and fallback"""

    def __init__(self):
        self.bot_token = config.telegram.bot_token
        self.chat_id = config.telegram.chat_id
        self.timeout = config.telegram.timeout_seconds
        self.retry_count = config.telegram.retry_count
        
        self.bot: Optional[Bot] = None
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the Telegram bot"""
        if self._initialized:
            return

        if not self.bot_token or self.bot_token == "":
            logger.warning("Telegram bot token not configured")
            return

        self.bot = Bot(token=self.bot_token)
        
        # Test connection
        try:
            await self.bot.get_me()
            self._initialized = True
            logger.info("Telegram bot initialized successfully")
        except Exception as e:
            logger.error(f"Failed to initialize Telegram bot: {e}")
            self._initialized = False

    async def close(self) -> None:
        """Close the bot session"""
        if self.bot:
            await self.bot.close()
            self._initialized = False

    async def send_signal(
        self,
        symbol: str,
        steps: int,
        price: float,
        direction: str,
        tp: float,
        sl: float,
        chart_bytes: Optional[bytes],
        caption: Optional[str] = None
    ) -> Optional[int]:
        """
        Send signal notification with optional chart.
        
        Args:
            symbol: Trading pair symbol
            steps: Pattern steps (always 2 for stackable)
            price: Entry price
            direction: LONG or SHORT
            tp: Take profit price
            sl: Stop loss price
            chart_bytes: PNG chart image bytes
            caption: Optional additional text
            
        Returns:
            Message ID if sent successfully, None otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        if not self._initialized:
            return None

        # Build caption
        direction_emoji = "📈" if direction == "LONG" else "📉"
        text = (
            f"🚀 {direction_emoji} *NEW SIGNAL* {direction_emoji}\n\n"
            f"📊 Symbol: `{symbol}`\n"
            f"🎯 Direction: *{direction}*\n"
            f"💰 Entry: `{price:.5f}`\n"
            f"✅ TP: `{tp:.5f}`\n"
            f"❌ SL: `{sl:.5f}`\n"
            f"📐 R:R = {config.trading.risk_reward_ratio}:1\n\n"
        )
        
        if caption:
            text += f"{caption}\n"
        
        text += "_Stackable Consolidations Pattern_"

        message_id = None

        for attempt in range(self.retry_count):
            try:
                if chart_bytes:
                    # Send photo with caption
                    photo = InputFile.from_buffer(chart_bytes, filename="chart.png")
                    response = await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=photo,
                        caption=text,
                        parse_mode="Markdown"
                    )
                    message_id = response.message_id
                else:
                    # Send text only
                    response = await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=text,
                        parse_mode="Markdown"
                    )
                    message_id = response.message_id

                logger.info(f"Signal notification sent for {symbol}, message_id: {message_id}")
                return message_id

            except TelegramRetryAfter as e:
                wait_time = e.retry_after
                logger.warning(f"Rate limited by Telegram, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                
            except TelegramAPIError as e:
                logger.error(f"Telegram API error (attempt {attempt + 1}): {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    
            except Exception as e:
                logger.error(f"Unexpected error sending signal: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(1)

        return None

    async def send_result(
        self,
        signal_id: int,
        symbol: str,
        outcome: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        chart_bytes: Optional[bytes],
        reply_to_message_id: Optional[int] = None
    ) -> Optional[int]:
        """
        Send result notification for closed signal.
        
        Args:
            signal_id: Signal database ID
            symbol: Trading pair symbol
            outcome: WIN or LOSE
            entry_price: Entry price
            exit_price: Exit price
            pnl: PnL percentage
            chart_bytes: PNG chart image bytes
            reply_to_message_id: Original signal message ID for threading
            
        Returns:
            Message ID if sent successfully, None otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        if not self._initialized:
            return None

        # Build caption
        result_emoji = "✅" if outcome == "WIN" else "❌"
        pnl_sign = "+" if pnl > 0 else ""
        pnl_color = "🟢" if pnl > 0 else "🔴"
        
        text = (
            f"{result_emoji} *SIGNAL CLOSED* {result_emoji}\n\n"
            f"📊 Symbol: `{symbol}`\n"
            f"📈 Result: *{outcome}* {pnl_color}\n"
            f"💰 Entry: `{entry_price:.5f}`\n"
            f"💵 Exit: `{exit_price:.5f}`\n"
            f"📊 PnL: *{pnl_sign}{pnl:.2f}%*\n\n"
        )

        message_id = None

        for attempt in range(self.retry_count):
            try:
                if chart_bytes:
                    # Send photo with caption
                    photo = InputFile.from_buffer(chart_bytes, filename="result.png")
                    response = await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=photo,
                        caption=text,
                        parse_mode="Markdown",
                        reply_to_message_id=reply_to_message_id
                    )
                    message_id = response.message_id
                else:
                    # Send text only (fallback)
                    text_with_note = text + "_⚠️ Chart generation failed_"
                    response = await self.bot.send_message(
                        chat_id=self.chat_id,
                        text=text_with_note,
                        parse_mode="Markdown",
                        reply_to_message_id=reply_to_message_id
                    )
                    message_id = response.message_id

                logger.info(f"Result notification sent for {symbol}, outcome: {outcome}, message_id: {message_id}")
                return message_id

            except TelegramRetryAfter as e:
                wait_time = e.retry_after
                logger.warning(f"Rate limited by Telegram, waiting {wait_time}s")
                await asyncio.sleep(wait_time)
                
            except TelegramAPIError as e:
                logger.error(f"Telegram API error (attempt {attempt + 1}): {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(1 * (attempt + 1))
                    
            except Exception as e:
                logger.error(f"Unexpected error sending result: {e}")
                if attempt < self.retry_count - 1:
                    await asyncio.sleep(1)

        return None

    async def send_stats_image(
        self,
        wins: int,
        losses: int,
        total: int,
        winrate: float,
        avg_pnl: float = 0.0
    ) -> bool:
        """
        Send statistics as image only (no text).
        
        Args:
            wins: Number of winning trades
            losses: Number of losing trades
            total: Total number of signals
            winrate: Win rate percentage
            avg_pnl: Average PnL percentage
            
        Returns:
            True if sent successfully, False otherwise
        """
        if not self._initialized:
            await self.initialize()
            
        if not self._initialized:
            return False

        # Generate stats image using matplotlib
        try:
            import matplotlib
            matplotlib.use('Agg')
            import matplotlib.pyplot as plt
            import io

            fig, ax = plt.subplots(figsize=(8, 6))
            fig.patch.set_facecolor('#1a1a2e')
            ax.set_facecolor('#16213e')

            # Create pie chart
            if wins + losses > 0:
                sizes = [wins, losses]
                labels = [f'Wins: {wins}', f'Losses: {losses}']
                colors = ['#2ecc71', '#e74c3c']
                
                wedges, texts = ax.pie(
                    sizes,
                    labels=labels,
                    colors=colors,
                    startangle=90,
                    autopct='%1.1f%%',
                    pctdistance=0.6
                )
                
                for text in texts:
                    text.set_color('white')
                    text.set_fontsize(10)

                # Center circle for donut effect
                centre_circle = plt.Circle((0, 0), 0.5, fc='#1a1a2e')
                ax.add_artist(centre_circle)

            # Add stats text in center
            closed_trades = wins + losses
            stats_text = (
                f'Total: {total}\n'
                f'Closed: {closed_trades}\n'
                f'Win Rate: {winrate:.1f}%\n'
                f'Avg PnL: {avg_pnl:+.2f}%'
            )
            
            ax.text(
                0, 0, stats_text,
                ha='center', va='center',
                fontsize=12, fontweight='bold',
                color='white'
            )

            ax.set_title('Trading Statistics', color='white', fontsize=14, fontweight='bold')

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

            # Send image
            for attempt in range(self.retry_count):
                try:
                    photo = InputFile.from_buffer(buf.getvalue(), filename="stats.png")
                    await self.bot.send_photo(
                        chat_id=self.chat_id,
                        photo=photo
                    )
                    logger.info("Statistics image sent successfully")
                    return True
                    
                except TelegramRetryAfter as e:
                    wait_time = e.retry_after
                    logger.warning(f"Rate limited, waiting {wait_time}s")
                    await asyncio.sleep(wait_time)
                    
                except Exception as e:
                    logger.error(f"Error sending stats (attempt {attempt + 1}): {e}")
                    if attempt < self.retry_count - 1:
                        await asyncio.sleep(1)

            return False

        except Exception as e:
            logger.error(f"Failed to generate/send stats image: {e}")
            return False

    async def send_text_message(
        self,
        text: str,
        parse_mode: str = "Markdown"
    ) -> bool:
        """Send a simple text message"""
        if not self._initialized:
            await self.initialize()
            
        if not self._initialized:
            return False

        try:
            await self.bot.send_message(
                chat_id=self.chat_id,
                text=text,
                parse_mode=parse_mode
            )
            return True
        except Exception as e:
            logger.error(f"Failed to send text message: {e}")
            return False


# Global notifier instance
notifier = TelegramNotifier()
