import numpy as np
import pandas as pd
import time
import MetaTrader5 as mt5
import talib
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_squared_error, r2_score
import pytz
from datetime import datetime
import sys

# Trading parameters - Customizable
SYMBOL = "XAUUSDm"  # Change to your desired pair (e.g., "EURUSD", "XAUUSD", "GBPJPY", etc.)
TIMEFRAME = mt5.TIMEFRAME_M5  # Change to your preferred timeframe
LOT_SIZE = 0.01  # Fixed lot size as requested
MAX_ACTIVE_TRADES = 1  # Only one trade at a time

# Minimum risk-reward ratio (will be enforced)
MIN_RISK_REWARD_RATIO = 2.0

# ATR periods for volatility calculation
ATR_PERIOD = 14


def initialize_mt5(account, password, server):
    """Initialize connection to MetaTrader 5"""
    if not mt5.initialize():
        print("[ERROR] MT5 initialization failed")
        mt5.shutdown()
        return False

    # Login to the trading account
    authorized = mt5.login(account, password=password, server=server)
    if not authorized:
        print(f"[ERROR] Login failed: {mt5.last_error()}")
        mt5.shutdown()
        return False

    print(f"[INFO] Connected to account #{account}")
    return True


def get_symbol_info(symbol):
    """Get detailed information about the trading symbol"""
    info = mt5.symbol_info(symbol)
    if info is None:
        print(f"[ERROR] Failed to get info for {symbol}: {mt5.last_error()}")
        return None

    # Create a dictionary with relevant information
    symbol_data = {
        "point": info.point,
        "digits": info.digits,
        "contract_size": info.trade_contract_size,
        "currency": info.currency_profit,
        "tick_size": info.trade_tick_size,
        "tick_value": info.trade_tick_value,
        "min_volume": info.volume_min,
        "max_volume": info.volume_max,
        "volume_step": info.volume_step
    }

    # Determine if it's forex, gold, or other
    if "USD" in symbol and len(symbol) == 6:
        symbol_data["type"] = "forex"
    elif "XAUUSD" in symbol:
        symbol_data["type"] = "gold"
    else:
        symbol_data["type"] = "other"

    return symbol_data


def calculate_point_value(symbol_data):
    """Calculate the USD value of one point for the given symbol"""
    # For most forex pairs, one pip is typically 0.0001 (10^-4) or 0.01 (10^-2) for JPY pairs
    # One pip = 10 points for 5-digit brokers

    if symbol_data["type"] == "forex":
        # For standard forex pairs (approximate)
        return symbol_data["tick_value"] / symbol_data["tick_size"] * symbol_data["point"]
    else:
        # For other instruments, use tick value
        return symbol_data["tick_value"]


def get_historical_data(symbol, timeframe, num_bars=1000):
    """Get historical price data from MT5"""
    # Define timezone
    timezone = pytz.timezone("UTC")

    # Get current time in UTC timezone
    now = datetime.now(timezone)

    # Get historical data
    rates = mt5.copy_rates_from(symbol, timeframe, now, num_bars)

    if rates is None or len(rates) == 0:
        print(f"[ERROR] Failed to get historical data: {mt5.last_error()}")
        return None

    # Convert to pandas DataFrame
    df = pd.DataFrame(rates)
    df['time'] = pd.to_datetime(df['time'], unit='s')
    df.set_index('time', inplace=True)

    return df


def prepare_features(data):
    """Feature engineering based on the same logic as original code"""
    df = data.copy()

    # Calculate features
    df['momentum'] = df['close'].diff()
    df['rsi'] = talib.RSI(df['close'], timeperiod=14)
    df['macd'], df['signal'], df['hist'] = talib.MACD(df['close'], fastperiod=12, slowperiod=26, signalperiod=9)

    # Calculate ATR for volatility measurement
    df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ATR_PERIOD)

    # Drop rows with NaN values that result from calculations
    df.dropna(inplace=True)

    return df


def train_model(data):
    """Train Random Forest model as in original code"""
    # Use all but the last 100 records for training
    split_idx = len(data) - 100 if len(data) > 100 else int(len(data) * 0.8)

    # Features and target
    features = ['momentum', 'rsi', 'macd', 'signal', 'hist']
    X_train = data.iloc[:split_idx][features]
    y_train = data.iloc[:split_idx]['close']

    # Train model
    model = RandomForestRegressor(n_estimators=100, random_state=42)
    model.fit(X_train, y_train)

    # Evaluate model
    X_test = data.iloc[split_idx:][features]
    y_test = data.iloc[split_idx:]['close']
    y_pred = model.predict(X_test)

    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    print(f"[INFO] Model Training Complete - MSE: {mse:.6f}, R²: {r2:.6f}")

    return model, features


