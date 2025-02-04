import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import talib
import time
from datetime import datetime, timezone
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_log.txt'),
        logging.StreamHandler()
    ]
)

class TradingSystem:
    def __init__(self):
        # Main settings
        self.symbol = "EURUSDm"
        self.magic = 12345678
        self.lot_size = 0.01  # Fixed lot size
        
        # Technical parameters
        self.atr_period = 14
        self.atr_multiplier = 2
        self.ema_fast = 20
        self.ema_slow = 50
        
        # Timeframes to analyze
        self.timeframes = {
            'fast': mt5.TIMEFRAME_H1,
            'medium': mt5.TIMEFRAME_H4,
            'slow': mt5.TIMEFRAME_D1
        }
        
        # Trading hours (GMT)
        self.trading_hours = {
            'asian': (0, 8),
            'london': (8, 16),
            'ny': (13, 21)
        }
        
        # Initialize MT5
        if not self.initialize_mt5():
            raise Exception("Failed to initialize MT5")
            
    def initialize_mt5(self):
        """Initialize MT5 connection"""
        if not mt5.initialize():
            logging.error(f"MT5 initialization failed: {mt5.last_error()}")
            return False
            
        if not mt5.symbol_select(self.symbol):
            logging.error(f"Symbol selection failed: {mt5.last_error()}")
            return False
            
        return True
        
    def get_market_data(self, timeframe, bars=100):
        """Get market data for analysis"""
        rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, bars)
        if rates is None:
            raise Exception("Failed to get market data")
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        return df
        
    def calculate_indicators(self, df):
        """Calculate technical indicators"""
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=self.atr_period)
        df['ema_fast'] = talib.EMA(df['close'], timeperiod=self.ema_fast)
        df['ema_slow'] = talib.EMA(df['close'], timeperiod=self.ema_slow)
        df['rsi'] = talib.RSI(df['close'], timeperiod=14)
        return df
        
    def is_trading_hour(self):
        """Check if current time is within trading hours"""
        current_hour = datetime.now(timezone.utc).hour
        
        for session_hours in self.trading_hours.values():
            if session_hours[0] <= current_hour < session_hours[1]:
                return True
        return False
        
    def check_trend_alignment(self):
        """Check trend alignment across timeframes"""
        trends = []
        
        for timeframe in self.timeframes.values():
            df = self.get_market_data(timeframe, 100)
            df = self.calculate_indicators(df)
            
            # Trend is up if fast EMA > slow EMA
            trend = 1 if df['ema_fast'].iloc[-1] > df['ema_slow'].iloc[-1] else -1
            trends.append(trend)
            
        # Return True if all trends align
        return all(t == trends[0] for t in trends)
        
    def calculate_entry_exit_points(self, trend):
        """Calculate entry, stop loss, and take profit levels"""
        df = self.get_market_data(self.timeframes['fast'], 100)
        df = self.calculate_indicators(df)
        
        current_atr = df['atr'].iloc[-1]
        
        if trend == 1:  # Uptrend
            entry = mt5.symbol_info_tick(self.symbol).ask
            stop_loss = entry - (current_atr * self.atr_multiplier)
            take_profit = entry + (current_atr * self.atr_multiplier * 1.5)
        else:  # Downtrend
            entry = mt5.symbol_info_tick(self.symbol).bid
            stop_loss = entry + (current_atr * self.atr_multiplier)
            take_profit = entry - (current_atr * self.atr_multiplier * 1.5)
            
        return entry, stop_loss, take_profit
        
    def place_order(self, order_type, price, sl, tp):
        """Place trading order with fixed lot size"""
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot_size,  # Using fixed lot size
            "type": order_type,
            "price": price,
            "sl": sl,
            "tp": tp,
            "deviation": 20,
            "magic": self.magic,
            "comment": f"python_trader_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }
        
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"Order failed: {result.comment}")
            return False
            
        logging.info(f"Order placed successfully: {result.comment}")
        return True
        
    def check_open_positions(self):
        """Check for open positions"""
        positions = mt5.positions_get(symbol=self.symbol)
        return len(positions) if positions is not None else 0
        
    def run(self):
        """Main trading loop"""
        logging.info("Starting trading system...")
        
        while True:
            try:
                # Check if there's already an open position
                if self.check_open_positions() > 0:
                    logging.info("Position already open, waiting...")
                    time.sleep(60)
                    continue
                    
                # Check trading hours
                if not self.is_trading_hour():
                    logging.info("Outside trading hours")
                    time.sleep(60)
                    continue
                    
                # Check trend alignment
                if not self.check_trend_alignment():
                    logging.info("Trends not aligned")
                    time.sleep(60)
                    continue
                    
                # Get trend direction from fastest timeframe
                df = self.get_market_data(self.timeframes['fast'], 100)
                df = self.calculate_indicators(df)
                trend = 1 if df['ema_fast'].iloc[-1] > df['ema_slow'].iloc[-1] else -1
                
                # Calculate entry points
                entry, sl, tp = self.calculate_entry_exit_points(trend)
                
                # Place order
                order_type = mt5.ORDER_TYPE_BUY if trend == 1 else mt5.ORDER_TYPE_SELL
                if self.place_order(order_type, entry, sl, tp):
                    logging.info(f"Order placed: {order_type}, Size: {self.lot_size}, Entry: {entry}, SL: {sl}, TP: {tp}")
                    # Wait for a while after placing an order
                    time.sleep(300)  # 5 minutes
                
                time.sleep(60)  # Wait before next iteration
                
            except Exception as e:
                logging.error(f"Error in main loop: {str(e)}")
                time.sleep(60)

if __name__ == "__main__":
    try:
        trader = TradingSystem()
        trader.run()
    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")
    finally:
        mt5.shutdown()
