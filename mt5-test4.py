import MetaTrader5 as mt5
import pandas as pd
import time

# Initialize MetaTrader 5
if not mt5.initialize():
    print("Failed to initialize MetaTrader 5.")
    exit()

count = 0
# Trading parameters
symbol = "XAUUSDm"
lot = 0.01
atr_period = 14
stop_loss_multiplier = 1.0  # Base stop loss multiplier
take_profit_multiplier = 3.0  # TP always 3x SL
deviation = 20
breakout_period = 5  # Number of candles to calculate breakout range

while True:
    # Ensure the symbol is available
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None or not symbol_info.visible:
        print(f"Symbol {symbol} is not available or not visible.")
        mt5.shutdown()
        exit()

    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)

    # Fetch historical data (5-minute candles)
    rates_5m = mt5.copy_rates_from_pos(symbol, mt5.TIMEFRAME_M5, 0, 200)

    if rates_5m is None or len(rates_5m) == 0:
        print("No data retrieved. Retrying...")
        time.sleep(60)
        continue

    data_5m = pd.DataFrame(rates_5m)
    data_5m["time"] = pd.to_datetime(data_5m["time"], unit="s")

    # Calculate ATR for 5-minute data
    data_5m["tr"] = data_5m["high"] - data_5m["low"]
    data_5m["atr"] = data_5m["tr"].rolling(window=atr_period).mean()

    if len(data_5m) < max(breakout_period, atr_period):
        print("Not enough data for calculations. Retrying...")
        time.sleep(60)
        continue

    # Identify breakout range (high and low of the last 'breakout_period' candles)
    breakout_high = data_5m["high"].iloc[-breakout_period:].max()
    breakout_low = data_5m["low"].iloc[-breakout_period:].min()

    # Get current prices
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("Failed to retrieve current prices. Retrying...")
        time.sleep(1)
        continue

    ask_price = tick.ask
    bid_price = tick.bid

    # Determine breakout conditions
    buy_condition = ask_price > breakout_high
    sell_condition = bid_price < breakout_low

    # Calculate Stop Loss and Take Profit
    atr_5m = data_5m["atr"].iloc[-1]
    stop_loss_points = atr_5m * stop_loss_multiplier
    take_profit_points = stop_loss_points * take_profit_multiplier

    # Adjust for minimum distance
    min_distance = max(symbol_info.trade_stops_level * symbol_info.point, 10 * symbol_info.point)
    stop_loss_points = max(stop_loss_points, min_distance)
    take_profit_points = max(take_profit_points, stop_loss_points * 3)

    tp_price = None
    sl_price = None
    request = None

    positions_total = mt5.positions_total()
    if positions_total == 0:  # Only if no position is already open
        if buy_condition:  # Buy breakout
            print("Buying breakout...")
            tp_price = ask_price + take_profit_points
            sl_price = ask_price - stop_loss_points

            if sl_price >= ask_price or tp_price <= ask_price:
                print("Invalid stop levels for Buy order. Skipping...")
                continue

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lot,
                "type": mt5.ORDER_TYPE_BUY,
                "price": ask_price,
                "tp": tp_price,
                "sl": sl_price,
                "deviation": deviation,
                "magic": 3092000,
                "comment": "Buy breakout order",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

        elif sell_condition:  # Sell breakout
            print("Selling breakout...")
            tp_price = bid_price - take_profit_points
            sl_price = bid_price + stop_loss_points

            if sl_price <= bid_price or tp_price >= bid_price:
                print("Invalid stop levels for Sell order. Skipping...")
                continue

            request = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": lot,
                "type": mt5.ORDER_TYPE_SELL,
                "price": bid_price,
                "tp": tp_price,
                "sl": sl_price,
                "deviation": deviation,
                "magic": 3092000,
                "comment": "Sell breakout order",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": mt5.ORDER_FILLING_IOC,
            }

        else:
            print("No breakout condition met. Skipping...")
            time.sleep(2)
            continue

        # Send trade request
        result = mt5.order_send(request)
        if result and result.retcode == mt5.TRADE_RETCODE_DONE:
            print(f"Order executed: TP = {tp_price}, SL = {sl_price}")
        else:
            print(f"Order execution failed: {result.comment if result else 'No response'}")
    else:
        print("Position already open. Skipping...")

    time.sleep(2)  # Wait 2 seconds before checking again
