"""
Exchange module with async CCXT client for MEXC futures.
Handles rate limiting, retries, and data fetching.
"""

import asyncio
from datetime import datetime
from typing import List, Optional

import ccxt.async_support as ccxt
import pandas as pd

from config import config


class ExchangeClient:
    """Async MEXC exchange client with rate limiting and retry logic"""

    def __init__(self):
        self.exchange: Optional[ccxt.mexc] = None
        self._semaphore = asyncio.Semaphore(config.exchange.max_concurrent_requests)
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize the exchange connection"""
        if self._initialized:
            return

        self.exchange = ccxt.mexc({
            'enableRateLimit': config.exchange.enable_rate_limit,
            'rateLimit': config.exchange.rate_limit_ms,
            'options': {
                'defaultType': 'future',  # Use futures by default
            }
        })

        if config.exchange.api_key and config.exchange.api_secret:
            self.exchange.apiKey = config.exchange.api_key
            self.exchange.secret = config.exchange.api_secret

        self._initialized = True

    async def close(self) -> None:
        """Close the exchange connection"""
        if self.exchange:
            await self.exchange.close()
            self._initialized = False

    async def fetch_ohlcv_safe(
        self,
        symbol: str,
        timeframe: str = None,
        limit: int = None,
        since: Optional[int] = None,
        retries: int = None
    ) -> pd.DataFrame:
        """
        Safely fetch OHLCV data with retry logic.
        
        Args:
            symbol: Trading pair symbol (e.g., 'BTC/USDT:USDT')
            timeframe: Candle timeframe (e.g., '15m')
            limit: Number of candles to fetch
            since: Timestamp in milliseconds to fetch from
            retries: Number of retry attempts
            
        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        timeframe = timeframe or config.exchange.default_timeframe
        limit = limit or config.exchange.candles_limit
        retries = retries or config.exchange.fetch_retries

        if not self._initialized:
            await self.initialize()

        async with self._semaphore:
            for attempt in range(retries):
                try:
                    # Fetch OHLCV data
                    ohlcv = await self.exchange.fetch_ohlcv(
                        symbol=symbol,
                        timeframe=timeframe,
                        limit=limit,
                        since=since
                    )

                    if not ohlcv:
                        return pd.DataFrame()

                    # Convert to DataFrame
                    df = pd.DataFrame(
                        ohlcv,
                        columns=['timestamp', 'open', 'high', 'low', 'close', 'volume']
                    )

                    # Convert timestamp to datetime
                    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                    
                    # Ensure numeric types
                    for col in ['open', 'high', 'low', 'close', 'volume']:
                        df[col] = pd.to_numeric(df[col], errors='coerce')

                    # Drop any rows with NaN values
                    df = df.dropna()

                    return df

                except ccxt.DDoSProtection as e:
                    # Rate limit hit, wait and retry
                    wait_time = (2 ** attempt) * 0.5  # Exponential backoff
                    await asyncio.sleep(wait_time)
                    
                except ccxt.ExchangeError as e:
                    error_msg = str(e)
                    if '510' in error_msg:
                        # MEXC specific rate limit error
                        wait_time = (2 ** attempt) * 1.0
                        await asyncio.sleep(wait_time)
                    else:
                        raise
                        
                except Exception as e:
                    if attempt == retries - 1:
                        raise
                    wait_time = (2 ** attempt) * 0.3
                    await asyncio.sleep(wait_time)

            return pd.DataFrame()

    async def get_futures_symbols(self, quote_currency: str = "USDT") -> List[str]:
        """
        Get list of active futures symbols.
        
        Args:
            quote_currency: Quote currency to filter (e.g., 'USDT')
            
        Returns:
            List of symbol strings
        """
        if not self._initialized:
            await self.initialize()

        try:
            markets = await self.exchange.load_markets()
            
            # Filter for active futures with specified quote currency
            symbols = []
            for symbol, market in markets.items():
                if (market.get('type') == 'future' and 
                    market.get('quote') == quote_currency and
                    market.get('active', False) and
                    market.get('linear', False)):  # Linear USDT-margined futures
                    symbols.append(symbol)
            
            return sorted(symbols)
            
        except Exception as e:
            # Fallback: try to get symbols from active tickers
            try:
                tickers = await self.exchange.fetch_tickers()
                symbols = [
                    sym for sym in tickers.keys()
                    if quote_currency in sym and ':' in sym
                ]
                return sorted(symbols)
            except:
                return []

    async def get_current_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        if not self._initialized:
            await self.initialize()

        try:
            ticker = await self.exchange.fetch_ticker(symbol)
            return ticker.get('last')
        except:
            return None


# Global exchange instance
exchange = ExchangeClient()
