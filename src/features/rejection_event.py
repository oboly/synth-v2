import pandas as pd
import numpy as np

def compute_rejection_events(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    # rolling levels
    df['rolling_low'] = df['low'].rolling(20).min()
    df['rolling_high'] = df['high'].rolling(20).max()

    # ATR (simple)
    df['tr'] = np.maximum(df['high'] - df['low'],
                 np.maximum(abs(df['high'] - df['close'].shift(1)),
                            abs(df['low'] - df['close'].shift(1))))
    df['atr'] = df['tr'].rolling(14).mean()

    # sweep detection
    df['sweep_down'] = df['low'] < df['rolling_low'].shift(1)
    df['sweep_up'] = df['high'] > df['rolling_high'].shift(1)

    # reclaim
    df['reclaim_down'] = df['close'] > df['rolling_low'].shift(1)
    df['reclaim_up'] = df['close'] < df['rolling_high'].shift(1)

    df['is_sweep'] = df['sweep_down'] | df['sweep_up']
    df['is_reclaim'] = (df['sweep_down'] & df['reclaim_down']) | \
                       (df['sweep_up'] & df['reclaim_up'])

    # direction
    df['sweep_direction'] = np.where(df['sweep_down'], 'down',
                             np.where(df['sweep_up'], 'up', None))

    # strength metrics
    df['sweep_distance_atr'] = np.where(
        df['sweep_down'],
        (df['rolling_low'].shift(1) - df['low']) / df['atr'],
        (df['high'] - df['rolling_high'].shift(1)) / df['atr']
    )

    df['reclaim_strength'] = np.where(
        df['sweep_down'],
        (df['close'] - df['rolling_low'].shift(1)) / df['atr'],
        (df['rolling_high'].shift(1) - df['close']) / df['atr']
    )

    # candle structure
    df['range'] = df['high'] - df['low']
    df['wick_ratio'] = (df['range'] - abs(df['close'] - df['open'])) / df['range']
    df['close_position'] = (df['close'] - df['low']) / df['range']

    # volume
    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']

    return df
