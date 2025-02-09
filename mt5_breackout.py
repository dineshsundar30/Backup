import MetaTrader5 as mt5
import pandas as pd
import numpy as np
from datetime import datetime

def initialize_mt5():
    if not mt5.initialize():
        print("Failed to initialize MT5")
        mt5.shutdown()
        return False
    return True

def get_historical_data(symbol, timeframe, num_bars):
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, num_bars)
    if rates is None or len(rates) == 0:
        return None
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    return df

def calculate_indicators(df):
    # Calculate EMAs
    df['ema21'] = df['close'].ewm(span=21, adjust=False).mean()
    df['ema50'] = df['close'].ewm(span=50, adjust=False).mean()
    
    # Calculate RSI
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0)
    loss = -delta.where(delta < 0, 0)
    avg_gain = gain.rolling(14).mean()
    avg_loss = loss.rolling(14).mean()
    rs = avg_gain / avg_loss
    df['rsi'] = 100 - (100 / (1 + rs))
    
    # Calculate ATR
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    df['tr'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    df['atr'] = df['tr'].rolling(14).mean()
    
    # Calculate ADX
    plus_dm = df['high'].diff()
    minus_dm = -df['low'].diff()
    plus_dm[plus_dm < 0] = 0
    minus_dm[minus_dm < 0] = 0
    
    tr = df['tr'].rolling(14).sum()
    plus_di = 100 * (plus_dm.rolling(14).sum() / tr)
    minus_di = 100 * (minus_dm.rolling(14).sum() / tr)
    dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
    df['adx'] = dx.rolling(14).mean()
    
    return df.dropna()

def check_breakout_conditions(df, breakout_period=7):
    # Get recent price action
    recent_high = df['high'].iloc[-breakout_period-1:-1].max()
    recent_low = df['low'].iloc[-breakout_period-1:-1].min()
    
    # Current closed candle values
    current_close = df['close'].iloc[-1]
    current_ema21 = df['ema21'].iloc[-1]
    current_ema50 = df['ema50'].iloc[-1]
    current_rsi = df['rsi'].iloc[-1]
    current_adx = df['adx'].iloc[-1]
    current_atr = df['atr'].iloc[-1]
    
    # Breakout conditions
    long_condition = (current_close > recent_high) and \
                    (current_ema21 > current_ema50) and \
                    (current_rsi > 50) and \
                    (current_adx > 25)
    
    short_condition = (current_close < recent_low) and \
                     (current_ema21 < current_ema50) and \
                     (current_rsi < 50) and \
                     (current_adx > 25)
    
    return long_condition, short_condition, current_atr

def execute_trade(symbol, direction, atr):
    tick = mt5.symbol_info_tick(symbol)
    if not tick:
        print("Failed to get tick data")
        return False

    symbol_info = mt5.symbol_info(symbol)
    point = symbol_info.point
    lot = 0.01
    deviation = 20

    if direction == "BUY":
        price = tick.ask
        sl_price = price - (atr * 1.5)
        tp_price = price + (atr * 3.0)
    elif direction == "SELL":
        price = tick.bid
        sl_price = price + (atr * 1.5)
        tp_price = price - (atr * 3.0)
    else:
        return False

    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot,
        "type": mt5.ORDER_TYPE_BUY if direction == "BUY" else mt5.ORDER_TYPE_SELL,
        "price": price,
        "sl": sl_price,
        "tp": tp_price,
        "deviation": deviation,
        "magic": 2024,
        "comment": "ImmediateBreakout",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Trade failed: {result.comment}")
        return False
    print(f"Trade executed: {direction} at {price}")
    return True

def main():
    if not initialize_mt5():
        return

    symbol = "EURUSDm"
    timeframe = mt5.TIMEFRAME_M5
    num_bars = 200  # Enough for all indicator calculations
    
    # Get and prepare historical data
    df = get_historical_data(symbol, timeframe, num_bars)
    if df is None:
        print("Failed to get historical data")
        mt5.shutdown()
        return
    
    df = calculate_indicators(df)
    if len(df) < 50:
        print("Not enough data for analysis")
        mt5.shutdown()
        return
    
    # Check current market conditions
    long_cond, short_cond, atr = check_breakout_conditions(df)
    
    # Check existing positions
    positions = mt5.positions_get(symbol=symbol)
    if positions is None:
        print("Error checking existing positions")
        mt5.shutdown()
        return
    
    if len(positions) == 0:
        if long_cond:
            execute_trade(symbol, "BUY", atr)
        elif short_cond:
            execute_trade(symbol, "SELL", atr)
        else:
            print("No valid breakout conditions detected")
    else:
        print("Existing positions detected - no new trades")
    
    mt5.shutdown()

if __name__ == "__main__":
    main()
