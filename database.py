"""
Database module with SQLite WAL mode and connection pooling.
Provides thread-safe access to signals storage.
"""

import asyncio
import sqlite3
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import aiosqlite

from config import config


class SignalStatus:
    """Signal status constants"""
    PENDING = "PENDING"
    WIN = "WIN"
    LOSE = "LOSE"


class Database:
    """Async SQLite database manager with WAL mode"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or config.database.db_path
        self._lock = asyncio.Lock()
        self._initialized = False

    async def initialize(self) -> None:
        """Initialize database with WAL mode and create tables"""
        async with aiosqlite.connect(self.db_path) as db:
            # Enable WAL mode for better concurrent performance
            if config.database.wal_mode:
                await db.execute("PRAGMA journal_mode=WAL")
            
            # Use NORMAL synchronous for balance between safety and speed
            if config.database.synchronous_normal:
                await db.execute("PRAGMA synchronous=NORMAL")
            
            # Enable foreign keys
            await db.execute("PRAGMA foreign_keys=ON")
            
            # Create signals table
            await db.execute("""
                CREATE TABLE IF NOT EXISTS signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL,
                    entry_price REAL NOT NULL,
                    tp_price REAL NOT NULL,
                    sl_price REAL NOT NULL,
                    steps INTEGER NOT NULL DEFAULT 1,
                    timeframe TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    telegram_message_id INTEGER,
                    entry_time TEXT NOT NULL,
                    exit_time TEXT,
                    exit_price REAL,
                    pnl REAL,
                    pattern_data TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Create index for efficient pending signal lookup
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_status_symbol 
                ON signals(status, symbol)
            """)
            
            # Create index for time-based queries
            await db.execute("""
                CREATE INDEX IF NOT EXISTS idx_signals_entry_time 
                ON signals(entry_time)
            """)
            
            await db.commit()
        
        self._initialized = True

    @asynccontextmanager
    async def get_connection(self):
        """Get database connection with proper settings"""
        if not self._initialized:
            await self.initialize()
        
        conn = await aiosqlite.connect(self.db_path)
        try:
            if config.database.wal_mode:
                await conn.execute("PRAGMA journal_mode=WAL")
            if config.database.synchronous_normal:
                await conn.execute("PRAGMA synchronous=NORMAL")
            yield conn
        finally:
            await conn.close()

    async def save_signal(
        self,
        symbol: str,
        entry_price: float,
        tp_price: float,
        sl_price: float,
        steps: int,
        timeframe: str,
        entry_time: str,
        pattern_data: Optional[str] = None
    ) -> int:
        """Save a new signal to the database"""
        now = datetime.utcnow().isoformat()
        
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                INSERT INTO signals (
                    symbol, entry_price, tp_price, sl_price, steps,
                    timeframe, status, entry_time, pattern_data,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                symbol, entry_price, tp_price, sl_price, steps,
                timeframe, SignalStatus.PENDING, entry_time, pattern_data,
                now, now
            ))
            await conn.commit()
            return cursor.lastrowid

    async def get_pending_by_symbol(self, symbol: str) -> Optional[Dict[str, Any]]:
        """Get pending signal for a specific symbol"""
        async with self.get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM signals 
                WHERE symbol = ? AND status = ?
                ORDER BY entry_time DESC
                LIMIT 1
            """, (symbol, SignalStatus.PENDING))
            
            row = await cursor.fetchone()
            if row:
                return dict(row)
            return None

    async def get_all_pending(self) -> List[Dict[str, Any]]:
        """Get all pending signals"""
        async with self.get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM signals 
                WHERE status = ?
                ORDER BY entry_time ASC
            """, (SignalStatus.PENDING,))
            
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

    async def update_status(
        self,
        signal_id: int,
        status: str,
        exit_price: Optional[float] = None,
        exit_time: Optional[str] = None,
        pnl: Optional[float] = None,
        telegram_message_id: Optional[int] = None
    ) -> None:
        """Update signal status and exit information"""
        now = datetime.utcnow().isoformat()
        
        async with self.get_connection() as conn:
            await conn.execute("""
                UPDATE signals 
                SET status = ?, exit_price = ?, exit_time = ?, 
                    pnl = ?, telegram_message_id = ?, updated_at = ?
                WHERE id = ?
            """, (status, exit_price, exit_time, pnl, telegram_message_id, now, signal_id))
            await conn.commit()

    async def set_telegram_message_id(
        self,
        signal_id: int,
        telegram_message_id: int
    ) -> None:
        """Set Telegram message ID for a signal"""
        async with self.get_connection() as conn:
            await conn.execute("""
                UPDATE signals 
                SET telegram_message_id = ?, updated_at = ?
                WHERE id = ?
            """, (telegram_message_id, datetime.utcnow().isoformat(), signal_id))
            await conn.commit()

    async def get_stats(self) -> Dict[str, Any]:
        """Get trading statistics"""
        async with self.get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            
            # Total signals
            cursor = await conn.execute("""
                SELECT COUNT(*) as total FROM signals
            """)
            total_row = await cursor.fetchone()
            total = total_row["total"] if total_row else 0
            
            # Wins
            cursor = await conn.execute("""
                SELECT COUNT(*) as wins FROM signals WHERE status = ?
            """, (SignalStatus.WIN,))
            wins_row = await cursor.fetchone()
            wins = wins_row["wins"] if wins_row else 0
            
            # Losses
            cursor = await conn.execute("""
                SELECT COUNT(*) as losses FROM signals WHERE status = ?
            """, (SignalStatus.LOSE,))
            losses_row = await cursor.fetchone()
            losses = losses_row["losses"] if losses_row else 0
            
            # Pending
            pending = total - wins - losses
            
            # Win rate
            winrate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0
            
            # Average PnL
            cursor = await conn.execute("""
                SELECT AVG(pnl) as avg_pnl FROM signals 
                WHERE status IN (?, ?)
            """, (SignalStatus.WIN, SignalStatus.LOSE))
            avg_row = await cursor.fetchone()
            avg_pnl = avg_row["avg_pnl"] if avg_row and avg_row["avg_pnl"] else 0.0
            
            return {
                "total": total,
                "wins": wins,
                "losses": losses,
                "pending": pending,
                "winrate": winrate,
                "avg_pnl": avg_pnl or 0.0
            }

    async def get_closed_count(self) -> int:
        """Get count of closed signals (WIN + LOSE)"""
        async with self.get_connection() as conn:
            cursor = await conn.execute("""
                SELECT COUNT(*) as count FROM signals 
                WHERE status IN (?, ?)
            """, (SignalStatus.WIN, SignalStatus.LOSE))
            row = await cursor.fetchone()
            return row[0] if row else 0

    async def get_recent_closed(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recently closed signals"""
        async with self.get_connection() as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("""
                SELECT * FROM signals 
                WHERE status IN (?, ?)
                ORDER BY exit_time DESC
                LIMIT ?
            """, (SignalStatus.WIN, SignalStatus.LOSE, limit))
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]


# Global database instance
db = Database()
