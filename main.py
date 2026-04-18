"""
Main orchestrator for MEXC Futures Stackable Consolidations Scanner.
Event-driven async bot with graceful shutdown.
"""

import asyncio
import logging
import signal
import sys
from datetime import datetime
from typing import Dict, List, Optional, Set

import pandas as pd

from config import config
from database import db, SignalStatus
from exchange import exchange
from pattern_engine import pattern_engine, StackablePattern
from result_tracker import result_tracker
from chart_generator import chart_generator
from telegram_bot import notifier


# Configure logging
logging.basicConfig(
    level=getattr(logging, config.bot.log_level),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(config.bot.log_file, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)


class TradingBot:
    """Main trading bot orchestrator"""

    def __init__(self):
        self._shutdown_event = asyncio.Event()
        self._symbols_cache: List[str] = []
        self._last_closed_count: int = 0
        self._processed_symbols: Set[str] = set()
        self._scan_interval = config.bot.scan_interval_minutes * 60

    async def initialize(self) -> None:
        """Initialize all components"""
        logger.info("Initializing trading bot...")
        
        # Initialize database
        await db.initialize()
        logger.info("Database initialized")
        
        # Initialize exchange
        await exchange.initialize()
        logger.info("Exchange client initialized")
        
        # Initialize Telegram notifier
        await notifier.initialize()
        logger.info("Telegram notifier initialized")
        
        # Load symbols cache
        await self._refresh_symbols()
        logger.info(f"Loaded {len(self._symbols_cache)} futures symbols")
        
        # Get initial closed count
        self._last_closed_count = await db.get_closed_count()
        
        logger.info("Bot initialization complete")

    async def shutdown(self) -> None:
        """Graceful shutdown of all components"""
        logger.info("Shutting down bot...")
        
        self._shutdown_event.set()
        
        # Close chart generator
        chart_generator.close()
        
        # Close exchange
        await exchange.close()
        
        # Close Telegram bot
        await notifier.close()
        
        logger.info("Bot shutdown complete")

    async def _refresh_symbols(self) -> None:
        """Refresh the list of available futures symbols"""
        try:
            symbols = await exchange.get_futures_symbols(
                quote_currency=config.bot.quote_currency
            )
            if symbols:
                self._symbols_cache = symbols
                logger.debug(f"Symbols cache refreshed: {len(symbols)} symbols")
        except Exception as e:
            logger.error(f"Failed to refresh symbols: {e}")

    async def _fetch_candles(self, symbol: str) -> Optional[pd.DataFrame]:
        """Fetch candles for a symbol with error handling"""
        try:
            df = await exchange.fetch_ohlcv_safe(
                symbol=symbol,
                timeframe=config.exchange.default_timeframe,
                limit=config.exchange.candles_limit
            )
            
            if df.empty:
                logger.debug(f"No data for {symbol}")
                return None
                
            return df
            
        except Exception as e:
            logger.error(f"Error fetching candles for {symbol}: {e}")
            return None

    async def _check_pending_signals(
        self,
        symbol: str,
        df: pd.DataFrame
    ) -> bool:
        """
        Check pending signals for a symbol.
        
        Returns:
            True if signal was closed, False otherwise
        """
        signal_data = await db.get_pending_by_symbol(symbol)
        
        if not signal_data:
            return False

        # Check outcome
        outcome, exit_price, exit_time = result_tracker.check_signal_outcome(df, signal_data)
        
        if outcome is None:
            # Still pending
            return False

        # Calculate PnL
        pnl = result_tracker.calculate_pnl(
            signal_data['entry_price'],
            exit_price,
            outcome
        )

        logger.info(
            f"Signal closed for {symbol}: {outcome}, "
            f"PnL: {pnl:.2f}%, Exit: {exit_price:.5f}"
        )

        # Update database
        await db.update_status(
            signal_id=signal_data['id'],
            status=outcome,
            exit_price=exit_price,
            exit_time=exit_time,
            pnl=pnl
        )

        # Generate result chart (async, non-blocking)
        chart_bytes = None
        try:
            chart_bytes = await chart_generator.generate_result_chart(
                df=df,
                signal=signal_data,
                outcome=outcome,
                exit_price=exit_price
            )
        except Exception as e:
            logger.error(f"Chart generation failed for result: {e}")

        # Send notification
        reply_to_msg_id = signal_data.get('telegram_message_id')
        
        await notifier.send_result(
            signal_id=signal_data['id'],
            symbol=symbol,
            outcome=outcome,
            entry_price=signal_data['entry_price'],
            exit_price=exit_price,
            pnl=pnl,
            chart_bytes=chart_bytes,
            reply_to_message_id=reply_to_msg_id
        )

        return True

    async def _detect_pattern(
        self,
        symbol: str,
        df: pd.DataFrame
    ) -> Optional[StackablePattern]:
        """Detect pattern and create signal if valid"""
        if symbol in self._processed_symbols:
            return None

        # Detect pattern
        pattern = pattern_engine.detect_pattern(df)
        
        if not pattern:
            return None

        # Validate entry window
        if not pattern_engine.validate_entry_window(df, pattern):
            logger.debug(f"Pattern entry window expired for {symbol}")
            return None

        # Check if price has already triggered
        current_price = df['close'].iloc[-1]
        
        if pattern.direction == 'LONG':
            if current_price >= pattern.entry_price:
                logger.info(f"{symbol}: Entry already triggered, skipping")
                return None
        else:  # SHORT
            if current_price <= pattern.entry_price:
                logger.info(f"{symbol}: Entry already triggered, skipping")
                return None

        logger.info(
            f"Pattern detected for {symbol}: {pattern.direction}, "
            f"Entry: {pattern.entry_price:.5f}"
        )

        return pattern

    async def _create_signal(
        self,
        symbol: str,
        pattern: StackablePattern,
        df: pd.DataFrame
    ) -> None:
        """Create and save signal, send notification"""
        # Save to database
        signal_id = await db.save_signal(
            symbol=symbol,
            entry_price=pattern.entry_price,
            tp_price=pattern.tp_price,
            sl_price=pattern.sl_price,
            steps=2,  # Stackable = 2 consolidations
            timeframe=config.exchange.default_timeframe,
            entry_time=pattern.time_end.isoformat(),
            pattern_data=None
        )

        logger.info(f"Signal saved: ID={signal_id}, Symbol={symbol}")

        # Generate chart
        chart_bytes = None
        try:
            chart_bytes = await chart_generator.generate_signal_chart(
                df=df,
                pattern=pattern,
                symbol=symbol
            )
        except Exception as e:
            logger.error(f"Chart generation failed: {e}")

        # Send notification
        message_id = await notifier.send_signal(
            symbol=symbol,
            steps=2,
            price=pattern.entry_price,
            direction=pattern.direction,
            tp=pattern.tp_price,
            sl=pattern.sl_price,
            chart_bytes=chart_bytes
        )

        # Update database with message ID
        if message_id:
            await db.set_telegram_message_id(signal_id, message_id)

        # Mark symbol as processed to avoid duplicate signals
        self._processed_symbols.add(symbol)

    async def _maybe_send_stats(self) -> None:
        """Send statistics if closed count changed"""
        current_closed = await db.get_closed_count()
        
        if current_closed != self._last_closed_count:
            stats = await db.get_stats()
            
            logger.info(
                f"Stats update: Total={stats['total']}, "
                f"Wins={stats['wins']}, Losses={stats['losses']}, "
                f"Winrate={stats['winrate']:.1f}%"
            )
            
            # Send stats image only
            await notifier.send_stats_image(
                wins=stats['wins'],
                losses=stats['losses'],
                total=stats['total'],
                winrate=stats['winrate'],
                avg_pnl=stats['avg_pnl']
            )
            
            self._last_closed_count = current_closed

    async def _scan_cycle(self) -> None:
        """Execute one complete scan cycle"""
        logger.debug("Starting scan cycle...")
        
        # Refresh symbols periodically
        if len(self._symbols_cache) == 0:
            await self._refresh_symbols()

        # Process symbols with concurrency limit
        semaphore = asyncio.Semaphore(config.exchange.max_concurrent_requests)
        
        async def process_symbol(symbol: str) -> None:
            async with semaphore:
                try:
                    # Fetch candles
                    df = await self._fetch_candles(symbol)
                    
                    if df is None or df.empty:
                        return

                    # First check pending signals (priority)
                    signal_closed = await self._check_pending_signals(symbol, df)
                    
                    if signal_closed:
                        logger.debug(f"Signal closed for {symbol}")
                        return

                    # If no pending signal, check for patterns
                    pattern = await self._detect_pattern(symbol, df)
                    
                    if pattern:
                        await self._create_signal(symbol, pattern, df)
                        
                except Exception as e:
                    logger.error(f"Error processing {symbol}: {e}")

        # Create tasks for all symbols
        tasks = [process_symbol(symbol) for symbol in self._symbols_cache]
        
        # Execute with controlled concurrency
        await asyncio.gather(*tasks, return_exceptions=True)
        
        # Check if we should send stats
        await self._maybe_send_stats()
        
        logger.debug("Scan cycle complete")

    async def run(self) -> None:
        """Main bot loop"""
        try:
            await self.initialize()
            
            logger.info("Bot started, beginning scan cycles...")
            
            while not self._shutdown_event.is_set():
                try:
                    start_time = datetime.utcnow()
                    
                    # Execute scan cycle
                    await self._scan_cycle()
                    
                    # Calculate sleep time
                    elapsed = (datetime.utcnow() - start_time).total_seconds()
                    sleep_time = max(0, self._scan_interval - elapsed)
                    
                    if sleep_time > 0:
                        logger.debug(f"Sleeping for {sleep_time:.1f}s")
                        await asyncio.sleep(sleep_time)
                        
                except asyncio.CancelledError:
                    logger.info("Scan cycle cancelled")
                    break
                    
                except Exception as e:
                    logger.error(f"Error in scan cycle: {e}")
                    await asyncio.sleep(5)  # Brief pause on error
                    
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received")
        except Exception as e:
            logger.error(f"Fatal error: {e}")
        finally:
            await self.shutdown()


async def main():
    """Entry point"""
    bot = TradingBot()
    
    # Setup signal handlers for graceful shutdown
    loop = asyncio.get_event_loop()
    
    def signal_handler():
        logger.info("Shutdown signal received")
        asyncio.create_task(bot.shutdown())
    
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, signal_handler)
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass
    
    # Run the bot
    await bot.run()


if __name__ == "__main__":
    asyncio.run(main())