def get_active_positions(symbol):
    """Get number of active positions for the symbol"""
    positions = mt5.positions_get(symbol=symbol)

    if positions is None:
        if mt5.last_error() != 0:  # Only print if there's an actual error
            print(f"[ERROR] Failed to get positions: {mt5.last_error()}")
        return 0

    return len(positions)


def calculate_dynamic_sl_tp(symbol_data, current_data, entry_price, order_type):
    """
    Calculate Stop Loss and Take Profit dynamically based on market volatility (ATR)
    """
    # Get current ATR value as a measure of volatility
    current_atr = current_data['atr'].iloc[-1]

    # Calculate point value
    point_value = calculate_point_value(symbol_data)

    # Base SL on current ATR (typically 1-2x ATR)
    # For more volatile markets, use lower multiple
    if symbol_data["type"] == "gold":
        atr_sl_multiplier = 1.5  # Gold can be volatile
    else:
        atr_sl_multiplier = 1.0  # Standard for forex

    # Calculate SL in price terms based on ATR
    sl_price_movement = current_atr * atr_sl_multiplier

    # Convert SL price movement to points
    sl_points = int(sl_price_movement / symbol_data["point"])

    # Ensure minimum SL distance (at least 10 points)
    min_sl_points = 20
    sl_points = max(sl_points, min_sl_points)

    # TP must be at least MIN_RISK_REWARD_RATIO times the SL (e.g., 2x)
    tp_points = int(sl_points * MIN_RISK_REWARD_RATIO)

    # Calculate actual SL/TP prices
    if order_type == mt5.ORDER_TYPE_BUY:
        sl_price = entry_price - sl_points * symbol_data["point"]
        tp_price = entry_price + tp_points * symbol_data["point"]
    else:  # SELL order
        sl_price = entry_price + sl_points * symbol_data["point"]
        tp_price = entry_price - tp_points * symbol_data["point"]

    # Round to the correct number of digits for the instrument
    sl_price = round(sl_price, symbol_data["digits"])
    tp_price = round(tp_price, symbol_data["digits"])

    # Calculate actual risk/reward in USD
    risk_usd = sl_points * point_value * LOT_SIZE
    reward_usd = tp_points * point_value * LOT_SIZE

    return sl_price, tp_price, sl_points, tp_points, risk_usd, reward_usd


def place_trade(symbol, symbol_data, lot_size, prediction, current_price, order_type, current_data):
    """Place a trade in MT5 with dynamic SL and TP"""
    # Calculate dynamic Stop Loss and Take Profit levels
    sl, tp, sl_points, tp_points, risk_usd, reward_usd = calculate_dynamic_sl_tp(
        symbol_data, current_data, current_price, order_type
    )

    # Fill order request structure
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": lot_size,
        "type": order_type,
        "price": current_price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,  # Allowed slippage in points
        "magic": 123456,  # Expert Advisor ID
        "comment": "Python Trading Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_FOK,
    }

    # Send the order
    result = mt5.order_send(request)

    # Check result
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"[ERROR] Order failed: {result.retcode}, {result.comment}")
        return False

    order_type_str = 'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'
    print(f"[TRADE] {order_type_str} Order placed - Ticket #{result.order}")
    print(
        f"[TRADE] Entry: {current_price:.{symbol_data['digits']}f}, SL: {sl:.{symbol_data['digits']}f}, TP: {tp:.{symbol_data['digits']}f}")
    print(f"[TRADE] SL Distance: {sl_points} points, TP Distance: {tp_points} points")
    print(f"[TRADE] Prediction: {prediction:.{symbol_data['digits']}f}")
    print(
        f"[TRADE] Risk: ${risk_usd:.2f}, Reward: ${reward_usd:.2f}, Ratio: 1:{reward_usd / risk_usd:.2f}")
    print(f"[TRADE] Current ATR: {current_data['atr'].iloc[-1]:.{symbol_data['digits']}f}")

    return True


def generate_trading_signal(model, features, current_data, last_close):
    """Generate trading signal based on model prediction"""
    # Extract features for prediction
    X = current_data[features].iloc[-1:].values

    # Make prediction
    prediction = model.predict(X)[0]

    # Compare prediction to current price
    if prediction > last_close:
        return mt5.ORDER_TYPE_BUY, prediction
    else:
        return mt5.ORDER_TYPE_SELL, prediction


def get_signal_threshold(symbol_data, current_data):
    """Determine appropriate signal threshold based on symbol type and volatility"""
    # Get current ATR value
    current_atr = current_data['atr'].iloc[-1]

    # Get current price
    current_price = current_data['close'].iloc[-1]

    # Calculate ATR as percentage of price
    atr_percent = (current_atr / current_price) * 100

    # Base threshold on symbol type but adjust for current volatility
    if symbol_data["type"] == "forex":
        base_threshold = 0.01  # 0.01% for regular forex pairs
    elif symbol_data["type"] == "gold":
        base_threshold = 0.05  # 0.05% for gold
    else:
        base_threshold = 0.03  # 0.03% for other instruments

    # Adjust threshold based on current ATR (more volatile = higher threshold)
    # For example, if ATR is high, we want a stronger signal before trading
    adjusted_threshold = base_threshold * (1 + atr_percent)

    return adjusted_threshold


