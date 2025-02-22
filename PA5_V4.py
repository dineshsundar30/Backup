import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import time
import logging
from typing import Optional, Dict, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('crypto_trading_bot.log'),
        logging.StreamHandler()
    ]
)


class CryptoPriceActionTrader:
    def __init__(self, symbol: str, risk_percent: float = 1.0):
        """Initialize cryptocurrency trading bot"""
        self.symbol = symbol
        self.risk_percent = risk_percent
        self.base_tf = mt5.TIMEFRAME_M5
        self.higher_tf = mt5.TIMEFRAME_H1
        self.swing_points = {'support': [], 'resistance': []}
        self.last_scan_time = datetime.now()

        # Initialize MT5 connection
        if not self.initialize_mt5():
            raise ConnectionError("MT5 initialization failed")

        # Trading parameters
        self.rsi_period = 14
        self.rsi_overbought = 65
        self.rsi_oversold = 35
        self.atr_period = 14
        self.min_volume_multiplier = 1.2

        # Initial data load
        self.refresh_market_data()
        self.print_init_status()

    def initialize_mt5(self) -> bool:
        """Initialize MT5 connection with retries"""
        for _ in range(3):
            if mt5.initialize():
                self.account_info = mt5.account_info()
                self.symbol_info = mt5.symbol_info(self.symbol)
                if not self.symbol_info:
                    self.print_available_symbols()
                    return False
                return True
            time.sleep(2)
        return False

    def print_available_symbols(self):
        """Display available cryptocurrency symbols"""
        print("Available crypto symbols:")
        all_symbols = mt5.symbols_get()
        crypto_symbols = [s.name for s in all_symbols if "crypto" in s.path.lower()]
        for sym in crypto_symbols[:10]:
            print(f" - {sym}")

    def print_init_status(self):
        """Print initialization details"""
        print(f"\n{'=' * 60}")
        print(f"✅ CRYPTO TRADING BOT INITIALIZED")
        print(f"🔎 Symbol: {self.symbol}")
        print(f"💰 Balance: ${self.account_info.balance:,.2f}")
        print(f"📊 Spread: {self.symbol_info.spread} pts")
        print(f"⏱️ Timeframes: M5 (Base) | H1 (Higher)")
        print(f"⚖️ Risk: {self.risk_percent}% | RR Ratio: 1:3")
        print(f"{'=' * 60}\n")

    def refresh_market_data(self):
        """Refresh market data with error handling"""
        try:
            print(f"\n🔄 [{datetime.now().strftime('%H:%M:%S')}] Refreshing data...")
            self.base_df = self.get_ohlcv(self.base_tf, 500)
            self.higher_df = self.get_ohlcv(self.higher_tf, 200)
            self.update_swing_points()
            self.current_price = mt5.symbol_info_tick(self.symbol).ask
            print(f"✅ Data refreshed | Price: {self.current_price:.5f}")
        except Exception as e:
            logging.error(f"Data refresh failed: {str(e)}")

    def get_ohlcv(self, timeframe: int, count: int) -> pd.DataFrame:
        """Get OHLCV data with retries"""
        for _ in range(3):
            rates = mt5.copy_rates_from_pos(self.symbol, timeframe, 0, count)
            if rates is not None:
                df = pd.DataFrame(rates)
                df['time'] = pd.to_datetime(df['time'], unit='s')
                return df.set_index('time')
            time.sleep(1)
        raise ConnectionError("Failed to fetch OHLCV data")

    def update_swing_points(self):
        """Identify support/resistance levels"""
        df = self.base_df[-100:]
        self.swing_points = {'support': [], 'resistance': []}

        for i in range(2, len(df) - 2):
            high = df['high'].iloc[i]
            low = df['low'].iloc[i]

            if high > df['high'].iloc[i - 1] and high > df['high'].iloc[i - 2] and \
                    high > df['high'].iloc[i + 1] and high > df['high'].iloc[i + 2]:
                self.swing_points['resistance'].append(high)

            if low < df['low'].iloc[i - 1] and low < df['low'].iloc[i - 2] and \
                    low < df['low'].iloc[i + 1] and low < df['low'].iloc[i + 2]:
                self.swing_points['support'].append(low)

    def calculate_atr(self, df: pd.DataFrame) -> pd.Series:
        """Calculate Average True Range"""
        high_low = df['high'] - df['low']
        high_close = (df['high'] - df['close'].shift()).abs()
        low_close = (df['low'] - df['close'].shift()).abs()
        tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
        return tr.rolling(self.atr_period).mean()

    def detect_market_phase(self) -> str:
        """Identify current market condition"""
        df = self.base_df[-20:]
        atr = self.calculate_atr(df).iloc[-1]
        price_range = df['high'].max() - df['low'].min()

        if price_range / atr < 1.5 and len(self.swing_points['support']) > 3:
            return 'range'

        current_high = df['high'].iloc[-1]
        current_low = df['low'].iloc[-1]
        if current_high > max(self.swing_points['resistance'][-3:]):
            return 'breakout_bullish'
        if current_low < min(self.swing_points['support'][-3:]):
            return 'breakout_bearish'
        return 'trending'

    def detect_price_patterns(self) -> Dict:
        """Identify candlestick patterns"""
        patterns = {
            'doji': False,
            'bullish_engulf': False,
            'bearish_engulf': False,
            'bullish_pin': False,
            'bearish_pin': False,
            'inside_bar': False
        }

        if len(self.base_df) < 3:
            return patterns

        current = self.base_df.iloc[-1]
        prev = self.base_df.iloc[-2]

        # Pattern detection logic
        body_size = abs(current['close'] - current['open'])
        total_range = current['high'] - current['low']

        patterns['doji'] = body_size <= total_range * 0.1
        patterns['bullish_engulf'] = (current['close'] > current['open'] and
                                      prev['close'] < prev['open'] and
                                      current['open'] < prev['close'] and
                                      current['close'] > prev['open'])
        patterns['bearish_engulf'] = (current['close'] < current['open'] and
                                      prev['close'] > prev['open'] and
                                      current['open'] > prev['close'] and
                                      current['close'] < prev['open'])

        upper_wick = current['high'] - max(current['open'], current['close'])
        lower_wick = min(current['open'], current['close']) - current['low']
        patterns['bullish_pin'] = lower_wick > total_range * 0.6 and body_size < total_range * 0.3
        patterns['bearish_pin'] = upper_wick > total_range * 0.6 and body_size < total_range * 0.3
        patterns['inside_bar'] = (current['high'] < prev['high'] and
                                  current['low'] > prev['low'])

        return patterns

    def calculate_rsi(self) -> float:
        """Calculate Relative Strength Index"""
        delta = self.base_df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.rsi_period, adjust=False).mean()

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs)).iloc[-1]

    def get_higher_tf_trend(self) -> str:
        """Get higher timeframe trend direction"""
        if len(self.higher_df) < 50:
            return 'neutral'

        ema20 = self.higher_df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = self.higher_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        return 'bullish' if ema20 > ema50 else 'bearish' if ema20 < ema50 else 'neutral'
    def calculate_position_size(self, sl_pips: float) -> float:
        """Calculate risk-adjusted position size"""
        risk_amount = self.account_info.balance * (self.risk_percent / 100)
        pip_value = (self.symbol_info.point * 10) * self.symbol_info.trade_contract_size
        return round(risk_amount / (sl_pips * pip_value), 2)

    def calculate_stop_loss(self, direction: str) -> Tuple[float, float]:
        """Determine stop loss levels"""
        price = self.current_price
        if direction == 'buy':
            nearest_support = min([s for s in self.swing_points['support'] if s < price],
                                  default=price - 50 * self.symbol_info.point)
            sl = nearest_support - 2 * self.symbol_info.point
        else:
            nearest_resistance = max([r for r in self.swing_points['resistance'] if r > price],
                                     default=price + 50 * self.symbol_info.point)
            sl = nearest_resistance + 2 * self.symbol_info.point

        sl_pips = abs(price - sl) / self.symbol_info.point
        return sl, sl_pips

    def execute_trade(self, direction: str, pattern: str):
        """Execute trade with proper risk management"""
        if self.active_position_exists():
            print("\n⚠️ Existing position detected - Trade skipped")
            return

        try:
            tick = mt5.symbol_info_tick(self.symbol)
            entry_price = tick.ask if direction == 'buy' else tick.bid
            sl_price, sl_pips = self.calculate_stop_loss(direction)
            tp_price = entry_price + (entry_price - sl_price) * 3 if direction == 'buy' else entry_price - (
                        sl_price - entry_price) * 3
            lot_size = self.calculate_position_size(sl_pips)

            print(f"\n{'=' * 60}")
            print(f"🚀 Executing {direction.upper()} Trade")
            print(f"📈 Pattern: {pattern.replace('_', ' ').title()}")
            print(f"💰 Entry: {entry_price:.5f}")
            print(f"⛔ Stop Loss: {sl_price:.5f} ({sl_pips:.1f} pips)")
            print(f"🎯 Take Profit: {tp_price:.5f}")
            print(f"📦 Size: {lot_size:.2f} lots")
            print(f"{'=' * 60}")

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": self.symbol,
                "volume": lot_size,
                "type": mt5.ORDER_TYPE_BUY if direction == 'buy' else mt5.ORDER_TYPE_SELL,
                "price": entry_price,
                "sl": sl_price,
                "tp": tp_price,
                "deviation": 20,
                "magic": 202310,
                "comment": f"PA_{pattern}",
                "type_time": mt5.ORDER_TIME_GTC,
            }

            result = mt5.order_send(request)
            if result.retcode != mt5.TRADE_RETCODE_DONE:
                logging.error(f"Trade failed: {result.comment}")
            else:
                logging.info(f"Trade executed: {direction} {lot_size} lots")

        except Exception as e:
            logging.error(f"Trade execution error: {str(e)}")

    def active_position_exists(self) -> bool:
        """Check for existing positions"""
        positions = mt5.positions_get(symbol=self.symbol)
        return len(positions) > 0

    def run_strategy(self):
        """Main trading strategy loop"""
        print("\n🚀 Starting Trading Strategy")
        print("📡 Scanning market for opportunities...\n")

        while True:
            try:
                if (datetime.now() - self.last_scan_time).seconds >= 30:
                    self.refresh_market_data()
                    self.last_scan_time = datetime.now()

                    # Market analysis
                    patterns = self.detect_price_patterns()
                    rsi = self.calculate_rsi()
                    trend = self.get_higher_tf_trend()
                    market_phase = self.detect_market_phase()
                    volume_ok = self.base_df['tick_volume'].iloc[-1] > \
                                self.base_df['tick_volume'].rolling(20).mean().iloc[-1]

                    # Print market status
                    print(f"\n{'=' * 60}")
                    print(f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"📈 Price: {self.current_price:.5f} | RSI: {rsi:.1f}")
                    print(f"🌐 Phase: {market_phase.replace('_', ' ').title()}")
                    print(f"📊 Volume: {'✅ Strong' if volume_ok else '❌ Weak'}")
                    print(
                        f"🔍 Patterns: {', '.join([p.replace('_', ' ').title() for p, v in patterns.items() if v]) or 'None'}")
                    print(f"{'=' * 60}")

                    # Trading logic
                    if market_phase == 'range':
                        print("⏸️  Market ranging - Waiting for breakout")
                        continue

                    if market_phase in ['trending', 'breakout_bullish', 'breakout_bearish']:
                        if trend == 'bullish' and volume_ok and rsi < 60:
                            if patterns['bullish_engulf']:
                                self.execute_trade('buy', 'bullish_engulf')
                            elif patterns['bullish_pin']:
                                self.execute_trade('buy', 'bullish_pin')

                        elif trend == 'bearish' and volume_ok and rsi > 40:
                            if patterns['bearish_engulf']:
                                self.execute_trade('sell', 'bearish_engulf')
                            elif patterns['bearish_pin']:
                                self.execute_trade('sell', 'bearish_pin')

                time.sleep(5)

            except Exception as e:
                logging.error(f"Main loop error: {str(e)}")
                time.sleep(30)

#PA with  1:3 and sl and deep seek cnage v2
if __name__ == "__main__":
    try:
        # Try common cryptocurrency symbols
        symbols = ['BTCUSDm']
        for symbol in symbols:
            try:
                print(f"Attempting connection with {symbol}...")
                trader = CryptoPriceActionTrader(symbol)
                trader.run_strategy()
                break
            except ValueError:
                continue
    except Exception as e:
        print(f"\n❌ Critical Error: {str(e)}")
        print("Troubleshooting:")
        print("1. Verify MT5 is running with correct symbol")
        print("2. Check cryptocurrency trading permissions")
        print("3. Ensure internet connection is stable")
        print("4. Confirm MT5 server supports cryptocurrency trading")
