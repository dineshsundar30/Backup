import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import talib
import time
from datetime import datetime, timedelta


def initialize_mt5():
    """Initialize MT5 connection"""
    if not mt5.initialize():
        print("MT5 initialization failed")
        return False
    return True


def get_symbol_info(symbol):
    """Get symbol specific information and adjust parameters"""
    info = mt5.symbol_info(symbol)
    if info is None:
        return None

    # Define parameters based on symbol type
    if 'USD' in symbol and len(symbol) == 6:  # Regular forex pair
        atr_multiplier = 2.0
        rr_ratio = 1.5
        lookback = 20
    else:  # Crypto or other instruments
        atr_multiplier = 2.5
        rr_ratio = 1.75
        lookback = 20

    return {
        'point': info.point,
        'digits': info.digits,
        'atr_multiplier': atr_multiplier,
        'rr_ratio': rr_ratio,
        'lookback': lookback,
        'contract_size': info.trade_contract_size
    }


def get_historical_data(symbol, timeframe, n_candles):
    """Get historical price data from MT5"""
    rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, n_candles)
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    if 'tick_volume' in df.columns:
        df['volume'] = df['tick_volume']
    else:
        df['volume'] = 0
    return df


def identify_hhll_pattern(df, lookback=20):
    """Identify HHLL pattern with TALib indicators"""
    df = df.copy()

    # TALib indicators
    df['ema20'] = talib.EMA(df['close'], timeperiod=20)
    df['ema50'] = talib.EMA(df['close'], timeperiod=50)
    df['rsi'] = talib.RSI(df['close'], timeperiod=14)
    df['macd'], df['macdsignal'], df['macdhist'] = talib.MACD(df['close'])
    df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)

    # Additional indicators for forex
    df['stoch_k'], df['stoch_d'] = talib.STOCH(df['high'], df['low'], df['close'])

    # Calculate Higher Highs and Lower Lows
    df['rolling_high'] = df['high'].rolling(window=lookback).max()
    df['rolling_low'] = df['low'].rolling(window=lookback).min()

    # Identify potential breakouts
    df['hh_breakout'] = (
            (df['close'] > df['rolling_high'].shift(1)) &  # Price breakout
            (df['close'] > df['ema20']) &  # Above EMA20
            (df['ema20'] > df['ema50']) &  # Bullish EMA cross
            (df['rsi'] > 50) &  # RSI confirms uptrend
            (df['macd'] > df['macdsignal']) &  # MACD confirms trend
            (df['stoch_k'] > df['stoch_d']) &  # Stochastic confirms
            (df['close'] > df['close'].shift(1))  # Current candle is bullish
    )

    df['ll_breakout'] = (
            (df['close'] < df['rolling_low'].shift(1)) &  # Price breakout
            (df['close'] < df['ema20']) &  # Below EMA20
            (df['ema20'] < df['ema50']) &  # Bearish EMA cross
            (df['rsi'] < 50) &  # RSI confirms downtrend
            (df['macd'] < df['macdsignal']) &  # MACD confirms trend
            (df['stoch_k'] < df['stoch_d']) &  # Stochastic confirms
            (df['close'] < df['close'].shift(1))  # Current candle is bearish
    )

    return df


def calculate_stop_loss_take_profit(df, entry_price, direction, symbol_info):
    """Calculate stop loss and take profit levels"""
    atr = df['atr'].iloc[-1]
    multiplier = symbol_info['atr_multiplier']
    rr_ratio = symbol_info['rr_ratio']

    if direction == 'BUY':
        stop_loss = entry_price - (multiplier * atr)
        take_profit = entry_price + (multiplier * rr_ratio * atr)
    else:
        stop_loss = entry_price + (multiplier * atr)
        take_profit = entry_price - (multiplier * rr_ratio * atr)

    # Round to symbol digits
    digits = symbol_info['digits']
    stop_loss = round(stop_loss, digits)
    take_profit = round(take_profit, digits)

    return stop_loss, take_profit


def place_order(symbol, order_type, lot_size, price, sl, tp):
    """Place trading order in MT5"""
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "magic": 234000,
        "comment": "HHLL Breakout",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order failed. Error code: {result.retcode}")
    return result


def check_open_positions(symbol):
    """Check if there are any open positions"""
    positions = mt5.positions_get(symbol=symbol)
    return len(positions) > 0 if positions is not None else False


def main():
    # Trading parameters - Can be changed to any symbol
    SYMBOL = "BTCUSDm"  # Change to your preferred symbol
    TIMEFRAME = mt5.TIMEFRAME_M15
    LOT_SIZE = 0.01

    # Initialize MT5
    if not initialize_mt5():
        return

    # Get symbol specific information
    symbol_info = get_symbol_info(SYMBOL)
    if symbol_info is None:
        print(f"Symbol {SYMBOL} not found!")
        return

    print(f"Starting HHLL Breakout Scanner for {SYMBOL}")

    while True:
        try:
            # Check if market is open
            if not mt5.symbol_info_tick(SYMBOL):
                print("Market is closed or symbol not found. Waiting...")
                time.sleep(60)
                continue

            # Check for open positions
            if check_open_positions(SYMBOL):
                print("Position already open. Waiting...")
                time.sleep(60)
                continue

            # Get latest data
            df = get_historical_data(SYMBOL, TIMEFRAME, 100)
            if df.empty:
                print("No data received. Waiting...")
                time.sleep(60)
                continue

            df = identify_hhll_pattern(df, symbol_info['lookback'])

            # Get current price
            tick = mt5.symbol_info_tick(SYMBOL)
            if tick is None:
                print("Cannot get current price. Waiting...")
                time.sleep(60)
                continue

            current_price = tick.ask

            # Check for breakout signals
            if df['hh_breakout'].iloc[-1]:
                sl, tp = calculate_stop_loss_take_profit(df, current_price, 'BUY', symbol_info)
                result = place_order(SYMBOL, mt5.ORDER_TYPE_BUY, LOT_SIZE,
                                     current_price, sl, tp)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"Buy order placed - Price: {current_price}, SL: {sl}, TP: {tp}")

            elif df['ll_breakout'].iloc[-1]:
                sl, tp = calculate_stop_loss_take_profit(df, current_price, 'SELL', symbol_info)
                result = place_order(SYMBOL, mt5.ORDER_TYPE_SELL, LOT_SIZE,
                                     current_price, sl, tp)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"Sell order placed - Price: {current_price}, SL: {sl}, TP: {tp}")

            time.sleep(60)  # Wait for 1 minute before next scan
            print("checking")

        except Exception as e:
            print(f"Error occurred: {str(e)}")
            time.sleep(60)
            continue


if __name__ == "__main__":
    main()