def main():
    # Account credentials - replace with your actual credentials
    account = 204296999
    password = "dk@Demo07"
    server = "Exness-MT5Trial7"

    print("[STARTING] MT5 Universal Trading Bot with Dynamic SL/TP")
    print(f"[CONFIG] Symbol: {SYMBOL}, Lot Size: {LOT_SIZE}, Max Positions: {MAX_ACTIVE_TRADES}")
    print(f"[CONFIG] Minimum Risk-Reward Ratio: 1:{MIN_RISK_REWARD_RATIO}")
    print(f"[CONFIG] ATR Period: {ATR_PERIOD}")

    # Initialize connection to MT5
    if not initialize_mt5(account, password, server):
        return

    try:
        # Get symbol information
        symbol_data = get_symbol_info(SYMBOL)
        if symbol_data is None:
            print(f"[ERROR] Unable to get information for {SYMBOL}. Exiting.")
            mt5.shutdown()
            return

        # Calculate and display symbol-specific info
        point_value = calculate_point_value(symbol_data)

        print(f"[INFO] Symbol Type: {symbol_data['type']}")
        print(f"[INFO] Point Value: ${point_value:.6f}")

        # Initial data load and model training
        print("[INFO] Loading historical data...")
        historical_data = get_historical_data(SYMBOL, TIMEFRAME)
        if historical_data is None:
            print("[ERROR] Failed to get historical data. Exiting.")
            mt5.shutdown()
            return

        # Prepare features
        print("[INFO] Preparing features...")
        processed_data = prepare_features(historical_data)

        # Train model
        print("[INFO] Training model...")
        model, features = train_model(processed_data)

        print("[INFO] Trading bot active - Press Ctrl+C to stop")

        # Trading loop
        while True:
            try:
                # Check current number of active positions
                active_positions = get_active_positions(SYMBOL)

                if active_positions < MAX_ACTIVE_TRADES:
                    # Get latest data for trading decision
                    current_data = get_historical_data(SYMBOL, TIMEFRAME, 200)
                    if current_data is None:
                        continue

                    processed_current = prepare_features(current_data)

                    # Get last close price
                    last_close = processed_current['close'].iloc[-1]

                    # Calculate dynamic signal threshold based on current volatility
                    signal_threshold = get_signal_threshold(symbol_data, processed_current)
                    print(f"[INFO] Current Signal Threshold: {signal_threshold:.4f}%")

                    # Get current symbol info for latest prices
                    symbol_info_tick = mt5.symbol_info_tick(SYMBOL)
                    if symbol_info_tick is None:
                        print(f"[ERROR] Failed to get symbol tick info for {SYMBOL}")
                        continue

                    # Use appropriate price based on order type
                    # Will be determined after the signal, but get both ready
                    bid_price = symbol_info_tick.bid
                    ask_price = symbol_info_tick.ask

                    # Generate signal
                    order_type, prediction = generate_trading_signal(model, features, processed_current, last_close)

                    # Use appropriate price based on order type
                    current_price = ask_price if order_type == mt5.ORDER_TYPE_BUY else bid_price

                    # Determine if we should take a trade
                    price_diff_percent = abs(prediction - last_close) / last_close * 100

                    # Only trade if prediction differs from current price by more than threshold
                    if price_diff_percent > signal_threshold:
                        order_type_str = 'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'
                        print(f"[SIGNAL] {order_type_str} - Current: {last_close:.{symbol_data['digits']}f}, "
                              f"Predicted: {prediction:.{symbol_data['digits']}f}, Diff: {price_diff_percent:.3f}%")

                        # Place trade with dynamic SL/TP
                        place_trade(SYMBOL, symbol_data, LOT_SIZE, prediction, current_price, order_type,
                                    processed_current)
                    else:
                        # No significant signal
                        print(f"[INFO] No significant signal - Diff: {price_diff_percent:.3f}%")
                else:
                    print(f"[INFO] Position limit reached ({active_positions}/{MAX_ACTIVE_TRADES})")

                # Short delay between checks
                time.sleep(5)  # 5 seconds between updates

            except Exception as e:
                print(f"[ERROR] Loop error: {str(e)}")
                time.sleep(10)  # Wait 10 seconds before continuing after an error

    except KeyboardInterrupt:
        print("[INFO] Bot stopped by user")
    except Exception as e:
        print(f"[ERROR] Fatal error: {str(e)}")
    finally:
        # Clean up and shut down MT5 connection
        mt5.shutdown()
        print("[INFO] MT5 connection closed")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("[INFO] Bot stopped by user")
        sys.exit(0)
