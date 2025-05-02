import numpy as np
import pandas as pd
import time
import MetaTrader5 as mt5
import talib
from sklearn.ensemble import RandomForestRegressor
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import mean_squared_error, r2_score
import pytz
from datetime import datetime, timedelta
import sys
import joblib
import os
from sklearn.model_selection import GridSearchCV

# Trading parameters - Customizable
SYMBOL = "XAUUSDm"  # Change to your desired pair (e.g., "EURUSDm", "XAUUSDm", "BTCUSDm")
TIMEFRAME = mt5.TIMEFRAME_M5  # Change to your preferred timeframe
LOT_SIZE = 0.01  # Fixed lot size as requested
MAX_ACTIVE_TRADES = 1  # Only one trade at a time

# Minimum risk-reward ratio (will be enforced)
MIN_RISK_REWARD_RATIO = 2.0

# ATR periods for volatility calculation
ATR_PERIOD = 14

# Model parameters
MODEL_RETRAIN_HOURS = 8  # Retrain model every X hours
MODEL_FILE = f"model_{SYMBOL}_{TIMEFRAME}.joblib"
SCALER_FILE = f"scaler_{SYMBOL}_{TIMEFRAME}.joblib"

# Trade confirmation parameters
CONFIRMATION_WINDOW = 3  # Number of consecutive signals to confirm trade
MIN_ACCURACY_THRESHOLD = 0.65  # Minimum accuracy required from backtest before trading

# Trade tracking
last_retrain_time = None
consecutive_signals = {'BUY': 0, 'SELL': 0}
trade_log = []
signal_history = []


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
    if "USD" in symbol and len(symbol) <= 6:
        symbol_data["type"] = "forex"
    elif "XAU" in symbol:
        symbol_data["type"] = "gold"
    elif "BTC" in symbol:
        symbol_data["type"] = "crypto"
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


def prepare_features(data, symbol_data=None):
    """Enhanced feature engineering with technical indicators"""
    df = data.copy()

    # Basic price features
    df['momentum'] = df['close'].diff()
    df['momentum_3'] = df['close'].diff(3)
    df['momentum_5'] = df['close'].diff(5)
    
    # Volatility indicators
    df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=ATR_PERIOD)
    df['atr_pct'] = df['atr'] / df['close'] * 100  # ATR as percentage of price
    
    # Trend indicators
    df['rsi'] = talib.RSI(df['close'], timeperiod=14)
    df['rsi_divergence'] = df['rsi'].diff(2)  # RSI momentum
    
    # MACD
    df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(
        df['close'], fastperiod=12, slowperiod=26, signalperiod=9
    )
    
    # Moving averages and their crossovers
    df['ma_20'] = talib.SMA(df['close'], timeperiod=20)
    df['ma_50'] = talib.SMA(df['close'], timeperiod=50)
    df['ma_diff'] = df['ma_20'] - df['ma_50']  # MA crossover indicator
    
    # Bollinger Bands
    df['upper_band'], df['middle_band'], df['lower_band'] = talib.BBANDS(
        df['close'], timeperiod=20, nbdevup=2, nbdevdn=2, matype=0
    )
    df['bb_width'] = (df['upper_band'] - df['lower_band']) / df['middle_band']  # BB width as volatility indicator
    df['bb_position'] = (df['close'] - df['lower_band']) / (df['upper_band'] - df['lower_band'])  # Position within BB
    
    # Stochastic oscillator
    df['k_line'], df['d_line'] = talib.STOCH(
        df['high'], df['low'], df['close'], fastk_period=14, slowk_period=3, slowd_period=3
    )
    
    # Market session feature (adds time-based context)
    df['hour'] = df.index.hour
    
    # Add symbol-specific features if available
    if symbol_data is not None:
        if symbol_data["type"] == "forex":
            # For forex, add specific indicators like ADX
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)
        elif symbol_data["type"] == "gold":
            # Gold may have specific relationships with USD strength
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)
            df['aroon_up'], df['aroon_down'] = talib.AROON(df['high'], df['low'], timeperiod=14)
        elif symbol_data["type"] == "crypto":
            # Cryptos often need longer lookback periods
            df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=21)
            df['volume_ma'] = df['tick_volume'].rolling(window=20).mean()
            df['volume_ratio'] = df['tick_volume'] / df['volume_ma']
    
    # Candlestick pattern recognition
    df['doji'] = talib.CDLDOJI(df['open'], df['high'], df['low'], df['close'])
    df['engulfing'] = talib.CDLENGULFING(df['open'], df['high'], df['low'], df['close'])
    df['hammer'] = talib.CDLHAMMER(df['open'], df['high'], df['low'], df['close'])
    
    # Price action features
    df['body_size'] = abs(df['close'] - df['open']) / df['close'] * 100  # Candle body as percentage of price
    df['upper_wick'] = (df['high'] - df[['open', 'close']].max(axis=1)) / df['close'] * 100
    df['lower_wick'] = (df[['open', 'close']].min(axis=1) - df['low']) / df['close'] * 100
    
    # Drop rows with NaN values that result from calculations
    df.dropna(inplace=True)

    return df


