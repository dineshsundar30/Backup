import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import talib
import sqlite3
from datetime import datetime
import logging
import time
from sklearn.ensemble import IsolationForest
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk
import threading

class TradeDatabase:
    def __init__(self, db_path="trading_history.db"):
        self.db_path = db_path
        self.setup_database()

    def setup_database(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    entry_time TIMESTAMP,
                    exit_time TIMESTAMP,
                    entry_price REAL,
                    exit_price REAL,
                    trade_type TEXT,
                    profit_loss REAL,
                    lot_size REAL,
                    supertrend_value REAL,
                    macd_value REAL,
                    signal_value REAL,
                    status TEXT
                )
            ''')
            
            conn.execute('''
                CREATE TABLE IF NOT EXISTS failed_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    pattern_data TEXT,
                    failure_count INTEGER,
                    last_seen TIMESTAMP
                )
            ''')

    def log_trade(self, trade_data):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                INSERT INTO trades (
                    symbol, entry_time, entry_price, trade_type, 
                    lot_size, supertrend_value, macd_value, signal_value, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                trade_data['symbol'],
                trade_data['entry_time'],
                trade_data['entry_price'],
                trade_data['trade_type'],
                trade_data['lot_size'],
                trade_data['supertrend_value'],
                trade_data['macd_value'],
                trade_data['signal_value'],
                'OPEN'
            ))

    def update_trade(self, trade_id, exit_price, profit_loss):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                UPDATE trades 
                SET exit_price = ?, exit_time = ?, profit_loss = ?, status = ?
                WHERE id = ?
            ''', (exit_price, datetime.now(), profit_loss, 'CLOSED', trade_id))

    def get_failed_patterns(self):
        with sqlite3.connect(self.db_path) as conn:
            return pd.read_sql('SELECT * FROM failed_patterns', conn)

class SupertrendCalculator:
    def __init__(self, period=10, multiplier=3):
        self.period = period
        self.multiplier = multiplier

    def calculate(self, df):
        high = df['high']
        low = df['low']
        close = df['close']

        # Calculate ATR
        tr1 = pd.DataFrame(high - low)
        tr2 = pd.DataFrame(abs(high - close.shift(1)))
        tr3 = pd.DataFrame(abs(low - close.shift(1)))
        frames = [tr1, tr2, tr3]
        tr = pd.concat(frames, axis=1, join='inner').max(axis=1)
        atr = tr.rolling(self.period).mean()

        # Calculate SuperTrend
        hl2 = (high + low) / 2
        upperband = hl2 + (self.multiplier * atr)
        lowerband = hl2 - (self.multiplier * atr)
        
        supertrend = pd.Series(0.0, index=df.index)
        direction = pd.Series(1, index=df.index)
        
        for i in range(1, len(df.index)):
            if close[i] > upperband[i-1]:
                direction[i] = 1
            elif close[i] < lowerband[i-1]:
                direction[i] = -1
            else:
                direction[i] = direction[i-1]
                if direction[i] > 0 and lowerband[i] < lowerband[i-1]:
                    lowerband[i] = lowerband[i-1]
                if direction[i] < 0 and upperband[i] > upperband[i-1]:
                    upperband[i] = upperband[i-1]
            
            if direction[i] > 0:
                supertrend[i] = lowerband[i]
            else:
                supertrend[i] = upperband[i]
        
        return supertrend, direction

