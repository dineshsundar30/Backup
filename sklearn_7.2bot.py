import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import talib
from datetime import datetime
import logging
import time
import json
from pathlib import Path


class TradeHistory:
    def __init__(self, history_path="trading_history.json"):
        self.history_path = Path(history_path)
        self.trades_data = self._load_history()

    def _load_history(self):
        if self.history_path.exists():
            with open(self.history_path, 'r') as f:
                return json.load(f)
        return {"trades": [], "failed_patterns": [], "successful_patterns": []}

    def _save_history(self):
        with open(self.history_path, 'w') as f:
            json.dump(self.trades_data, f, indent=4, default=str)

    def log_trade(self, trade_data):
        trade_data['id'] = len(self.trades_data["trades"]) + 1
        trade_data['status'] = 'OPEN'
        self.trades_data["trades"].append(trade_data)
        self._save_history()
        return trade_data['id']

    def update_trade(self, trade_id, exit_price, profit_loss):
        for trade in self.trades_data["trades"]:
            if trade['id'] == trade_id:
                trade['exit_price'] = exit_price
                trade['exit_time'] = str(datetime.now())
                trade['profit_loss'] = profit_loss
                trade['status'] = 'CLOSED'
                break
        self._save_history()

    def get_failed_patterns(self):
        return self.trades_data["failed_patterns"]

    def log_failed_pattern(self, pattern):
        pattern_str = json.dumps(pattern)
        current_time = str(datetime.now())

        # Check if pattern exists and update it, or add new pattern
        pattern_found = False
        for failed_pattern in self.trades_data["failed_patterns"]:
            if failed_pattern["pattern_data"] == pattern_str:
                failed_pattern["failure_count"] += 1
                failed_pattern["last_seen"] = current_time
                pattern_found = True
                break

        if not pattern_found:
            self.trades_data["failed_patterns"].append({
                "pattern_data": pattern_str,
                "failure_count": 1,
                "last_seen": current_time
            })

        self._save_history()


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
            if close[i] > upperband[i - 1]:
                direction[i] = 1
            elif close[i] < lowerband[i - 1]:
                direction[i] = -1
            else:
                direction[i] = direction[i - 1]
                if direction[i] > 0 and lowerband[i] < lowerband[i - 1]:
                    lowerband[i] = lowerband[i - 1]
                if direction[i] < 0 and upperband[i] > upperband[i - 1]:
                    upperband[i] = upperband[i - 1]

            if direction[i] > 0:
                supertrend[i] = lowerband[i]
            else:
                supertrend[i] = upperband[i]

        return supertrend, direction