def train_model(data, symbol_data):
    """Enhanced model training with cross-validation and feature selection"""
    try:
        # Define key features based on symbol type
        base_features = [
            'momentum', 'momentum_3', 'momentum_5', 
            'rsi', 'rsi_divergence', 
            'macd', 'macd_signal', 'macd_hist',
            'atr', 'atr_pct', 
            'ma_diff', 'bb_width', 'bb_position',
            'k_line', 'd_line',
            'body_size', 'upper_wick', 'lower_wick',
            'doji', 'engulfing', 'hammer'
        ]
        
        # Add symbol-specific features
        if symbol_data["type"] in ["forex", "gold"]:
            base_features.append('adx')
        
        if symbol_data["type"] == "gold":
            base_features.extend(['aroon_up', 'aroon_down'])
            
        if symbol_data["type"] == "crypto":
            base_features.extend(['adx', 'volume_ratio'])
        
        # Use all but the last 100 records for training
        split_idx = len(data) - 100 if len(data) > 100 else int(len(data) * 0.8)
        
        # Features and target
        # Filter to only use features that exist in the data
        features = [f for f in base_features if f in data.columns]
        
        X_train = data.iloc[:split_idx][features]
        y_train = data.iloc[:split_idx]['close']
        
        X_test = data.iloc[split_idx:][features]
        y_test = data.iloc[split_idx:]['close']
        
        # Normalize features
        scaler = StandardScaler()
        X_train_scaled = scaler.fit_transform(X_train)
        X_test_scaled = scaler.transform(X_test)
        
        # Convert back to DataFrame to maintain feature names
        X_train_scaled_df = pd.DataFrame(X_train_scaled, columns=features, index=X_train.index)
        X_test_scaled_df = pd.DataFrame(X_test_scaled, columns=features, index=X_test.index)
        
        # Train RandomForest with optimized hyperparameters
        if len(X_train_scaled_df) > 1000:  # Use GridSearchCV only if we have enough data
            param_grid = {
                'n_estimators': [100, 200],
                'max_depth': [None, 10, 20],
                'min_samples_split': [2, 5]
            }
            grid_search = GridSearchCV(
                RandomForestRegressor(random_state=42), 
                param_grid, 
                cv=3, 
                scoring='neg_mean_squared_error'
            )
            grid_search.fit(X_train_scaled_df, y_train)
            model = grid_search.best_estimator_
            print(f"[INFO] Best model parameters: {grid_search.best_params_}")
        else:
            model = RandomForestRegressor(n_estimators=200, random_state=42)
            model.fit(X_train_scaled_df, y_train)
        
        # Evaluate model
        y_pred = model.predict(X_test_scaled_df)
        
        mse = mean_squared_error(y_test, y_pred)
        r2 = r2_score(y_test, y_pred)
        
        print(f"[INFO] Model Training Complete - MSE: {mse:.6f}, R²: {r2:.6f}")
        
        # Feature importance
        importances = model.feature_importances_
        indices = np.argsort(importances)[::-1]
        
        print("\n[INFO] Feature importance:")
        for i in range(min(10, len(features))):  # Show top 10 features
            print(f"{features[indices[i]]}: {importances[indices[i]]:.4f}")
        
        # Save the model and scaler
        joblib.dump(model, MODEL_FILE)
        joblib.dump(scaler, SCALER_FILE)
        joblib.dump(features, f"features_{SYMBOL}_{TIMEFRAME}.joblib")
        
        return model, scaler, features
        
    except Exception as e:
        print(f"[ERROR] Model training failed: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # If we have a saved model, try to load it
        if os.path.exists(MODEL_FILE) and os.path.exists(SCALER_FILE):
            print("[INFO] Loading previous model...")
            model = joblib.load(MODEL_FILE)
            scaler = joblib.load(SCALER_FILE)
            features = joblib.load(f"features_{SYMBOL}_{TIMEFRAME}.joblib")
            return model, scaler, features
        
        # Otherwise return a simple fallback model
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        scaler = StandardScaler()
        model.fit(X_train[features[:3]], y_train)  # Use just a few features
        return model, scaler, features[:3]


def get_active_positions(symbol):
    """Get active positions for the symbol"""
    positions = mt5.positions_get(symbol=symbol)

    if positions is None:
        if mt5.last_error() != 0:  # Only print if there's an actual error
            print(f"[ERROR] Failed to get positions: {mt5.last_error()}")
        return []

    return positions


def calculate_dynamic_sl_tp(symbol_data, current_data, entry_price, order_type):
    """
    Calculate Stop Loss and Take Profit dynamically based on market volatility (ATR)
    and support/resistance levels
    """
    # Get current ATR value as a measure of volatility
    current_atr = current_data['atr'].iloc[-1]
    
    # Calculate point value
    point_value = calculate_point_value(symbol_data)
    
    # Adjust ATR multiplier based on symbol type and volatility
    if symbol_data["type"] == "gold":
        atr_sl_multiplier = 1.5  # Gold can be volatile
    elif symbol_data["type"] == "crypto":
        atr_sl_multiplier = 2.0  # Cryptocurrencies are highly volatile
    else:
        atr_sl_multiplier = 1.0  # Standard for forex
    
    # For very high volatility periods, reduce the multiplier to avoid excessive risk
    if current_data['atr_pct'].iloc[-1] > 0.5:  # ATR > 0.5% of price
        atr_sl_multiplier *= 0.8
    
    # Calculate SL in price terms based on ATR
    sl_price_movement = current_atr * atr_sl_multiplier
    
    # Convert SL price movement to points
    sl_points = int(sl_price_movement / symbol_data["point"])
    
    # Ensure minimum SL distance (at least 20 points)
    min_sl_points = 20
    sl_points = max(sl_points, min_sl_points)
    
    # Consider recent support/resistance levels for better SL/TP placement
    recent_highs = current_data['high'].iloc[-20:].values
    recent_lows = current_data['low'].iloc[-20:].values
    
    # Calculate actual SL/TP prices based on order type and support/resistance
    if order_type == mt5.ORDER_TYPE_BUY:
        # For buy orders, SL below recent support
        base_sl_price = entry_price - sl_points * symbol_data["point"]
        
        # Look for nearby support level
        support_levels = recent_lows[recent_lows < entry_price]
        if len(support_levels) > 0:
            nearest_support = max(support_levels)  # Highest support below entry
            # Use support if it's reasonably close but not too close
            max_support_dist = sl_points * 1.2 * symbol_data["point"]
            if entry_price - nearest_support < max_support_dist and entry_price - nearest_support > min_sl_points * symbol_data["point"]:
                sl_price = nearest_support - 5 * symbol_data["point"]  # Place SL just below support
            else:
                sl_price = base_sl_price
        else:
            sl_price = base_sl_price
            
        # TP above recent resistance
        resistance_levels = recent_highs[recent_highs > entry_price]
        if len(resistance_levels) > 0:
            nearest_resistance = min(resistance_levels)  # Lowest resistance above entry
            # Calculate TP that's at least MIN_RISK_REWARD_RATIO times the risk
            min_tp_price = entry_price + (entry_price - sl_price) * MIN_RISK_REWARD_RATIO
            # Use resistance if it's beyond our minimum TP
            if nearest_resistance > min_tp_price:
                tp_price = nearest_resistance + 5 * symbol_data["point"]  # Place TP just above resistance
            else:
                tp_price = min_tp_price
        else:
            tp_price = entry_price + (entry_price - sl_price) * MIN_RISK_REWARD_RATIO
    
    else:  # SELL order
        # For sell orders, SL above recent resistance
        base_sl_price = entry_price + sl_points * symbol_data["point"]
        
        # Look for nearby resistance level
        resistance_levels = recent_highs[recent_highs > entry_price]
        if len(resistance_levels) > 0:
            nearest_resistance = min(resistance_levels)  # Lowest resistance above entry
            # Use resistance if it's reasonably close but not too close
            max_resistance_dist = sl_points * 1.2 * symbol_data["point"]
            if nearest_resistance - entry_price < max_resistance_dist and nearest_resistance - entry_price > min_sl_points * symbol_data["point"]:
                sl_price = nearest_resistance + 5 * symbol_data["point"]  # Place SL just above resistance
            else:
                sl_price = base_sl_price
        else:
            sl_price = base_sl_price
            
        # TP below recent support
        support_levels = recent_lows[recent_lows < entry_price]
        if len(support_levels) > 0:
            nearest_support = max(support_levels)  # Highest support below entry
            # Calculate TP that's at least MIN_RISK_REWARD_RATIO times the risk
            min_tp_price = entry_price - (sl_price - entry_price) * MIN_RISK_REWARD_RATIO
            # Use support if it's beyond our minimum TP
            if nearest_support < min_tp_price:
                tp_price = nearest_support - 5 * symbol_data["point"]  # Place TP just below support
            else:
                tp_price = min_tp_price
        else:
            tp_price = entry_price - (sl_price - entry_price) * MIN_RISK_REWARD_RATIO
    
    # Round to the correct number of digits for the instrument
    sl_price = round(sl_price, symbol_data["digits"])
    tp_price = round(tp_price, symbol_data["digits"])
    
    # Calculate final SL/TP points and USD values
    if order_type == mt5.ORDER_TYPE_BUY:
        sl_points = int((entry_price - sl_price) / symbol_data["point"])
        tp_points = int((tp_price - entry_price) / symbol_data["point"])
    else:
        sl_points = int((sl_price - entry_price) / symbol_data["point"])
        tp_points = int((entry_price - tp_price) / symbol_data["point"])
    
    # Calculate actual risk/reward in USD
    risk_usd = sl_points * point_value * LOT_SIZE
    reward_usd = tp_points * point_value * LOT_SIZE
    
    return sl_price, tp_price, sl_points, tp_points, risk_usd, reward_usd


def place_trade(symbol, symbol_data, lot_size, prediction, current_price, order_type, current_data):
    """Place a trade in MT5 with dynamic SL and TP"""
    try:
        # Calculate dynamic Stop Loss and Take Profit levels
        sl, tp, sl_points, tp_points, risk_usd, reward_usd = calculate_dynamic_sl_tp(
            symbol_data, current_data, current_price, order_type
        )

        # Verify risk-reward ratio meets minimum requirement
        actual_rr_ratio = reward_usd / risk_usd if risk_usd > 0 else 0
        if actual_rr_ratio < MIN_RISK_REWARD_RATIO:
            print(f"[WARNING] Risk-reward ratio of {actual_rr_ratio:.2f} is below minimum {MIN_RISK_REWARD_RATIO}")
            # Adjust TP to meet minimum risk-reward ratio
            if order_type == mt5.ORDER_TYPE_BUY:
                tp = current_price + (current_price - sl) * MIN_RISK_REWARD_RATIO
                tp_points = int((tp - current_price) / symbol_data["point"])
            else:
                tp = current_price - (sl - current_price) * MIN_RISK_REWARD_RATIO
                tp_points = int((current_price - tp) / symbol_data["point"])
            
            tp = round(tp, symbol_data["digits"])
            reward_usd = tp_points * calculate_point_value(symbol_data) * lot_size
            print(f"[INFO] Adjusted TP to maintain minimum risk-reward ratio: {MIN_RISK_REWARD_RATIO}")

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
        
        # Log the trade
        trade_log.append({
            'time': datetime.now(),
            'symbol': symbol,
            'type': order_type_str,
            'ticket': result.order,
            'entry': current_price,
            'sl': sl,
            'tp': tp,
            'risk_usd': risk_usd,
            'reward_usd': reward_usd,
            'atr': current_data['atr'].iloc[-1]
        })

        return True
    
    except Exception as e:
        print(f"[ERROR] Failed to place trade: {str(e)}")
        return False


def generate_trading_signal(model, scaler, features, current_data, last_close, last_high, last_low):
    """Generate trading signal based on model prediction and additional confirmation"""
    try:
        # Extract features for prediction
        X = current_data[features].iloc[-1:]
        
        # Scale the features
        X_scaled = scaler.transform(X)
        
        # Make prediction using DataFrame to preserve feature names
        X_scaled_df = pd.DataFrame(X_scaled, columns=features, index=X.index)
        prediction = model.predict(X_scaled_df)[0]
        
        # Get additional indicators for confirmation
        rsi = current_data['rsi'].iloc[-1]
        macd_hist = current_data['macd_hist'].iloc[-1]
        bb_position = current_data['bb_position'].iloc[-1]
        stoch_k = current_data['k_line'].iloc[-1]
        stoch_d = current_data['d_line'].iloc[-1]
        
        # Initialize signal confidence scores
        buy_confidence = 0
        sell_confidence = 0
        
        # Price prediction component
        price_diff_percent = (prediction - last_close) / last_close * 100
        if prediction > last_close:
            buy_confidence += min(abs(price_diff_percent) * 10, 40)  # Cap at 40% weight
        else:
            sell_confidence += min(abs(price_diff_percent) * 10, 40)  # Cap at 40% weight
        
        # RSI component
        if rsi < 30:
            buy_confidence += 15
        elif rsi > 70:
            sell_confidence += 15
        
        # MACD component
        if macd_hist > 0 and macd_hist > current_data['macd_hist'].iloc[-2]:
            buy_confidence += 10
        elif macd_hist < 0 and macd_hist < current_data['macd_hist'].iloc[-2]:
            sell_confidence += 10
        
        # Bollinger Bands component
        if bb_position < 0.2:  # Price near lower band
            buy_confidence += 10
        elif bb_position > 0.8:  # Price near upper band
            sell_confidence += 10
        
        # Stochastic component
        if stoch_k < 20 and stoch_d < 20 and stoch_k > stoch_d:
            buy_confidence += 15
        elif stoch_k > 80 and stoch_d > 80 and stoch_k < stoch_d:
            sell_confidence += 15
        
        # Check for trend confirmation from moving averages
        ma_20 = current_data['ma_20'].iloc[-1]
        ma_50 = current_data['ma_50'].iloc[-1]
        
        if ma_20 > ma_50:  # Uptrend
            buy_confidence += 10
        elif ma_50 > ma_20:  # Downtrend
            sell_confidence += 10
        
        # Determine final signal
        signal_threshold = 50  # Minimum confidence needed for a trade
        
        if buy_confidence > sell_confidence and buy_confidence >= signal_threshold:
            order_type = mt5.ORDER_TYPE_BUY
            confidence = buy_confidence
        elif sell_confidence > buy_confidence and sell_confidence >= signal_threshold:
            order_type = mt5.ORDER_TYPE_SELL
            confidence = sell_confidence
        else:
            return None, prediction, 0  # No clear signal
        
        # Update consecutive signal counters
        order_type_str = 'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'
        opposite_type = 'SELL' if order_type_str == 'BUY' else 'BUY'
        
        consecutive_signals[order_type_str] += 1
        consecutive_signals[opposite_type] = 0
        
        # Log the signal
        signal_history.append({
            'time': datetime.now(),
            'type': order_type_str,
            'prediction': prediction,
            'current': last_close,
            'confidence': confidence,
            'consecutive': consecutive_signals[order_type_str],
            'rsi': rsi,
            'macd_hist': macd_hist,
            'bb_position': bb_position,
            'stoch_k': stoch_k,
            'stoch_d': stoch_d
        })
        
        return order_type, prediction, confidence
    
    except Exception as e:
        print(f"[ERROR] Signal generation failed: {str(e)}")
        return None, last_close, 0


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
        base_threshold = 0.015  # 0.015% for regular forex pairs
    elif symbol_data["type"] == "gold":
        base_threshold = 0.07  # 0.07% for gold (more volatile)
    elif symbol_data["type"] == "crypto":
        base_threshold = 0.12  # 0.12% for crypto (highly volatile)
    else:
        base_threshold = 0.04  # 0.04% for other instruments
    
    # Adjust threshold based on current ATR (more volatile = higher threshold)
    # For example, if ATR is high, we want a stronger signal before trading
    volatility_factor = (1 + (atr_percent / 0.5))  # normalize to typical volatility
    adjusted_threshold = base_threshold * volatility_factor
    
    # Also adjust based on time of day (lower threshold during active market hours)
    hour = datetime.now().hour
    if symbol_data["type"] == "forex":
        if 8 <= hour <= 16:  # Active European/US session for forex
            adjusted_threshold *= 0.9
        elif 22 <= hour or hour <= 2:  # Active Asian session
            adjusted_threshold *= 0.95
    elif symbol_data["type"] == "gold":
        if 13 <= hour <= 20:  # Active gold trading hours
            adjusted_threshold *= 0.9
    
    return adjusted_threshold


def backtest_model(model, scaler, features, historical_data, symbol_data):
    """Backtest the model to evaluate its performance before live trading"""
    try:
        # Use last 200 candles for backtesting
        backtest_data = historical_data.iloc[-200:].copy()
        
        # Prepare features for backtesting
        processed_data = prepare_features(backtest_data, symbol_data)
        
        # Initialize backtesting variables
        trades = []
        correct_predictions = 0
        total_trades = 0
        cumulative_pnl = 0
        
        # Calculate point value for PnL
        point_value = calculate_point_value(symbol_data)
        
        # Loop through data (skip first 50 for indicators to stabilize)
        for i in range(50, len(processed_data) - 10):
            current_slice = processed_data.iloc[:i+1].copy()
            current_row = current_slice.iloc[-1]
            
            # Get current price
            current_price = current_row['close']
            
            # Extract features for prediction
            X = current_slice[features].iloc[-1:].copy()
            
            # Scale features
            X_scaled = scaler.transform(X)
            X_scaled_df = pd.DataFrame(X_scaled, columns=features, index=X.index)
            
            # Generate prediction
            prediction = model.predict(X_scaled_df)[0]
            
            # Determine if this would have triggered a trade
            price_diff_percent = abs(prediction - current_price) / current_price * 100
            signal_threshold = get_signal_threshold(symbol_data, current_slice)
            
            if price_diff_percent > signal_threshold:
                # This would have triggered a trade
                order_type = mt5.ORDER_TYPE_BUY if prediction > current_price else mt5.ORDER_TYPE_SELL
                
                # Look 10 bars ahead to see what happened
                future_price = processed_data.iloc[i+10]['close']
                
                # Determine if prediction was correct
                if order_type == mt5.ORDER_TYPE_BUY:
                    was_correct = future_price > current_price
                    pnl_points = (future_price - current_price) / symbol_data["point"]
                else:
                    was_correct = future_price < current_price
                    pnl_points = (current_price - future_price) / symbol_data["point"]
                
                # Calculate PnL in USD
                pnl_usd = pnl_points * point_value * LOT_SIZE
                
                if was_correct:
                    correct_predictions += 1
                    
                total_trades += 1
                cumulative_pnl += pnl_usd
                
                # Add trade to list
                trades.append({
                    'time': current_slice.index[-1],
                    'type': 'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL',
                    'entry': current_price,
                    'exit': future_price,
                    'correct': was_correct,
                    'pnl_usd': pnl_usd
                })
        
        # Calculate accuracy
        accuracy = correct_predictions / total_trades if total_trades > 0 else 0
        avg_pnl = cumulative_pnl / total_trades if total_trades > 0 else 0
        
        print(f"[BACKTEST] Results for {symbol_data['type'].upper()}:")
        print(f"[BACKTEST] Total Trades: {total_trades}")
        print(f"[BACKTEST] Correct Predictions: {correct_predictions}")
        print(f"[BACKTEST] Accuracy: {accuracy:.2%}")
        print(f"[BACKTEST] Average PnL per Trade: ${avg_pnl:.2f}")
        print(f"[BACKTEST] Cumulative PnL: ${cumulative_pnl:.2f}")
        
        return {
            'accuracy': accuracy,
            'total_trades': total_trades,
            'correct_predictions': correct_predictions,
            'cumulative_pnl': cumulative_pnl,
            'avg_pnl': avg_pnl,
            'trades': trades
        }
        
    except Exception as e:
        print(f"[ERROR] Backtesting failed: {str(e)}")
        import traceback
        traceback.print_exc()
        return {'accuracy': 0, 'total_trades': 0}


def analyze_trade_performance():
    """Analyze trading performance from logs"""
    if not trade_log:
        print("[INFO] No trades to analyze yet.")
        return
    
    # Calculate basic statistics
    total_trades = len(trade_log)
    
    closed_positions = mt5.history_deals_get(
        datetime.now() - timedelta(days=7),
        datetime.now()
    )
    
    if closed_positions is None or len(closed_positions) == 0:
        print("[INFO] No closed positions found in history.")
        return
    
    # Convert to DataFrame
    deals = pd.DataFrame(list(closed_positions), columns=closed_positions[0]._asdict().keys())
    
    # Filter to our EA's trades
    deals = deals[deals['comment'] == "Python Trading Bot"]
    
    if len(deals) == 0:
        print("[INFO] No closed positions found for this bot.")
        return
    
    # Calculate profit metrics
    total_profit = deals['profit'].sum()
    winning_trades = deals[deals['profit'] > 0]
    losing_trades = deals[deals['profit'] <= 0]
    
    win_rate = len(winning_trades) / len(deals) if len(deals) > 0 else 0
    avg_win = winning_trades['profit'].mean() if len(winning_trades) > 0 else 0
    avg_loss = losing_trades['profit'].mean() if len(losing_trades) > 0 else 0
    
    # Print performance summary
    print("\n===== TRADING PERFORMANCE =====")
    print(f"Total Trades Closed: {len(deals)}")
    print(f"Win Rate: {win_rate:.2%}")
    print(f"Average Win: ${avg_win:.2f}")
    print(f"Average Loss: ${avg_loss:.2f}")
    print(f"Total Profit/Loss: ${total_profit:.2f}")
    print(f"Profit Factor: {abs(winning_trades['profit'].sum() / losing_trades['profit'].sum()) if len(losing_trades) > 0 and losing_trades['profit'].sum() != 0 else 'N/A'}")
    

def main():
    # Account credentials
    account = 204296999
    password = "dk@Demo07"
    server = "Exness-MT5Trial7"

    print("[STARTING] MT5 Enhanced Trading Bot with Dynamic SL/TP")
    print(f"[CONFIG] Symbol: {SYMBOL}, Lot Size: {LOT_SIZE}, Max Positions: {MAX_ACTIVE_TRADES}")
    print(f"[CONFIG] Minimum Risk-Reward Ratio: 1:{MIN_RISK_REWARD_RATIO}")
    print(f"[CONFIG] ATR Period: {ATR_PERIOD}")
    print(f"[CONFIG] Trade Confirmation Window: {CONFIRMATION_WINDOW} consecutive signals")

    # Initialize connection to MT5
    if not initialize_mt5(account, password, server):
        return

    try:
        # Global variables for training control
        global last_retrain_time
        
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
        historical_data = get_historical_data(SYMBOL, TIMEFRAME, 2000)  # Get more data for better training
        if historical_data is None:
            print("[ERROR] Failed to get historical data. Exiting.")
            mt5.shutdown()
            return

        # Prepare features
        print("[INFO] Preparing features...")
        processed_data = prepare_features(historical_data, symbol_data)

        # Check if we have a saved model and when it was last updated
        model_exists = os.path.exists(MODEL_FILE) and os.path.exists(SCALER_FILE)
        
        if model_exists:
            model_last_modified = datetime.fromtimestamp(os.path.getmtime(MODEL_FILE))
            hours_since_last_train = (datetime.now() - model_last_modified).total_seconds() / 3600
            print(f"[INFO] Existing model found. Last updated: {model_last_modified}")
            print(f"[INFO] Hours since last training: {hours_since_last_train:.1f}")
            
            if hours_since_last_train < MODEL_RETRAIN_HOURS:
                print(f"[INFO] Loading existing model (will retrain in {MODEL_RETRAIN_HOURS - hours_since_last_train:.1f} hours)...")
                model = joblib.load(MODEL_FILE)
                scaler = joblib.load(SCALER_FILE)
                features = joblib.load(f"features_{SYMBOL}_{TIMEFRAME}.joblib")
                last_retrain_time = model_last_modified
            else:
                print("[INFO] Training new model...")
                model, scaler, features = train_model(processed_data, symbol_data)
                last_retrain_time = datetime.now()
        else:
            print("[INFO] Training model...")
            model, scaler, features = train_model(processed_data, symbol_data)
            last_retrain_time = datetime.now()

        # Backtest model to verify performance
        print("[INFO] Backtesting model...")
        backtest_results = backtest_model(model, scaler, features, historical_data, symbol_data)
        
        # Check if model meets minimum accuracy threshold
        if backtest_results['accuracy'] < MIN_ACCURACY_THRESHOLD and backtest_results['total_trades'] > 10:
            print(f"[WARNING] Model accuracy ({backtest_results['accuracy']:.2%}) is below threshold ({MIN_ACCURACY_THRESHOLD:.2%})")
            print("[INFO] Continuing but with increased signal confirmation requirements")
            required_confirmations = CONFIRMATION_WINDOW + 1
        else:
            required_confirmations = CONFIRMATION_WINDOW

        print("[INFO] Trading bot active - Press Ctrl+C to stop")

        # Trading loop
        while True:
            try:
                # Check if we need to retrain the model
                hours_since_training = (datetime.now() - last_retrain_time).total_seconds() / 3600
                if hours_since_training >= MODEL_RETRAIN_HOURS:
                    print(f"[INFO] Model retraining scheduled (last retrain: {hours_since_training:.1f} hours ago)")
                    
                    # Get fresh historical data for retraining
                    fresh_data = get_historical_data(SYMBOL, TIMEFRAME, 2000)
                    if fresh_data is not None:
                        processed_fresh = prepare_features(fresh_data, symbol_data)
                        model, scaler, features = train_model(processed_fresh, symbol_data)
                        last_retrain_time = datetime.now()
                        
                        # Re-backtest the model
                        backtest_results = backtest_model(model, scaler, features, fresh_data, symbol_data)
                        
                        # Update required confirmations based on accuracy
                        if backtest_results['accuracy'] < MIN_ACCURACY_THRESHOLD and backtest_results['total_trades'] > 10:
                            required_confirmations = CONFIRMATION_WINDOW + 1
                        else:
                            required_confirmations = CONFIRMATION_WINDOW
                    else:
                        print("[WARNING] Could not get fresh data for retraining")

                # Check current positions
                active_positions = get_active_positions(SYMBOL)

                if len(active_positions) < MAX_ACTIVE_TRADES:
                    # Get latest data for trading decision
                    current_data = get_historical_data(SYMBOL, TIMEFRAME, 300)
                    if current_data is None:
                        time.sleep(5)
                        continue

                    processed_current = prepare_features(current_data, symbol_data)
                    
                    # Get last prices
                    last_close = processed_current['close'].iloc[-1]
                    last_high = processed_current['high'].iloc[-1]
                    last_low = processed_current['low'].iloc[-1]

                    # Get current symbol info for latest prices
                    symbol_info_tick = mt5.symbol_info_tick(SYMBOL)
                    if symbol_info_tick is None:
                        print(f"[ERROR] Failed to get symbol tick info for {SYMBOL}")
                        time.sleep(5)
                        continue

                    # Generate signal with confidence level
                    order_type, prediction, confidence = generate_trading_signal(
                        model, scaler, features, processed_current, last_close, last_high, last_low
                    )
                    
                    if order_type is not None:
                        order_type_str = 'BUY' if order_type == mt5.ORDER_TYPE_BUY else 'SELL'
                        
                        # Get appropriate bid/ask price
                        bid_price = symbol_info_tick.bid
                        ask_price = symbol_info_tick.ask
                        current_price = ask_price if order_type == mt5.ORDER_TYPE_BUY else bid_price
                        
                        # Check if we have enough consecutive signals
                        if consecutive_signals[order_type_str] >= required_confirmations:
                            print(f"[SIGNAL] {order_type_str} - Current: {last_close:.{symbol_data['digits']}f}, "
                                f"Predicted: {prediction:.{symbol_data['digits']}f}, Confidence: {confidence:.1f}%")
                            print(f"[SIGNAL] Confirmed with {consecutive_signals[order_type_str]} consecutive signals")
                            
                            # Place trade with dynamic SL/TP
                            place_trade(SYMBOL, symbol_data, LOT_SIZE, prediction, current_price, order_type, processed_current)
                            
                            # Reset consecutive signals after trade
                            consecutive_signals['BUY'] = 0
                            consecutive_signals['SELL'] = 0
                        else:
                            print(f"[SIGNAL] {order_type_str} detected with {confidence:.1f}% confidence, "
                                  f"but waiting for confirmation ({consecutive_signals[order_type_str]}/{required_confirmations})")
                    else:
                        print(f"[INFO] No tradable signal detected")
                else:
                    # Analyze active positions
                    positions_df = pd.DataFrame(list(active_positions), columns=active_positions[0]._asdict().keys())
                    for i, pos in positions_df.iterrows():
                        profit = pos['profit']
                        time_open = datetime.fromtimestamp(pos['time'])
                        mins_open = (datetime.now() - time_open).total_seconds() / 60
                        print(f"[POSITION] #{pos['ticket']} {pos['type']} - Open for {mins_open:.1f} mins, P/L: ${profit:.2f}")
                    
                    # Every hour, analyze overall performance
                    current_hour = datetime.now().hour
                    if current_hour % 1 == 0 and datetime.now().minute < 2:
                        analyze_trade_performance()
                
                # Sleep to avoid excessive API calls
                time.sleep(15)  # 15 seconds between updates

            except KeyboardInterrupt:
                print("[INFO] Bot stopped by user")
                break
            except Exception as e:
                print(f"[ERROR] Loop error: {str(e)}")
                import traceback
                traceback.print_exc()
                time.sleep(10)  # Wait 10 seconds before continuing after an error

    except KeyboardInterrupt:
        print("[INFO] Bot stopped by user")
    except Exception as e:
        print(f"[ERROR] Fatal error: {str(e)}")
        import traceback
        traceback.print_exc()
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