class MT5TradingBot:
    def __init__(self, symbol='EURUSD', timeframe=mt5.TIMEFRAME_M5, interval=300):
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval = interval
        self.logger = self._setup_logging()
        self.min_balance = 10
        self.fixed_lot = 0.01
        self.db = TradeDatabase()
        self.supertrend = SupertrendCalculator()
        self.anomaly_detector = IsolationForest(contamination=0.1, random_state=42)
        
        if not mt5.initialize():
            error = mt5.last_error()
            self.logger.error(f"MT5 Initialization Error: {error}")
            raise Exception(f"MT5 Connection Failed: {error}")

    def _setup_logging(self):
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(levelname)s: %(message)s',
            handlers=[
                logging.FileHandler('trading_bot.log'),
                logging.StreamHandler()
            ]
        )
        return logging.getLogger(__name__)

    def calculate_indicators(self, df):
        df = df.copy()
        
        # Calculate Supertrend
        df['supertrend'], df['supertrend_direction'] = self.supertrend.calculate(df)
        
        # Calculate MACD
        df['macd'], df['macdsignal'], df['macdhist'] = talib.MACD(
            df['close'], fastperiod=12, slowperiod=26, signalperiod=9
        )
        
        return df

    def check_trading_signal(self, df):
        last_row = df.iloc[-1]
        
        # Get previous failed patterns
        failed_patterns = self.db.get_failed_patterns()
        
        # Create current pattern signature
        current_pattern = {
            'supertrend_direction': last_row['supertrend_direction'],
            'macd_cross': 1 if last_row['macd'] > last_row['macdsignal'] else -1,
            'price_level': last_row['close']
        }
        
        # Check if pattern is in failed patterns
        pattern_str = json.dumps(current_pattern)
        if any(failed_patterns['pattern_data'].str.contains(pattern_str)):
            return 0, None
        
        # Trading logic
        if (last_row['supertrend_direction'] == 1 and 
            last_row['macd'] > last_row['macdsignal'] and 
            last_row['macdhist'] > 0):
            return 1, current_pattern  # Buy signal
            
        elif (last_row['supertrend_direction'] == -1 and 
              last_row['macd'] < last_row['macdsignal'] and 
              last_row['macdhist'] < 0):
            return -1, current_pattern  # Sell signal
            
        return 0, None  # No signal

    def execute_trade(self, signal, pattern):
        try:
            if not self.check_account_viability():
                return None

            positions = mt5.positions_get(symbol=self.symbol)
            if positions:
                self.logger.info(f"Active trade exists for {self.symbol}")
                return None

            if signal == 1:  # Buy
                trade_type = mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(self.symbol).ask
            else:  # Sell
                trade_type = mt5.ORDER_TYPE_SELL
                price = mt5.symbol_info_tick(self.symbol).bid

            # Calculate dynamic SL and TP based on ATR or fixed pips
            sl_points = 100  # Adjust based on your risk management
            tp_points = sl_points * 2  # Risk:Reward ratio of 1:2

            point = mt5.symbol_info(self.symbol).point
            
            if trade_type == mt5.ORDER_TYPE_BUY:
                sl = price - sl_points * point
                tp = price + tp_points * point
            else:
                sl = price + sl_points * point
                tp = price - tp_points * point

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": self.fixed_lot,
                "type": trade_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": 234000,
                "comment": "SuperTrend-MACD Trade",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

            result = mt5.order_send(request)
            
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                self.logger.info(f"Trade executed: {self.fixed_lot} lots at {price}")
                # Log trade to database
                trade_data = {
                    'symbol': self.symbol,
                    'entry_time': datetime.now(),
                    'entry_price': price,
                    'trade_type': 'BUY' if trade_type == mt5.ORDER_TYPE_BUY else 'SELL',
                    'lot_size': self.fixed_lot,
                    'supertrend_value': pattern['supertrend_direction'],
                    'macd_value': pattern['macd_cross'],
                    'signal_value': signal
                }
                self.db.log_trade(trade_data)
            else:
                self.logger.error(f"Trade failed: {result.comment}")
                # Log failed pattern
                self.log_failed_pattern(pattern)

        except Exception as e:
            self.logger.error(f"Trade execution error: {e}")

    def log_failed_pattern(self, pattern):
        with sqlite3.connect(self.db.db_path) as conn:
            pattern_str = json.dumps(pattern)
            conn.execute('''
                INSERT INTO failed_patterns (pattern_data, failure_count, last_seen)
                VALUES (?, 1, ?) 
                ON CONFLICT(pattern_data) 
                DO UPDATE SET failure_count = failure_count + 1, last_seen = ?
            ''', (pattern_str, datetime.now(), datetime.now()))

    def check_account_viability(self):
        account_info = mt5.account_info()
        if account_info is None:
            self.logger.error("Cannot retrieve account information")
            return False
        return account_info.balance >= self.min_balance

    def run_trading_cycle(self):
        while True:
            try:
                # Fetch latest data
                rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, 1000)
                if rates is None:
                    self.logger.error("Failed to fetch rates")
                    time.sleep(self.interval)
                    continue

                df = pd.DataFrame(rates)
                df = self.calculate_indicators(df)

                # Generate trading signal
                signal, pattern = self.check_trading_signal(df)
                
                if signal != 0:
                    self.execute_trade(signal, pattern)

                time.sleep(self.interval)

            except Exception as e:
                self.logger.error(f"Trading cycle error: {e}")
                time.sleep(self.interval)

class TradingBotGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("MT5 Trading Bot")
        self.bot = None
        self.setup_gui()

    def setup_gui(self):
        # Symbol selection
        ttk.Label(self.root, text="Symbol:").grid(row=0, column=0, padx=5, pady=5)
        self.symbol_var = tk.StringVar(value="EURUSD")
        self.symbol_entry = ttk.Entry(self.root, textvariable=self.symbol_var)
        self.symbol_entry.grid(row=0, column=1, padx=5, pady=5)

        # Start/Stop button
        self.start_button = ttk.Button(self.root, text="Start Trading", command=self.toggle_trading)
        self.start_button.grid(row=1, column=0, columnspan=2, pady=10)

        # Status display
        self.status_var = tk.StringVar(value="Status: Stopped")
        ttk.Label(self.root, textvariable=self.status_var).grid(row=2, column=0, columnspan=2)

    def toggle_trading(self):
        if self.bot is None:
            # Start trading
            self.bot = MT5TradingBot(symbol=self.symbol_var.get())
            self.trading_thread = threading.Thread(target=self.bot.run_trading_cycle)
            self.trading_thread.daemon = True
            self.trading_thread.start()
            self.start_button.config(text="Stop Trading")
            self.status_var.set("Status: Running")
        else:
            # Stop trading
            self.bot = None
            self.start_button.config(text="Start Trading")
            self.status_var.set("Status: Stopped")

def main():
    root = tk.Tk()
    app = TradingBotGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()
