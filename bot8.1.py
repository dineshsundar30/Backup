import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import time
import talib

# Main settings
magic = 12345678
account_id = 243279052

# Symbol settings
symbol = 'EURUSDm'
sl_multiplier = 13

lot = 0.1
add_lot = 0.01
min_deleverage = 15
deleverage_steps = 7
take_profit_short = 21
sl_short = take_profit_short * sl_multiplier

# Supertrend settings
atr_period = 10
atr_multiplier = 3

def calculate_supertrend(df, period=10, multiplier=3):
    """Calculate Super Trend using TA-Lib"""
    
    # Calculate ATR using TA-Lib
    df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=period)
    
    # Calculate basic upper and lower bands
    hl2 = (df['high'] + df['low']) / 2
    df['basic_ub'] = hl2 + (multiplier * df['atr'])
    df['basic_lb'] = hl2 - (multiplier * df['atr'])
    
    # Initialize Supertrend columns
    df['final_ub'] = df['basic_ub']
    df['final_lb'] = df['basic_lb']
    df['supertrend'] = df['basic_ub']
    df['supertrend_direction'] = 1
    
    # Calculate Final Upper Band
    for i in range(period, len(df)):
        df.loc[df.index[i], 'final_ub'] = df.loc[df.index[i], 'basic_ub'] if (
            df.loc[df.index[i], 'basic_ub'] < df.loc[df.index[i-1], 'final_ub']
            or df.loc[df.index[i-1], 'close'] > df.loc[df.index[i-1], 'final_ub']
        ) else df.loc[df.index[i-1], 'final_ub']
    
    # Calculate Final Lower Band
    for i in range(period, len(df)):
        df.loc[df.index[i], 'final_lb'] = df.loc[df.index[i], 'basic_lb'] if (
            df.loc[df.index[i], 'basic_lb'] > df.loc[df.index[i-1], 'final_lb']
            or df.loc[df.index[i-1], 'close'] < df.loc[df.index[i-1], 'final_lb']
        ) else df.loc[df.index[i-1], 'final_lb']
    
    # Calculate Supertrend
    for i in range(period, len(df)):
        if (
            df.loc[df.index[i-1], 'supertrend'] == df.loc[df.index[i-1], 'final_ub']
            and df.loc[df.index[i], 'close'] <= df.loc[df.index[i], 'final_ub']
        ):
            df.loc[df.index[i], 'supertrend'] = df.loc[df.index[i], 'final_ub']
        elif (
            df.loc[df.index[i-1], 'supertrend'] == df.loc[df.index[i-1], 'final_ub']
            and df.loc[df.index[i], 'close'] > df.loc[df.index[i], 'final_ub']
        ):
            df.loc[df.index[i], 'supertrend'] = df.loc[df.index[i], 'final_lb']
        elif (
            df.loc[df.index[i-1], 'supertrend'] == df.loc[df.index[i-1], 'final_lb']
            and df.loc[df.index[i], 'close'] >= df.loc[df.index[i], 'final_lb']
        ):
            df.loc[df.index[i], 'supertrend'] = df.loc[df.index[i], 'final_lb']
        elif (
            df.loc[df.index[i-1], 'supertrend'] == df.loc[df.index[i-1], 'final_lb']
            and df.loc[df.index[i], 'close'] < df.loc[df.index[i], 'final_lb']
        ):
            df.loc[df.index[i], 'supertrend'] = df.loc[df.index[i], 'final_ub']
        
        # Set trend direction
        df.loc[df.index[i], 'supertrend_direction'] = 1 if df.loc[df.index[i], 'supertrend'] <= df.loc[df.index[i], 'close'] else -1
    
    return df

# Init
if not mt5.initialize():
    print('initialize() failed, error code =', mt5.last_error())
    quit()

# Timeframe settings
timeframe = mt5.TIMEFRAME_M1

selected = mt5.symbol_select(symbol)
if not selected:
    print('symbol_select({}) failed, error code = {}'.format(symbol, mt5.last_error()))
    quit()