class MT5TradingBot:
    def __init__(self, symbol, timeframe=mt5.TIMEFRAME_M5, interval=300):
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval = interval
        self.logger = self._setup_logging()
        self.min_balance = 10
        self.fixed_lot = 0.01
        self.trade_history = TradeHistory()
        self.supertrend = SupertrendCalculator()
        self.failed_pattern_expiry_hours = 24  # How long to remember failed patterns

        if not mt5.initialize():
            error = mt5.last_error()
            self.logger.error(f"MT5 Initialization Error: {error}")
            raise Exception(f"MT5 Connection Failed: {error}")

        # Log initial account information
        account_info = mt5.account_info()
        if account_info:
            self.logger.info(f"Current Account Balance: ${account_info.balance:.2f}")
            self.logger.info(f"Current Account Equity: ${account_info.equity:.2f}")
            self.logger.info(f"Current Account Profit: ${account_info.profit:.2f}")

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

        # Log current market conditions
        self.logger.info(f"Current Price: {last_row['close']}")
        self.logger.info(f"SuperTrend Direction: {'Up' if last_row['supertrend_direction'] == 1 else 'Down'}")
        self.logger.info(f"MACD: {last_row['macd']:.6f}, Signal: {last_row['macdsignal']:.6f}")

        # Create current pattern signature
        current_pattern = {
            'supertrend_value': float(last_row['supertrend_direction']),
            'macd_value': 1 if last_row['macd'] > last_row['macdsignal'] else -1,
            'trade_type': 'BUY' if last_row['supertrend_direction'] == 1 else 'SELL'
        }

        # Check if this pattern recently failed
        failed_patterns = self.trade_history.get_failed_patterns()
        current_time = datetime.now()

        for failed_pattern in failed_patterns:
            pattern_data = json.loads(failed_pattern["pattern_data"])
            last_seen = datetime.strptime(failed_pattern["last_seen"], '%Y-%m-%d %H:%M:%S.%f')

            # Only consider failures within the expiry period
            hours_since_failure = (current_time - last_seen).total_seconds() / 3600
            if hours_since_failure > self.failed_pattern_expiry_hours:
                continue

            # Check if current pattern matches a failed pattern
            if (pattern_data['supertrend_value'] == current_pattern['supertrend_value'] and
                    pattern_data['macd_value'] == current_pattern['macd_value'] and
                    pattern_data['trade_type'] == current_pattern['trade_type']):
                self.logger.info(
                    f"Similar pattern failed recently ({hours_since_failure:.1f} hours ago). Skipping trade.")
                return 0, None

        # Trading logic
        if (last_row['supertrend_direction'] == 1 and
                last_row['macd'] > last_row['macdsignal'] and
                last_row['macdhist'] > 0):
            self.logger.info("Buy Signal Detected")
            return 1, current_pattern

        elif (last_row['supertrend_direction'] == -1 and
              last_row['macd'] < last_row['macdsignal'] and
              last_row['macdhist'] < 0):
            self.logger.info("Sell Signal Detected")
            return -1, current_pattern

        self.logger.info("No valid trading signal detected")
        return 0, None

    def execute_trade(self, signal, pattern):
        try:
            if not self.check_account_viability():
                return None

            positions = mt5.positions_get(symbol=self.symbol)
            if positions:
                self.logger.info(f"Active trade exists for {self.symbol}")
                return None

            # Get symbol information
            symbol_info = mt5.symbol_info(self.symbol)
            if symbol_info is None:
                self.logger.error(f"Failed to get symbol info for {self.symbol}")
                return None

            if signal == 1:  # Buy
                trade_type = mt5.ORDER_TYPE_BUY
                price = mt5.symbol_info_tick(self.symbol).ask
                self.logger.info(f"Preparing BUY order at {price}")
            else:  # Sell
                trade_type = mt5.ORDER_TYPE_SELL
                price = mt5.symbol_info_tick(self.symbol).bid
                self.logger.info(f"Preparing SELL order at {price}")

            # Adjust SL and TP based on the symbol
            point = symbol_info.point
            digits = symbol_info.digits

            # For XAUUSD (Gold), use different pip calculations
            if 'GOLD' in self.symbol.upper() or 'XAU' in self.symbol.upper():
                sl_points = 200  # 200 points = $2 for Gold
                tp_points = sl_points * 2
            else:
                sl_points = 100  # Regular forex pairs
                tp_points = sl_points * 2

            # Calculate SL and TP prices
            if trade_type == mt5.ORDER_TYPE_BUY:
                sl = price - (sl_points * point)
                tp = price + (tp_points * point)
            else:
                sl = price + (sl_points * point)
                tp = price - (tp_points * point)

            # Round SL and TP to the correct number of digits
            sl = round(sl, digits)
            tp = round(tp, digits)

            self.logger.info(f"Trade parameters - Entry: {price}, SL: {sl}, TP: {tp}")

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
                self.logger.info(f"Trade executed successfully at {price}")
                trade_data = {
                    'symbol': self.symbol,
                    'entry_time': str(datetime.now()),
                    'entry_price': float(price),
                    'trade_type': 'BUY' if trade_type == mt5.ORDER_TYPE_BUY else 'SELL',
                    'lot_size': self.fixed_lot,
                    'supertrend_value': float(pattern['supertrend_value']),
                    'macd_value': float(pattern['macd_value']),
                    'sl': sl,
                    'tp': tp
                }
                trade_id = self.trade_history.log_trade(trade_data)
                self.logger.info(f"Trade logged to history with ID: {trade_id}")
            else:
                self.logger.error(f"Trade failed: {result.comment}")
                self.logger.error(f"Error code: {result.retcode}")
                self.trade_history.log_failed_pattern(pattern)

        except Exception as e:
            self.logger.error(f"Trade execution error: {e}")

    def check_account_viability(self):
        account_info = mt5.account_info()
        if account_info is None:
            self.logger.error("Cannot retrieve account information")
            return False

        self.logger.info(f"Account Balance: ${account_info.balance:.2f}")
        self.logger.info(f"Account Equity: ${account_info.equity:.2f}")

        if account_info.balance < self.min_balance:
            self.logger.warning(
                f"Account balance (${account_info.balance:.2f}) below minimum requirement (${self.min_balance:.2f})")
            return False
        return True

    def run_trading_cycle(self):
        self.logger.info(f"Starting trading bot for {self.symbol}")
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


def main():
    # Get symbol input from user
    symbol = input("Enter trading symbol (e.g., EURUSD): ")

    try:
        bot = MT5TradingBot(symbol=symbol)
        bot.run_trading_cycle()
    except KeyboardInterrupt:
        print("\nTrading bot stopped by user")
    except Exception as e:
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
