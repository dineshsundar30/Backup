import MetaTrader5 as mt5
import pandas as pd
import numpy as np
import talib
from sklearn.model_selection import train_test_split, cross_val_score
from sklearn.preprocessing import StandardScaler
from sklearn.ensemble import StackingClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.tree import DecisionTreeClassifier
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier
import logging
import time
import threading


class MT5TradingBot:
    def __init__(self, symbol='XAUUSDm', timeframe=mt5.TIMEFRAME_M5, interval=300):
        self.symbol = symbol
        self.timeframe = timeframe
        self.interval = interval
        self.logger = self._setup_logging()
        self.min_balance = 10
        self.fixed_lot = 0.01
        self._trade_lock = threading.Lock()
        self._is_trading = False

        if not mt5.initialize():
            error = mt5.last_error()
            self.logger.error(f"MT5 Initialization Error: {error}")
            raise Exception(f"MT5 Connection Failed: {error}")

    def _setup_logging(self):
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s - %(levelname)s: %(message)s')
        return logging.getLogger(__name__)

    def calculate_tp_sl(self, current_price, atr):
        risk_ratio = 2
        sl_distance = atr * 1
        tp_distance = sl_distance * risk_ratio
        
        return {
            'buy': {
                'sl': current_price - sl_distance,
                'tp': current_price + tp_distance
            },
            'sell': {
                'sl': current_price + sl_distance,
                'tp': current_price - tp_distance
            }
        }

    def check_account_viability(self):
        account_info = mt5.account_info()
        if account_info is None:
            self.logger.error("Cannot retrieve account information")
            return False

        balance = account_info.balance
        self.logger.info(f"Current Account Balance: ${balance:.2f}")

        return balance >= self.min_balance

    def fetch_historical_data(self, lookback_periods=2000):
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, lookback_periods)
        return pd.DataFrame(rates)

    def calculate_advanced_indicators(self, df):
        df = df.copy()
        df['sma_50'] = talib.SMA(df['close'], timeperiod=50)
        df['ema_20'] = talib.EMA(df['close'], timeperiod=20)
        df['rsi'] = talib.RSI(df['close'], timeperiod=14)
        df['macd'], df['macdsignal'], _ = talib.MACD(df['close'])
        df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)
        df['bbands_upper'], _, df['bbands_lower'] = talib.BBANDS(df['close'])
        df['willr'] = talib.WILLR(df['high'], df['low'], df['close'])

        return df.dropna()

    def prepare_training_data(self, df):
        df = df.copy()
        features = [
            'sma_50', 'ema_20', 'rsi', 'macd',
            'atr', 'bbands_upper', 'bbands_lower', 'willr'
        ]

        df.loc[:, 'future_return'] = df['close'].shift(-10) / df['close'] - 1
        X = df[features]
        y = np.where(df['future_return'] > 0.001, 1, 0)

        scaler = StandardScaler()
        X_scaled = scaler.fit_transform(X)

        return train_test_split(X_scaled, y, test_size=0.2, random_state=42)

    def create_stacked_model(self):
        base_models = [
            ('rf', RandomForestClassifier(n_estimators=100, random_state=42)),
            ('gb', GradientBoostingClassifier(n_estimators=100, random_state=42)),
            ('dt', DecisionTreeClassifier(random_state=42))
        ]

        stacked_model = StackingClassifier(
            estimators=base_models,
            final_estimator=LogisticRegression(),
            cv=5
        )

        return stacked_model

    def train_prediction_model(self, X_train, X_test, y_train, y_test):
        model = self.create_stacked_model()
        cv_scores = cross_val_score(model, X_train, y_train, cv=5)
        model.fit(X_train, y_train)

        accuracy = model.score(X_test, y_test)
        self.logger.info(f"Model Cross-Validation Scores: {cv_scores}")
        self.logger.info(f"Model Accuracy: {accuracy * 100:.2f}%")

        return model

    def execute_trade(self, signal, model, X_latest, latest_data):
        with self._trade_lock:
            # Check if a trade is already in progress
            if self._is_trading:
                self.logger.info("A trade is already in progress. Skipping...")
                return None

            try:
                self._is_trading = True

                if not self.check_account_viability():
                    return None

                confidence = model.predict_proba(X_latest)[0]
                if confidence[signal] < 0.85:
                    self.logger.info("Confidence too low for trading")
                    return None

                current_price = latest_data['close'].iloc[0]
                current_atr = latest_data['atr'].iloc[0]

                tp_sl_levels = self.calculate_tp_sl(current_price, current_atr)

                if signal == 1:  # Buy
                    trade_type = mt5.ORDER_TYPE_BUY
                    price = mt5.symbol_info_tick(self.symbol).ask
                    sl = tp_sl_levels['buy']['sl']
                    tp = tp_sl_levels['buy']['tp']
                else:  # Sell
                    trade_type = mt5.ORDER_TYPE_SELL
                    price = mt5.symbol_info_tick(self.symbol).bid
                    sl = tp_sl_levels['sell']['sl']
                    tp = tp_sl_levels['sell']['tp']

                request = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": self.symbol,
                    "volume": self.fixed_lot,
                    "type": trade_type,
                    "price": price,
                    "sl": sl,
                    "tp": tp,
                    "deviation": 20,
                    "magic": 234000,
                    "comment": "Dynamic TP/SL Trade"
                }

                result = mt5.order_send(request)
                if result.retcode == mt5.TRADE_RETCODE_DONE:
                    self.logger.info(f"Trade executed: {self.fixed_lot} lots")
                    self.logger.info(f"Entry: {price}, SL: {sl}, TP: {tp}")
                else:
                    self.logger.error(f"Trade failed: {result.comment}")

            except Exception as e:
                self.logger.error(f"Trade execution error: {e}")
            finally:
                self._is_trading = False

    def run_trading_cycle(self):
        while True:
            try:
                historical_data = self.fetch_historical_data()
                indicators_data = self.calculate_advanced_indicators(historical_data)

                X_train, X_test, y_train, y_test = self.prepare_training_data(indicators_data)
                model = self.train_prediction_model(X_train, X_test, y_train, y_test)

                latest_data = indicators_data.iloc[-1:]
                X_latest = StandardScaler().fit_transform(latest_data[
                    ['sma_50', 'ema_20', 'rsi', 'macd', 'atr',
                     'bbands_upper', 'bbands_lower', 'willr']
                ])

                signal = model.predict(X_latest)[0]
                self.execute_trade(signal, model, X_latest, latest_data)

                time.sleep(self.interval)

            except Exception as e:
                self.logger.error(f"Trading cycle error: {e}")
                time.sleep(self.interval)


def main():
    bot = MT5TradingBot(symbol='XAUUSDm')
    bot.run_trading_cycle()


if __name__ == "__main__":
    main()