def get_indicators():
    bars = mt5.copy_rates_from_pos(symbol, timeframe, 0, 240)
    if bars is None:
        print('copy_rates_from_pos() failed, error code =', mt5.last_error())
        quit()

    df = pd.DataFrame(bars)
    df.set_index(pd.to_datetime(df['time'], unit='s'), inplace=True)
    df.drop(columns=['time'], inplace=True)
    
    # Calculate SMAs using TA-Lib
    df['sma_6H'] = talib.SMA(df['high'], timeperiod=6)
    df['sma_6L'] = talib.SMA(df['low'], timeperiod=6)
    df['sma_33'] = talib.SMA(df['close'], timeperiod=33)
    df['sma_60'] = talib.SMA(df['close'], timeperiod=60)
    df['sma_120'] = talib.SMA(df['close'], timeperiod=120)
    df['sma_240'] = talib.SMA(df['close'], timeperiod=240)
    
    # Calculate Supertrend
    df = calculate_supertrend(df, atr_period, atr_multiplier)
    
    global sma6H, sma6L, sma33, sma60, sma120, sma240, supertrend, supertrend_direction
    sma6H = df['sma_6H'].iloc[-1]
    sma6L = df['sma_6L'].iloc[-1]
    sma33 = df['sma_33'].iloc[-1]
    sma60 = df['sma_60'].iloc[-1]
    sma120 = df['sma_120'].iloc[-1]
    sma240 = df['sma_240'].iloc[-1]
    supertrend = df['supertrend'].iloc[-1]
    supertrend_direction = df['supertrend_direction'].iloc[-1]

def get_position_count():
    positions = mt5.positions_get(symbol=symbol)
    return len(positions) if positions is not None else 0

def get_position_data():
    positions = mt5.positions_get(symbol=symbol)
    if positions == None or len(positions) == 0:
        return None, None, None, None

    position = positions[0]  # Get first position
    post_dict = position._asdict()
    return (
        post_dict['price_open'],
        post_dict['identifier'],
        post_dict['volume'],
        post_dict['type']  # Return position type (buy/sell)
    )

def get_ask_bid():
    tick = mt5.symbol_info_tick(symbol)
    return tick.ask, tick.bid

point = mt5.symbol_info(symbol).point
deviation = 20

# Order templates
def create_order(order_type, volume, price, sl, tp):
    return {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": volume,
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": deviation,
        "magic": magic,
        "comment": f"python {'buy' if order_type == mt5.ORDER_TYPE_BUY else 'sell'}",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

def create_sltp_request(position_id, order_type, volume, price, sl, tp):
    return {
        "action": mt5.TRADE_ACTION_SLTP,
        "symbol": symbol,
        "volume": float(volume),
        "type": order_type,
        "position": position_id,
        "sl": sl,
        "tp": tp,
        "magic": magic,
        "comment": f"Change stop loss for {'Buy' if order_type == mt5.ORDER_TYPE_BUY else 'Sell'} position",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }

while True:
    try:
        # Get current market data
        get_indicators()
        ask, bid = get_ask_bid()
        position_count = mt5.positions_total()
        pos_price, identifier, volume, pos_type = get_position_data() if position_count > 0 else (0, 0, 0, None)

        # Check if we can take new positions
        if position_count == 0:
            # Sell condition with Supertrend
            good_sell_condition = ask > sma6H and supertrend_direction == -1

            # Buy condition with Supertrend
            good_buy_condition = bid < sma6L and supertrend_direction == 1

            if good_sell_condition:
                # Create sell order
                sell_order = create_order(
                    mt5.ORDER_TYPE_SELL,
                    lot,
                    bid,
                    ask + sl_short * point,
                    ask - take_profit_short * point
                )
                result = mt5.order_send(sell_order)
                print("Opening sell position...")

            elif good_buy_condition:
                # Create buy order
                buy_order = create_order(
                    mt5.ORDER_TYPE_BUY,
                    lot,
                    ask,
                    bid - sl_short * point,
                    bid + take_profit_short * point
                )
                result = mt5.order_send(buy_order)
                print("Opening buy position...")
        elif position_count > 0:
            time.sleep(10)
            print("Position is already open")
        
        time.sleep(0.1)
        
    except Exception as e:
        print(f"Error occurred: {e}")
        time.sleep(1)
