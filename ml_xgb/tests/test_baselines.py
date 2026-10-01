import numpy as np
import pandas as pd

from src.baselines import evaluate_baselines, persistence, same_hour_of_day, trailing_mean_24h
from src.feature_engineering import build_feature_matrix
from src.preprocessing import build_hourly_grid


def _grid(n=300):
    times = pd.date_range("2024-03-01 00:00", periods=n, freq="1h")
    df = pd.DataFrame({"time": times, "AQI": np.arange(n, dtype=float), "pm10": 1.0,
                       "pm2_5": 1.0, "Humidity": 1.0, "Temperature": 1.0})
    return build_hourly_grid(df)


def _samples(g, positions):
    X = build_feature_matrix(g)
    return X.loc[positions]


def test_persistence_and_mean24():
    g = _grid()
    s = _samples(g, [100])
    assert persistence(s)[0] == 100
    assert trailing_mean_24h(s)[0] == np.mean(np.arange(77, 101))


def test_same_hour_h27_is_not_naive_t_plus_h_minus_24():
    g = _grid()
    aqi = g["AQI"].to_numpy()
    s = _samples(g, [100])  # t = 04:00, t+27h có giờ 07:00
    pred = same_hour_of_day(s, aqi, 27)[0]
    assert pred == 79            # 07:00 hôm trước, ≤ t
    assert pred != aqi[100 + 27 - 24]  # t+h-24h = 103 là tương lai
    assert g["time"][int(pred)].hour == 7 and int(pred) <= 100


def test_same_hour_never_uses_future_for_any_horizon():
    g = _grid()
    aqi = g["AQI"].to_numpy()  # giá trị = vị trí -> pred phải ≤ vị trí t
    pos = np.arange(100, 200)
    s = _samples(g, pos)
    for h in range(3, 73, 3):
        pred = same_hour_of_day(s, aqi, h)
        assert (pred <= pos).all()
        assert (g["time"][pred.astype(int)].dt.hour.values == ((s["time"].dt.hour + h) % 24).values).all()


def test_same_hour_h24_equals_persistence():
    g = _grid()
    s = _samples(g, [150])
    assert same_hour_of_day(s, g["AQI"].to_numpy(), 24)[0] == 150


def test_same_hour_falls_back_over_missing_day():
    g = _grid()
    aqi = g["AQI"].to_numpy().copy()
    aqi[79] = np.nan
    s = _samples(g, [100])
    assert same_hour_of_day(s, aqi, 27)[0] == 55  # lùi thêm 24h


def test_evaluate_baselines_same_length_as_samples():
    g = _grid()
    s = _samples(g, np.arange(100, 130))
    out = evaluate_baselines(s, g["AQI"].to_numpy(), 6)
    assert set(out) == {"persistence", "mean_24h", "same_hour_of_day"}
    assert all(len(v) == len(s) for v in out.values())
