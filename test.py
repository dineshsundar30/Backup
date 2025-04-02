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
        logging.FileHandler('xauusd_price_action.log'),
        logging.StreamHandler()
    ]
)


class XAUUSDPriceActionTrader:
    def __init__(self, symbol: str = 'XAUUSDm', fixed_lot_size: float = 0.01):
        """Initialize XAUUSD price action trader with enhanced features"""
        self.symbol = symbol
        self.fixed_lot_size = fixed_lot_size
        self.base_tf = mt5.TIMEFRAME_M5  # Focus on 5-minute chart
        self.higher_tf = mt5.TIMEFRAME_H1
        self.swing_points = {'support': [], 'resistance': []}
        self.last_scan_time = datetime.now()
        self.last_trade_time = datetime.now() - timedelta(hours=1)  # Prevent immediate trading on startup

        # Initialize MT5 connection
        if not self.initialize_mt5():
            raise ConnectionError("Failed to initialize MT5 connection")

        # Risk management parameters
        self.rsi_period = 14
        self.rsi_overbought = 75  # More relaxed for Gold 
        self.rsi_oversold = 25    # More relaxed for Gold
        self.atr_period = 14
        self.trailing_sl = True
        self.breakeven_at = 1.5  # Move SL to breakeven at 1.5x risk
        
        # Cooldown between trades (reduced to increase trade frequency)
        self.trade_cooldown_minutes = 5

        # Initial market data load
        self.refresh_market_data()
        self.print_init_status()

    def print_init_status(self):
        """Print initialization status"""
        print(f"\n{'=' * 60}")
        print(f"✅ GOLD PRICE ACTION TRADER INITIALIZED")
        print(f"🔎 Symbol: {self.symbol} | Account Balance: ${self.account_info.balance:,.2f}")
        print(f"📊 Spread: {self.symbol_info.spread} pts | Fixed Lot Size: {self.fixed_lot_size}")
        print(f"⏱️ OPTIMIZED FOR M5 CHART | Risk/Reward: Dynamic (min 1:2)")
        print(f"{'=' * 60}\n")

    def initialize_mt5(self) -> bool:
        """Initialize MT5 connection with retries and validation"""
        for _ in range(3):
            if mt5.initialize():
                self.account_info = mt5.account_info()
                self.symbol_info = mt5.symbol_info(self.symbol)
                if self.symbol_info is None:
                    self.print_available_symbols()
                    return False
                return True
            time.sleep(2)
        return False

    def print_available_symbols(self):
        """Print first 10 available symbols for troubleshooting"""
        print("⚠️ Available symbols in MT5:")
        for i, s in enumerate(mt5.symbols_get()[:10]):
            print(f"{i + 1}. {s.name}")
        print("\n")

    def refresh_market_data(self):
        """Refresh market data with error handling"""
        try:
            print(f"\n🔄 [{datetime.now().strftime('%H:%M:%S')}] Refreshing market data...")
            self.base_df = self.get_ohlcv(self.base_tf, 100)  # Reduced from 500 for faster processing
            self.higher_df = self.get_ohlcv(self.higher_tf, 50)  # Reduced from 200 for faster processing
            self.update_swing_points()
            self.current_price = mt5.symbol_info_tick(self.symbol).ask
            print(f"✅ Data refreshed | Gold Price: {self.current_price:.2f}")
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
        """Identify swing points for support/resistance in Gold with improved logic"""
        df = self.base_df[-50:]  # Last 50 bars for faster processing
        self.swing_points = {'support': [], 'resistance': []}

        # Enhanced swing point detection (5-point method)
        for i in range(4, len(df) - 4):
            # Check more bars for more significant levels
            high = df['high'].iloc[i]
            low = df['low'].iloc[i]
            
            # Swing high detection - check 4 bars before and after
            if all(high > df['high'].iloc[i-j] for j in range(1, 5)) and \
               all(high > df['high'].iloc[i+j] for j in range(1, 5)):
                self.swing_points['resistance'].append(high)
            
            # Swing low detection - check 4 bars before and after
            if all(low < df['low'].iloc[i-j] for j in range(1, 5)) and \
               all(low < df['low'].iloc[i+j] for j in range(1, 5)):
                self.swing_points['support'].append(low)
        
        # Also look for significant pullbacks on higher timeframe
        h_df = self.higher_df[-20:]
        for i in range(2, len(h_df) - 2):
            high = h_df['high'].iloc[i]
            low = h_df['low'].iloc[i]
            
            # Add only very significant H1 levels
            if all(high > h_df['high'].iloc[i-j] for j in range(1, 3)) and \
               all(high > h_df['high'].iloc[i+j] for j in range(1, 3)):
                self.swing_points['resistance'].append(high)
            
            if all(low < h_df['low'].iloc[i-j] for j in range(1, 3)) and \
               all(low < h_df['low'].iloc[i+j] for j in range(1, 3)):
                self.swing_points['support'].append(low)
        
        # Remove duplicates and sort
        self.swing_points['support'] = sorted(list(set(self.swing_points['support'])))
        self.swing_points['resistance'] = sorted(list(set(self.swing_points['resistance'])))

    def detect_price_patterns(self) -> Dict:
        """Detect multiple price action patterns for Gold with focus on M5 timeframe"""
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
        prev2 = self.base_df.iloc[-3]

        # Doji Pattern (more relaxed definition)
        body_size = abs(current['close'] - current['open'])
        total_range = current['high'] - current['low']
        patterns['doji'] = body_size <= total_range * 0.15  # Increased from 0.1 for more signals

        # Engulfing Patterns (relaxed conditions for more signals)
        patterns['bullish_engulf'] = (current['close'] > current['open'] and
                                     prev['close'] < prev['open'] and
                                     (current['open'] <= prev['close'] * 1.001) and  # Added small tolerance
                                     (current['close'] >= prev['open'] * 0.999))     # Added small tolerance

        patterns['bearish_engulf'] = (current['close'] < current['open'] and
                                     prev['close'] > prev['open'] and
                                     (current['open'] >= prev['close'] * 0.999) and  # Added small tolerance
                                     (current['close'] <= prev['open'] * 1.001))     # Added small tolerance

        # Pin Bar Patterns (relaxed conditions)
        upper_wick = current['high'] - max(current['open'], current['close'])
        lower_wick = min(current['open'], current['close']) - current['low']
        patterns['bullish_pin'] = lower_wick > total_range * 0.5 and body_size < total_range * 0.4  # Less strict
        patterns['bearish_pin'] = upper_wick > total_range * 0.5 and body_size < total_range * 0.4  # Less strict

        # Inside Bar Pattern
        patterns['inside_bar'] = (current['high'] <= prev['high'] * 1.001 and
                                 current['low'] >= prev['low'] * 0.999)  # Added small tolerance

        return patterns

    def calculate_rsi(self) -> float:
        """Calculate RSI with smoothing"""
        df = self.base_df.copy()
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0)
        loss = -delta.where(delta < 0, 0)

        avg_gain = gain.ewm(alpha=1 / self.rsi_period, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1 / self.rsi_period, adjust=False).mean()

        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs)).iloc[-1]

    def get_higher_tf_trend(self) -> str:
        """Get higher timeframe trend direction for Gold"""
        if len(self.higher_df) < 20:  # Reduced from 50 for faster response
            return 'neutral'

        ema20 = self.higher_df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        ema50 = self.higher_df['close'].ewm(span=50, adjust=False).mean().iloc[-1]
        
        # Calculate additional trend indicator
        price = self.higher_df['close'].iloc[-1]
        prev_price = self.higher_df['close'].iloc[-2]
        price_above_ema = price > ema20
        rising_price = price > prev_price
        
        # More nuanced trend assessment
        if ema20 > ema50 and price_above_ema and rising_price:
            return 'strong_bullish'
        elif ema20 > ema50:
            return 'bullish'
        elif ema20 < ema50 and not price_above_ema and not rising_price:
            return 'strong_bearish'
        elif ema20 < ema50:
            return 'bearish'
        else:
            return 'neutral'

    def calculate_stop_loss(self, direction: str) -> Tuple[float, float]:
        """Calculate stop loss based on market analysis - adapted for Gold"""
        price = self.current_price
        
        # Calculate Average True Range for more dynamic stop loss sizing
        df = self.base_df.copy()
        df['tr1'] = abs(df['high'] - df['low'])
        df['tr2'] = abs(df['high'] - df['close'].shift(1))
        df['tr3'] = abs(df['low'] - df['close'].shift(1))
        df['tr'] = df[['tr1', 'tr2', 'tr3']].max(axis=1)
        atr = df['tr'].rolling(self.atr_period).mean().iloc[-1]
        
        # More sophisticated stop loss calculation
        if direction == 'buy':
            # For buy trades, consider multiple factors
            # 1. Check recent swing lows
            recent_lows = self.base_df['low'].iloc[-5:].min()
            # 2. Check key support levels
            nearest_support = max([s for s in self.swing_points['support'] if s < price], default=recent_lows)
            # 3. Use ATR for minimum distance
            min_sl_distance = atr * 1.5  # At least 1.5x ATR
            
            # Calculate SL based on nearest significant level
            candidate_sl = min(recent_lows, nearest_support) - 2 * self.symbol_info.point
            
            # Ensure minimum distance from current price
            if price - candidate_sl < min_sl_distance:
                sl = price - min_sl_distance
            else:
                sl = candidate_sl
        else:
            # For sell trades, use similar approach for resistance
            recent_highs = self.base_df['high'].iloc[-5:].max()
            nearest_resistance = min([r for r in self.swing_points['resistance'] if r > price], default=recent_highs)
            min_sl_distance = atr * 1.5
            
            candidate_sl = max(recent_highs, nearest_resistance) + 2 * self.symbol_info.point
            
            if candidate_sl - price < min_sl_distance:
                sl = price + min_sl_distance
            else:
                sl = candidate_sl

        # Calculate pips from price to stop loss
        sl_pips = abs(price - sl) / self.symbol_info.point
        
        # Limit maximum stop loss size based on % of account balance
        account_balance = self.account_info.balance
        max_risk_amount = account_balance * 0.02  # 2% max risk
        max_sl_pips = (max_risk_amount / (self.fixed_lot_size * 10)) / (self.symbol_info.point * 10)  # Approximation for Gold
        
        if sl_pips > max_sl_pips:
            sl_pips = max_sl_pips
            sl = price - max_sl_pips * self.symbol_info.point if direction == 'buy' else price + max_sl_pips * self.symbol_info.point
        
        # Ensure minimum SL size to avoid noise
        min_sl_pips = 15  # Minimum 15 pips for Gold
        if sl_pips < min_sl_pips:
            sl_pips = min_sl_pips
            sl = price - min_sl_pips * self.symbol_info.point if direction == 'buy' else price + min_sl_pips * self.symbol_info.point
                
        return sl, sl_pips

    def print_scan_summary(self, patterns: Dict, rsi: float, trend: str):
        """Print detailed market scan summary for Gold"""
        print(f"\n{'=' * 60}")
        print(f"🔍 GOLD MARKET SCAN - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"📈 Price: {self.current_price:.2f} | RSI: {rsi:.1f}")
        print(f"📊 Higher TF Trend: {trend.upper()}")
        print(f"📜 Detected Patterns:")
        for pattern, detected in patterns.items():
            if detected: print(f" - {pattern.replace('_', ' ').title()}")
        if not any(patterns.values()):
            print(" - No significant patterns detected")
        print(f"📉 Support/Resistance:")
        print(f" - Support Levels: {', '.join(f'{s:.2f}' for s in self.swing_points['support'][:3])}" if self.swing_points['support'] else " - No support levels detected")
        print(f" - Resistance Levels: {', '.join(f'{r:.2f}' for r in self.swing_points['resistance'][-3:])}" if self.swing_points['resistance'] else " - No resistance levels detected")
        print(f"{'=' * 60}")

    def execute_trade(self, direction: str, pattern: str):
        """Execute trade with SME concept and enhanced risk management"""
        # Check trade cooldown
        if (datetime.now() - self.last_trade_time).total_seconds() < self.trade_cooldown_minutes * 60:
            remaining = self.trade_cooldown_minutes - int((datetime.now() - self.last_trade_time).total_seconds() / 60)
            print(f"\n⏳ Trade Cooldown Active: {remaining} minutes remaining")
            return
            
        if self.active_position_exists():
            print("\n⚠️ Trade Aborted: Existing position detected")
            return

        # Calculate trade parameters
        tick = mt5.symbol_info_tick(self.symbol)
        entry_price = tick.ask if direction == 'buy' else tick.bid
        sl_price, sl_pips = self.calculate_stop_loss(direction)
        
        # Implement SME (Support, Momentum, Entry) concept for better TP placement
        # Look for next significant level for take profit instead of fixed 1:3
        if direction == 'buy':
            # Find next resistance level above entry or project 1:3 R:R
            resistances = [r for r in self.swing_points['resistance'] if r > entry_price]
            if resistances:
                # Find nearest resistance that gives at least 1:2 risk:reward
                min_tp_distance = (entry_price - sl_price) * 2
                valid_resistances = [r for r in resistances if r - entry_price >= min_tp_distance]
                if valid_resistances:
                    tp_price = min(valid_resistances)  # Nearest valid resistance
                else:
                    # No valid resistance found, use 1:3
                    tp_price = entry_price + (entry_price - sl_price) * 3
            else:
                tp_price = entry_price + (entry_price - sl_price) * 3
        else:  # Sell trade
            # Find next support level below entry or project 1:3 R:R
            supports = [s for s in self.swing_points['support'] if s < entry_price]
            if supports:
                # Find nearest support that gives at least 1:2 risk:reward
                min_tp_distance = (sl_price - entry_price) * 2
                valid_supports = [s for s in supports if entry_price - s >= min_tp_distance]
                if valid_supports:
                    tp_price = max(valid_supports)  # Nearest valid support
                else:
                    # No valid support found, use 1:3
                    tp_price = entry_price - (sl_price - entry_price) * 3
            else:
                tp_price = entry_price - (sl_price - entry_price) * 3
        
        # Calculate actual risk:reward ratio
        rr_ratio = abs(tp_price - entry_price) / abs(entry_price - sl_price)
        
        # Ensure minimum R:R of 1:2
        if rr_ratio < 2:
            if direction == 'buy':
                tp_price = entry_price + (entry_price - sl_price) * 2
            else:
                tp_price = entry_price - (sl_price - entry_price) * 2
            rr_ratio = 2.0

        # Print trade details
        print(f"\n{'=' * 60}")
        print(f"🚀 EXECUTING {direction.upper()} TRADE ON GOLD")
        print(f"📈 Pattern: {pattern.replace('_', ' ').title()}")
        print(f"💰 Entry Price: {entry_price:.2f}")
        print(f"⛔ Stop Loss: {sl_price:.2f} ({sl_pips:.1f} pips)")
        print(f"🎯 Take Profit: {tp_price:.2f} (R:R {rr_ratio:.1f}:1)")
        print(f"📦 Position Size: {self.fixed_lot_size:.2f} lots (FIXED)")
        print(f"{'=' * 60}\n")

        # Prepare trade request
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": self.fixed_lot_size,
            "type": mt5.ORDER_TYPE_BUY if direction == 'buy' else mt5.ORDER_TYPE_SELL,
            "price": entry_price,
            "sl": sl_price,
            "tp": tp_price,
            "deviation": 20,
            "magic": 202311,
            "comment": f"GOLD_{pattern}",
            "type_time": mt5.ORDER_TIME_GTC,
        }

        # Send trade order
        result = mt5.order_send(request)
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            logging.error(f"Trade failed: {result.comment}")
            print(f"❌ Trade Failed: {result.comment}")
        else:
            logging.info(f"Trade executed: {direction} {self.fixed_lot_size} lots | SL: {sl_price:.2f} | TP: {tp_price:.2f} | R:R {rr_ratio:.1f}:1")
            print(f"✅ Trade Executed Successfully!")
            self.last_trade_time = datetime.now()

    def active_position_exists(self) -> bool:
        """Check for existing positions"""
        positions = mt5.positions_get(symbol=self.symbol)
        return len(positions) > 0

    def manage_existing_trades(self):
        """Manage existing trades with trailing stop loss and breakeven features"""
        positions = mt5.positions_get(symbol=self.symbol)
        if not positions:
            return
            
        for position in positions:
            # Skip positions for other symbols
            if position.symbol != self.symbol:
                continue
                
            # Get current price
            tick = mt5.symbol_info_tick(self.symbol)
            current_price = tick.bid if position.type == mt5.ORDER_TYPE_BUY else tick.ask
            
            # Calculate profit in terms of risk (relative to initial stop loss)
            entry_price = position.price_open
            initial_sl = position.sl
            risk = abs(entry_price - initial_sl)
            current_profit = abs(current_price - entry_price)
            profit_risk_ratio = current_profit / risk if risk > 0 else 0
            
            # Move to breakeven when profit reaches 1.5x risk
            if self.breakeven_at > 0 and profit_risk_ratio >= self.breakeven_at:
                # Check if SL is not already at breakeven or better
                if (position.type == mt5.ORDER_TYPE_BUY and position.sl < entry_price) or \
                   (position.type == mt5.ORDER_TYPE_SELL and (position.sl > entry_price or position.sl == 0)):
                    
                    # Calculate new SL at breakeven + a small buffer (5 points)
                    new_sl = entry_price + (5 * self.symbol_info.point) if position.type == mt5.ORDER_TYPE_BUY else \
                             entry_price - (5 * self.symbol_info.point)
                             
                    # Update SL
                    request = {
                        "action": mt5.TRADE_ACTION_SLTP,
                        "symbol": position.symbol,
                        "position": position.ticket,
                        "sl": new_sl,
                        "tp": position.tp
                    }
                    result = mt5.order_send(request)
                    if result.retcode == mt5.TRADE_RETCODE_DONE:
                        logging.info(f"Moved to breakeven: Ticket {position.ticket}, new SL: {new_sl:.2f}")
                        print(f"✅ Position {position.ticket} moved to breakeven. New SL: {new_sl:.2f}")
                    else:
                        logging.error(f"Failed to modify SL: {result.comment}")
            
            # Apply trailing stop if enabled
            elif self.trailing_sl and profit_risk_ratio >= 1.0:
                # Calculate trailing distance based on ATR or fixed pips
                trailing_distance = risk  # Use initial risk as trailing distance
                
                if position.type == mt5.ORDER_TYPE_BUY:
                    new_sl = current_price - trailing_distance
                    # Only move SL up, never down
                    if new_sl > position.sl:
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": position.symbol,
                            "position": position.ticket,
                            "sl": new_sl,
                            "tp": position.tp
                        }
                        result = mt5.order_send(request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            logging.info(f"Updated trailing SL: Ticket {position.ticket}, new SL: {new_sl:.2f}")
                            print(f"📈 Trailing SL updated for position {position.ticket}. New SL: {new_sl:.2f}")
                else:  # SELL position
                    new_sl = current_price + trailing_distance
                    # Only move SL down, never up
                    if new_sl < position.sl or position.sl == 0:
                        request = {
                            "action": mt5.TRADE_ACTION_SLTP,
                            "symbol": position.symbol,
                            "position": position.ticket,
                            "sl": new_sl,
                            "tp": position.tp
                        }
                        result = mt5.order_send(request)
                        if result.retcode == mt5.TRADE_RETCODE_DONE:
                            logging.info(f"Updated trailing SL: Ticket {position.ticket}, new SL: {new_sl:.2f}")
                            print(f"📉 Trailing SL updated for position {position.ticket}. New SL: {new_sl:.2f}")

    def run_strategy(self):
        """Main strategy execution loop for Gold trading, optimized for M5 timeframe"""
        print("\n🚀 Starting IMPROVED Gold Price Action Trading Strategy with Enhanced SL/TP")
        print("📡 Scanning M5 chart for trading opportunities...\n")

        while True:
            try:
                # Refresh data every 5 seconds
                if (datetime.now() - self.last_scan_time).seconds >= 5:
                    self.refresh_market_data()
                    self.last_scan_time = datetime.now()

                    # Market analysis
                    patterns = self.detect_price_patterns()
                    rsi = self.calculate_rsi()
                    trend = self.get_higher_tf_trend()
                    
                    # Check volume
                    volume_ok = self.base_df['tick_volume'].iloc[-1] > \
                                self.base_df['tick_volume'].rolling(10).mean().iloc[-1] * 0.7
                    
                    # Manage existing trades first
                    self.manage_existing_trades()
                    
                    # Print scan results
                    self.print_scan_summary(patterns, rsi, trend)

                    # Trade logic with improved conditions
                    
                    # Bullish signals - more selective with trend alignment
                    if 'bullish' in trend and rsi < self.rsi_overbought:
                        if patterns['bullish_engulf'] or patterns['bullish_pin']:
                            self.execute_trade('buy', 'bullish_pattern')
                        elif patterns['doji'] and self.base_df['close'].iloc[-1] > self.base_df['open'].iloc[-1]:
                            self.execute_trade('buy', 'bullish_doji')

                    # Bearish signals - more selective with trend alignment
                    elif 'bearish' in trend and rsi > self.rsi_oversold:
                        if patterns['bearish_engulf'] or patterns['bearish_pin']:
                            self.execute_trade('sell', 'bearish_pattern')
                        elif patterns['doji'] and self.base_df['close'].iloc[-1] < self.base_df['open'].iloc[-1]:
                            self.execute_trade('sell', 'bearish_doji')

                time.sleep(1)  # Check more frequently

            except Exception as e:
                logging.error(f"Main loop error: {str(e)}")
                print(f"⚠️ Error occurred: {str(e)}")
                time.sleep(10)  # Reduced from 30 seconds

# Gold Price Action Trader with fixed lot size of 0.01
if __name__ == "__main__":
    try:
        # Try common MT5 Gold symbol variations
        symbols_to_try = ['XAUUSDm', 'GOLD', 'XAUUSD']
        for symbol in symbols_to_try:
            try:
                trader = XAUUSDPriceActionTrader(symbol, fixed_lot_size=0.01)
                trader.run_strategy()
                break
            except ValueError:
                continue
    except Exception as e:
        print(f"\n❌ Critical Error: {str(e)}")
        print("Troubleshooting Steps:")
        print("1. Ensure MT5 is running and logged in")
        print("2. Check internet connection")
        print("3. Verify XAUUSDm/GOLD exists in Market Watch")
        print("4. Check API connection settings")
