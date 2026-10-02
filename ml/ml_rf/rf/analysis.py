"""Phân tích sâu RF so với XGBoost trên cùng tập mẫu (đọc model đã lưu, không train lại model).

Ngoài MAE/RMSE: bias, tương quan, tỷ lệ đúng mức AQI, sai số khi AQI >= 151, mức overfit,
sai số theo mùa, baseline "luôn dự báo trung bình train" (clim), trung bình hai model (avg),
dung lượng và tốc độ dự báo.

    python -m rf.analysis     # -> models/comparison/full_comparison.csv, season_test.csv
"""
import json
import time

import numpy as np
import pandas as pd

from rf import config as rf_config  # noqa: F401  (thêm ml_xgb vào sys.path)
from src import config  # noqa: E402
from src.train import build_dataset, load_model_and_metadata as load_xgb, predict_with_model, _fit  # noqa: E402
from src.split import select_valid_samples  # noqa: E402
from src.targets import target_column  # noqa: E402
from rf.train import load_model_and_metadata as load_rf, model_path as rf_path  # noqa: E402
from src.train import model_path as xgb_path  # noqa: E402

LEVELS = [0, 50.5, 100.5, 150.5, 200.5, 300.5, np.inf]


def level(a):
    return np.digitize(np.round(a), LEVELS[1:-1])


def season(t):
    m = t.dt.month
    return np.select([m.isin([12, 1, 2]), m.isin([3, 4, 5]), m.isin([6, 7, 8])], ["Đông", "Xuân", "Hè"], "Thu")


data, aqi, _ = build_dataset()
rows, season_rows = [], []
for h in config.HORIZONS:
    xm, xmeta = load_xgb(h)
    rm, rmeta = load_rf(h)
    cols = xmeta["feature_columns"]
    assert cols == rmeta["feature_columns"]
    tr, _ = select_valid_samples(data, h, "train", cols)
    clim = tr[target_column(h)].mean()
    for seg in ("train", "val", "test"):
        s, _ = select_valid_samples(data, h, seg, cols)
        y = s[target_column(h)].to_numpy()
        px = predict_with_model(xm, s[cols], xmeta["n_trees"])
        pr = rm.predict(s[cols])
        preds = {"xgb": px, "rf": pr, "avg": (px + pr) / 2, "clim": np.full_like(y, clim)}
        hi = y >= 150.5
        for m, p in preds.items():
            rows.append(dict(h=h, seg=seg, model=m, n=len(y),
                             MAE=np.mean(np.abs(y - p)), RMSE=np.sqrt(np.mean((y - p) ** 2)),
                             bias=np.mean(p - y), corr=np.corrcoef(p, y)[0, 1] if p.std() > 0 else np.nan,
                             level_acc=np.mean(level(p) == level(y)) * 100,
                             n_hi=int(hi.sum()), MAE_hi=np.mean(np.abs(y[hi] - p[hi])), bias_hi=np.mean(p[hi] - y[hi])))
        if seg == "test" and h in (3, 24, 72):
            ss = season(s["time"])
            for sea in ("Xuân", "Hè", "Thu", "Đông"):
                k = ss == sea
                season_rows.append(dict(h=h, season=sea, n=int(k.sum()),
                                        xgb=np.mean(np.abs(y[k] - px[k])), rf=np.mean(np.abs(y[k] - pr[k]))))

df = pd.DataFrame(rows)
out = rf_config.MODELS_DIR / "comparison"
out.mkdir(parents=True, exist_ok=True)
df.to_csv(out / "full_comparison.csv", index=False)
pd.DataFrame(season_rows).to_csv(out / "season_test.csv", index=False)

pd.set_option("display.width", 250)
for seg in ("val", "test"):
    t = df[df.seg == seg].pivot(index="h", columns="model", values=["MAE", "RMSE"]).round(2)
    print(f"\n== {seg} MAE/RMSE ==\n{t.to_string()}")
t = df[df.seg == "test"].pivot(index="h", columns="model", values=["bias", "corr", "level_acc", "MAE_hi", "bias_hi"]).round(2)
print(f"\n== test bias/corr/level_acc/MAE_hi/bias_hi ==\n{t.to_string()}")
print("n_hi test:", df[(df.seg == 'test') & (df.model == 'xgb')].set_index('h')['n_hi'].to_dict())
t = df[df.seg.isin(["train", "val"]) & df.model.isin(["xgb", "rf"])].pivot(index="h", columns=["model", "seg"], values="MAE").round(2)
print(f"\n== overfit (MAE train vs val) ==\n{t.to_string()}")
print("\n== season test ==\n", pd.DataFrame(season_rows).round(2).to_string(index=False))

# Chi phí: dung lượng, tốc độ dự báo, thời gian train XGBoost (train lại h=3, 72 với cùng cấu hình, không lưu)
size_x = sum(xgb_path(h).stat().st_size for h in config.HORIZONS) / 1e6
size_r = sum(rf_path(h).stat().st_size for h in config.HORIZONS) / 1e6
print(f"\nsize total: xgb {size_x:.1f} MB, rf {size_r:.1f} MB")
fit_rf = [json.loads((rf_config.MODELS_DIR / f'rf_AQI_h{h}.meta.json').read_text())['fit_seconds'] for h in config.HORIZONS]
print(f"rf fit seconds: total {sum(fit_rf):.0f}, mean {np.mean(fit_rf):.1f}")
for h in (3, 72):
    xm, xmeta = load_xgb(h)
    cols = xmeta["feature_columns"]
    tr, _ = select_valid_samples(data, h, "train", cols)
    va, _ = select_valid_samples(data, h, "val", cols)
    t0 = time.perf_counter()
    _fit(xmeta["xgb_params"], tr[cols], tr[target_column(h)], va[cols], va[target_column(h)], xmeta["early_stopping_rounds"])
    print(f"xgb refit h={h}: {time.perf_counter() - t0:.1f}s")
one = data.dropna(subset=cols).tail(1)[cols]
batch = data.dropna(subset=cols).tail(1000)[cols]
for name, loader in (("xgb", load_xgb), ("rf", load_rf)):
    t0 = time.perf_counter()
    models = [loader(h) for h in config.HORIZONS]
    tl = time.perf_counter() - t0
    t0 = time.perf_counter()
    for _ in range(5):
        for m, meta in models:
            (predict_with_model(m, one, meta["n_trees"]) if name == "xgb" else m.predict(one))
    t1 = (time.perf_counter() - t0) / 5
    print(f"{name}: load 24 models {tl:.1f}s, predict 1 sample x 24 horizons {t1 * 1000:.0f} ms")
