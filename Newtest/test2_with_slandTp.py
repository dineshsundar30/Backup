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

# Trading parameters
SYMBOL = "EURUSD"  # Change to your desired forex pair
TIMEFRAME = mt5.TIMEFRAME_H1  # Change to your preferred timeframe
LOT_SIZE = 0.01  # Fixed lot size as requested
MAX_ACTIVE_TRADES = 1  # Only one trade at a time

# Risk management parameters
STOP_LOSS_PIPS = 20  # Stop loss in pips
TAKE_PROFIT_PIPS = 40  # Take profit in pips

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

def calculate_sl_tp(symbol, order_type, entry_price):
    """Calculate Stop Loss and Take Profit levels in price"""
    # Get symbol info to determine point value
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print(f"[ERROR] Failed to get symbol info for {symbol}")
        # Use default values as fallback
        point = 0.0001
    else:
        point = symbol_info.point
    
    # Calculate SL and TP based on the order type
    if order_type == mt5.ORDER_TYPE_BUY:
        sl = entry_price - STOP_LOSS_PIPS * point * 10  # *10 for converting pips to points for 5-digit brokers
        tp = entry_price + TAKE_PROFIT_PIPS * point * 10
    else:  # SELL order
        sl = entry_price + STOP_LOSS_PIPS * point * 10
        tp = entry_price - TAKE_PROFIT_PIPS * point * 10
    
    return round(sl, 5), round(tp, 5)

def place_trade(symbol, lot_size, prediction, current_price, order_type):
    """Place a trade in MT5 with SL and TP"""
    # Calculate Stop Loss and Take Profit levels
    sl, tp = calculate_sl_tp(symbol, order_type, current_price)
    
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
    print(f"[TRADE] Entry: {current_price:.5f}, SL: {sl:.5f}, TP: {tp:.5f}")
    print(f"[TRADE] Prediction: {prediction:.5f}, Risk: {STOP_LOSS_PIPS} pips, Reward: {TAKE_PROFIT_PIPS} pips")
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

def main():
    # Account credentials - replace with your actual credentials
    account = 12345678
    password = "your_password"
    server = "your_broker_server"
    
    print("[STARTING] Forex Trading Bot")
    print(f"[CONFIG] Symbol: {SYMBOL}, Lot Size: {LOT_SIZE}, Max Positions: {MAX_ACTIVE_TRADES}")
    print(f"[CONFIG] Stop Loss: {STOP_LOSS_PIPS} pips, Take Profit: {TAKE_PROFIT_PIPS} pips")
    
    # Initialize connection to MT5
    if not initialize_mt5(account, password, server):
        return
    
    try:
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
                    
                    # Get current symbol info
                    symbol_info = mt5.symbol_info(SYMBOL)
                    if symbol_info is None:
                        print(f"[ERROR] Failed to get symbol info for {SYMBOL}")
                        continue
                    
                    current_price = symbol_info.ask if symbol_info.ask > 0 else symbol_info.bid
                    
                    # Generate signal
                    order_type, prediction = generate_trading_signal(model, features, processed_current, last_close)
                    
                    # Determine if we should take a trade
                    price_diff_percent = abs(prediction - last_close) / last_close * 100
                    
                    # Only trade if prediction differs from current price by a meaningful amount
                    if price_diff_percent > 0.01:  # Minimum 0.01% difference
                        order_type_str = 'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'
                        print(f"[SIGNAL] {order_type_str} - Current: {last_close:.5f}, Predicted: {prediction:.5f}, Diff: {price_diff_percent:.3f}%")
                        
                        # Place trade
                        place_trade(SYMBOL, LOT_SIZE, prediction, current_price, order_type)
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