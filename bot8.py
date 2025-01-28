import MetaTrader5 as mt5
import pandas as pd
import time
import ta

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


def get_sma():
    bars = mt5.copy_rates_from_pos(symbol, timeframe, 0, 240)
    if bars is None:
        print('copy_rates_from_pos() failed, error code =', mt5.last_error())
        quit()

    df = pd.DataFrame(bars)
    df.set_index(pd.to_datetime(df['time'], unit='s'), inplace=True)
    df.drop(columns=['time'], inplace=True)
    df['sma_6H'] = ta.trend.sma_indicator(df['high'], window=6)
    df['sma_6L'] = ta.trend.sma_indicator(df['low'], window=6)
    df['sma_33'] = ta.trend.sma_indicator(df['close'], window=33)
    df['sma_60'] = ta.trend.sma_indicator(df['close'], window=60)
    df['sma_120'] = ta.trend.sma_indicator(df['close'], window=120)
    df['sma_240'] = ta.trend.sma_indicator(df['close'], window=240)

    global sma6H, sma6L, sma33, sma60, sma120, sma240
    sma6H = df['sma_6H'].iloc[-1]
    sma6L = df['sma_6L'].iloc[-1]
    sma33 = df['sma_33'].iloc[-1]
    sma60 = df['sma_60'].iloc[-1]
    sma120 = df['sma_120'].iloc[-1]
    sma240 = df['sma_240'].iloc[-1]


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
    # Get current market data
    get_sma()
    ask, bid = get_ask_bid()
    position_count = mt5.positions_total()
    pos_price, identifier, volume, pos_type = get_position_data() if position_count > 0 else (0, 0, 0, None)

    # Check if we can take new positions
    if position_count == 0:
        # Sell condition (your original logic)
        good_sell_condition = ask > sma6H

        # Buy condition (mirror of sell condition)
        good_buy_condition = bid < sma6L

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
        print("position is already in open")
    ''' # Handle additional entries for existing position
    elif position_count == 1:
        if pos_type == mt5.ORDER_TYPE_SELL and ask > sma6H and sma6L > pos_price:
            # Additional sell entry
            additional_sell = create_order(
                mt5.ORDER_TYPE_SELL,
                add_lot,
                bid,
                pos_price + sl_short * point,
                pos_price - take_profit_short * point
            )
            sell_result = mt5.order_send(additional_sell)

            # Update stop loss
            if sell_result.retcode == mt5.TRADE_RETCODE_DONE:
                sltp_request = create_sltp_request(
                    identifier,
                    mt5.ORDER_TYPE_SELL,
                    volume,
                    pos_price,
                    pos_price + sl_short * point,
                    pos_price - take_profit_short * point
                )
                mt5.order_send(sltp_request)

        elif pos_type == mt5.ORDER_TYPE_BUY and bid < sma6L and sma6H < pos_price:
            # Additional buy entry
            additional_buy = create_order(
                mt5.ORDER_TYPE_BUY,
                add_lot,
                ask,
                pos_price - sl_short * point,
                pos_price + take_profit_short * point
            )
            buy_result = mt5.order_send(additional_buy)

            # Update stop loss
            if buy_result.retcode == mt5.TRADE_RETCODE_DONE:
                sltp_request = create_sltp_request(
                    identifier,
                    mt5.ORDER_TYPE_BUY,
                    volume,
                    pos_price,
                    pos_price - sl_short * point,
                    pos_price + take_profit_short * point
                )
                mt5.order_send(sltp_request)              '''

    time.sleep(0.1)
