import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime
import time
import logging

# Configure logging
logging.basicConfig(
    filename='price_action_trader.log',
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)


class PriceActionTrader:
    def __init__(self, symbol, timeframe=mt5.TIMEFRAME_M5):
        """Initialize the trader with symbol and timeframe"""
        self.symbol = symbol
        self.timeframe = timeframe
        self.lot_size = 0.01
        self.position_open = False
        self.risk_reward_ratio = 3  # Implementing 1:3 risk-reward ratio

        # SL adjustment factor - increase this to give more breathing room
        self.sl_buffer_multiplier = 1.5

        # Initialize MT5
        if not mt5.initialize():
            print("MT5 initialization failed!")
            raise Exception("MT5 initialization failed")
        print(f"MT5 connected successfully for {self.symbol}")

        # Get symbol info for pip calculation
        self.symbol_info = mt5.symbol_info(self.symbol)
        if self.symbol_info is None:
            raise Exception(f"Failed to get symbol info for {self.symbol}")

        # Calculate pip value
        self.point = self.symbol_info.point
        self.digits = self.symbol_info.digits
        self.pip_multiplier = 10 if self.digits == 3 or self.digits == 5 else 1
        self.pip_value = self.point * self.pip_multiplier

        print(f"Pip value for {self.symbol}: {self.pip_value}")

    def get_candles(self, count=500):
        """Get candlestick data from MT5"""
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, count)
        if rates is None:
            print("Failed to fetch candle data")
            return None
        return pd.DataFrame(rates)

    def identify_trend(self, df, window=10):
        """Identify the current market trend"""
        try:
            high_max = df['high'].rolling(window=window).max()
            low_min = df['low'].rolling(window=window).min()

            last_highs = high_max.tail(window)
            last_lows = low_min.tail(window)

            higher_highs = last_highs.iloc[-1] > last_highs.iloc[0]
            higher_lows = last_lows.iloc[-1] > last_lows.iloc[0]

            lower_highs = last_highs.iloc[-1] < last_highs.iloc[0]
            lower_lows = last_lows.iloc[-1] < last_lows.iloc[0]

            print(f"Trend Analysis - Higher Highs: {higher_highs}, Higher Lows: {higher_lows}")

            if higher_highs and higher_lows:
                return "uptrend"
            elif lower_highs and lower_lows:
                return "downtrend"
            else:
                return "sideways"

        except Exception as e:
            print(f"Error in trend identification: {str(e)}")
            return "sideways"

    def identify_doji(self, df, row_idx, tolerance=0.2):
        """Identify doji candlestick pattern"""
        try:
            row = df.iloc[row_idx]
            body_size = abs(row['open'] - row['close'])
            wick_size = row['high'] - row['low']

            if wick_size == 0:
                return False

            body_to_wick_ratio = body_size / wick_size
            is_doji = body_to_wick_ratio <= tolerance

            print(f"Doji Analysis - Body/Wick Ratio: {body_to_wick_ratio:.5f}")
            return is_doji

        except Exception as e:
            print(f"Error in doji calculation: {str(e)}")
            return False

    def identify_engulfing(self, df, row_idx):
        """Identify engulfing candlestick pattern"""
        try:
            if row_idx < 1:
                return None

            current = df.iloc[row_idx]
            previous = df.iloc[row_idx - 1]

            # Bullish engulfing
            if (current['close'] > current['open'] and
                    previous['close'] < previous['open'] and
                    current['close'] > previous['open'] and
                    current['open'] < previous['close']):
                return "bullish"

            # Bearish engulfing
            if (current['close'] < current['open'] and
                    previous['close'] > previous['open'] and
                    current['close'] < previous['open'] and
                    current['open'] > previous['close']):
                return "bearish"

            return None

        except Exception as e:
            print(f"Error in engulfing calculation: {str(e)}")
            return None

    def identify_pin_bar(self, df, row_idx, tail_ratio=0.6):
        """Identify pin bar pattern"""
        try:
            row = df.iloc[row_idx]
            total_range = row['high'] - row['low']
            body_range = abs(row['open'] - row['close'])

            if total_range == 0:
                return None

            upper_wick = row['high'] - max(row['open'], row['close'])
            lower_wick = min(row['open'], row['close']) - row['low']

            # Bullish pin bar (hammer)
            if (lower_wick > (total_range * tail_ratio) and
                    upper_wick < (total_range * 0.2) and
                    body_range < (total_range * 0.4)):
                return "bullish"

            # Bearish pin bar (shooting star)
            if (upper_wick > (total_range * tail_ratio) and
                    lower_wick < (total_range * 0.2) and
                    body_range < (total_range * 0.4)):
                return "bearish"

            return None

        except Exception as e:
            print(f"Error in pin bar calculation: {str(e)}")
            return None

    def calculate_atr(self, df, period=14):  # Increased ATR period for stability
        """Calculate Average True Range"""
        try:
            high = df['high']
            low = df['low']
            close = df['close'].shift(1)

            tr1 = high - low
            tr2 = abs(high - close)
            tr3 = abs(low - close)

            tr = pd.DataFrame({'tr1': tr1, 'tr2': tr2, 'tr3': tr3}).max(axis=1)
            atr = tr.rolling(window=period).mean()

            return atr

        except Exception as e:
            print(f"Error calculating ATR: {str(e)}")
            return pd.Series([0] * len(df))

    def calculate_sl_tp(self, direction, entry_price, sl_distance):
        """Calculate Stop Loss and Take Profit with 1:3 risk-reward ratio"""
        if direction == "buy":
            stop_loss = entry_price - sl_distance
            # Take profit is 3x the SL distance (1:3 ratio)
            take_profit = entry_price + (sl_distance * self.risk_reward_ratio)
        else:  # sell
            stop_loss = entry_price + sl_distance
            # Take profit is 3x the SL distance (1:3 ratio)
            take_profit = entry_price - (sl_distance * self.risk_reward_ratio)

        return stop_loss, take_profit

    def find_swing_levels(self, df, lookback=20):
        """Find recent swing high/low levels for better SL placement"""
        highs = df['high'].values
        lows = df['low'].values

        # Simple swing high detection (price higher than surrounding bars)
        swing_highs = []
        for i in range(2, min(lookback, len(df) - 2)):
            if highs[i] > highs[i - 1] and highs[i] > highs[i - 2] and highs[i] > highs[i + 1] and highs[i] > highs[
                i + 2]:
                swing_highs.append(highs[i])

        # Simple swing low detection (price lower than surrounding bars)
        swing_lows = []
        for i in range(2, min(lookback, len(df) - 2)):
            if lows[i] < lows[i - 1] and lows[i] < lows[i - 2] and lows[i] < lows[i + 1] and lows[i] < lows[i + 2]:
                swing_lows.append(lows[i])

        return swing_highs, swing_lows

    def calculate_sl_distance(self, df, direction, entry_price):
        """Calculate appropriate SL distance based on ATR and swing levels"""
        atr = self.calculate_atr(df).iloc[-1]

        # Get recent swing levels
        swing_highs, swing_lows = self.find_swing_levels(df)

        if direction == "buy":
            # For buy trades, find the most relevant swing low
            relevant_lows = [low for low in swing_lows if low < entry_price]
            if relevant_lows:
                # Place SL below the nearest swing low
                nearest_swing_low = max(relevant_lows)
                # Add a buffer (percentage of ATR) below the swing low
                sl_distance = entry_price - (nearest_swing_low - (0.3 * atr))
            else:
                # Fallback: use ATR with a buffer multiplier
                sl_distance = self.sl_buffer_multiplier * atr

        else:  # sell
            # For sell trades, find the most relevant swing high
            relevant_highs = [high for high in swing_highs if high > entry_price]
            if relevant_highs:
                # Place SL above the nearest swing high
                nearest_swing_high = min(relevant_highs)
                # Add a buffer (percentage of ATR) above the swing high
                sl_distance = (nearest_swing_high + (0.3 * atr)) - entry_price
            else:
                # Fallback: use ATR with a buffer multiplier
                sl_distance = self.sl_buffer_multiplier * atr

        # Make sure SL distance is at least 1.5x ATR to avoid premature stop outs
        min_sl_distance = self.sl_buffer_multiplier * atr
        sl_distance = max(sl_distance, min_sl_distance)

        return sl_distance

    def place_trade(self, direction, entry_price, stop_loss, take_profit):
        """Execute trade in MT5"""
        if self.position_open:
            print("⚠️ Position already open, skipping new trade")
            return False

        # Calculate SL and TP distances in pips
        sl_pips = abs(entry_price - stop_loss) / self.pip_value
        tp_pips = abs(entry_price - take_profit) / self.pip_value

        # Log risk-reward details
        logging.info(f"Trade setup - Direction: {direction}, Entry: {entry_price:.5f}")
        logging.info(f"SL: {stop_loss:.5f} ({sl_pips:.1f} pips), TP: {take_profit:.5f} ({tp_pips:.1f} pips)")
        logging.info(f"Risk-Reward Ratio: 1:{tp_pips / sl_pips:.2f}")

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.lot_size,
            "type": mt5.ORDER_TYPE_BUY if direction == "buy" else mt5.ORDER_TYPE_SELL,
            "price": entry_price,
            "sl": stop_loss,
            "tp": take_profit,
            "deviation": 20,
            "magic": 234000,
            "comment": "price action trade 1:3 RR",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC,
        }

        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"❌ Trade failed: {result.comment}")
            return False

        self.position_open = True
        print("\n🔵 TRADE EXECUTED:")
        print(f"Symbol: {self.symbol}")
        print(f"Type: {'BUY' if direction == 'buy' else 'SELL'}")
        print(f"Entry Price: {entry_price:.5f}")
        print(f"Stop Loss: {stop_loss:.5f} ({sl_pips:.1f} pips)")
        print(f"Take Profit: {take_profit:.5f} ({tp_pips:.1f} pips)")
        print(f"Risk-Reward Ratio: 1:{tp_pips / sl_pips:.2f}")
        print(f"Lot Size: {self.lot_size}")
        print("----------------------------------------\n")
        return True

    def run(self):
        """Main trading loop"""
        print(f"\n🚀 Starting Price Action Trader for {self.symbol} on M5 timeframe")
        print(f"Trading with 1:{self.risk_reward_ratio} risk-reward ratio")
        print(f"Using improved SL placement with {self.sl_buffer_multiplier}x ATR buffer")

        while True:
            try:
                # Fetch latest data
                df = self.get_candles()
                if df is None:
                    continue

                # Check for open positions
                if self.position_open:
                    positions = mt5.positions_get(symbol=self.symbol)
                    self.position_open = len(positions) > 0
                    if self.position_open:
                        print(f"📊 Active position open for {self.symbol}")
                    continue

                # Market analysis
                current_trend = self.identify_trend(df)
                atr = self.calculate_atr(df).iloc[-1]

                # Pattern detection
                last_candle_idx = -1
                doji = self.identify_doji(df, last_candle_idx)
                engulfing = self.identify_engulfing(df, last_candle_idx)
                pin_bar = self.identify_pin_bar(df, last_candle_idx)

                # Print market conditions
                print(f"\n🔍 MARKET CHECK - {self.symbol}")
                print(f"Current Price: {df['close'].iloc[-1]:.5f}")
                print(f"Trend: {current_trend}")
                print(
                    f"Patterns Found: {'Doji ' if doji else ''}{'Pin Bar ' + pin_bar if pin_bar else ''}{'Engulfing ' + engulfing if engulfing else ''}")

                # Trading logic
                entry_price = df['close'].iloc[-1]

                if current_trend == "uptrend":
                    if (pin_bar == "bullish" or engulfing == "bullish") and not doji:
                        print("\n🔼 BULLISH SIGNAL DETECTED")

                        # Calculate optimal SL distance based on market conditions
                        sl_distance = self.calculate_sl_distance(df, "buy", entry_price)

                        # Apply 1:3 risk-reward ratio to determine SL and TP
                        stop_loss, take_profit = self.calculate_sl_tp("buy", entry_price, sl_distance)

                        self.place_trade("buy", entry_price, stop_loss, take_profit)

                elif current_trend == "downtrend":
                    if (pin_bar == "bearish" or engulfing == "bearish") and not doji:
                        print("\n🔽 BEARISH SIGNAL DETECTED")

                        # Calculate optimal SL distance based on market conditions
                        sl_distance = self.calculate_sl_distance(df, "sell", entry_price)

                        # Apply 1:3 risk-reward ratio to determine SL and TP
                        stop_loss, take_profit = self.calculate_sl_tp("sell", entry_price, sl_distance)

                        self.place_trade("sell", entry_price, stop_loss, take_profit)

                time.sleep(5)

            except Exception as e:
                print(f"❌ Error in main loop: {str(e)}")
                logging.error(f"Main loop error: {str(e)}")
                time.sleep(30)

#PA with  1:3 and sl cnage
if __name__ == "__main__":
    trader = PriceActionTrader("XAUUSDm")
    trader.run()
