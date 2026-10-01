# PLAN: Huấn luyện XGBoost dự báo AQI (3h → 72h)

Cập nhật 01/10/2026 (vòng 2) theo `PLAN_REVIEW.md`. Đọc cùng `PLAN_REVIEW.md` và báo cáo `NguyenDucTham_DATN_v2_checked.pdf`.

> **Giới hạn kết luận:** kết quả hiện tại đánh giá dự báo AQI trên chuỗi dữ liệu
> Hà Nội tổng hợp (nhiều nguồn ghép lại, xem mục 2). Khả năng áp dụng cho cảm
> biến thật `NODE_076` cần được kiểm chứng riêng bằng dữ liệu của cảm biến đó;
> các node khác trên hệ thống dùng dữ liệu mô phỏng (báo cáo mục 4.3.3).

## 1. Mục tiêu

- **Nhãn duy nhất giai đoạn đầu: `AQI`** (đã tính lại từ PM2.5/PM10 theo Bảng 3.3–3.4 của báo cáo).
- Horizon: `3, 6, 9, ..., 72` giờ (24 mốc). Direct multi-step: **một `XGBRegressor` cho mỗi horizon → 24 model**.
- Đầu vào: lịch sử AQI, PM2.5, PM10, độ ẩm, nhiệt độ. PM2.5/PM10 chỉ là feature; **chưa** train model dự báo riêng cho chúng (phạm vi mở rộng sau này).
- Mục đích: dự báo AQI mà hệ thống hiển thị, xác định model có ích ở horizon nào, tạo model để tích hợp backend sau.
- Luồng làm việc: viết/test code trên VSCode + Claude Code (mẫu nhỏ) → train full trên Google Colab.

## 2. Dữ liệu

- File: `data/dataset.csv` ở gốc repo. Header: `time,AQI,pm10,pm2_5,Humidity,Temperature`.
- 41.112 dòng, `2022-01-13T00:00:00` → `2026-09-22T23:00:00`, tần suất 1h, không trùng timestamp.
- **Thiếu toàn bộ ngày 31/12/2023 (24 giờ)**; sau reindex đầy đủ lên lưới giờ liên tục là 41.136 timestamp → bắt buộc xử lý bằng lưới giờ (mục 4).
- Timestamp không có offset; nguồn metadata là UTC+7 → coi là **giờ địa phương**, không mặc định UTC. Feature giờ/tháng dùng giờ địa phương, nhất quán với inference.
- Chưa có `node_id` (chuỗi Hà Nội chung, không tự gán là lịch sử của `NODE_076`). Nếu mở rộng nhiều node, lag/rolling/reindex/target tính riêng theo node.
- **Nguồn dữ liệu theo giai đoạn (ghi rõ trong thống kê split, mục 7):**
  - Trước 01/07/2025: chủ yếu khớp `data/2022.csv`, `data/2023.csv`, `data/2024.csv`, `data/2025.csv`.
  - Từ 01/07/2025 (10.776 dòng): PM2.5/PM10 khớp `data/open-meteo-AQI.csv`, nhiệt độ/độ ẩm khớp `data/open-meteo-HaNoi-Temperature.csv`. AQI gốc của đoạn này đã bị thay bằng công thức báo cáo (mục 3).
  - Tính lại AQI thống nhất phép quy đổi nhưng **không** xóa khác biệt về nguồn PM/thời tiết giữa hai giai đoạn. Với split 70/15/15 (mục 7), validation có cả hai nguồn và test hầu như toàn bộ là Open-Meteo → kết quả test đo khả năng dự báo trên **chuỗi Hà Nội tổng hợp**, chưa chứng minh khả năng trên dữ liệu cảm biến thật `NODE_076`. Bổ sung một lần đánh giá theo thời gian riêng trong đoạn nguồn cũ (mục 7).
- Cột AQI đã được ghi đè theo công thức báo cáo; SHA-256 ghi trong `PLAN_REVIEW.md` mục 2.2.

### Định nghĩa nhãn AQI (giữ nhất quán)

- Tính **trực tiếp từ PM từng dòng**, không trung bình 24h, không NowCast.
- Bảng breakpoint theo báo cáo (PM2.5 mức Tốt 0–12, khác bảng EPA 2024). Đổi bảng/cửa sổ = đổi định nghĩa nhãn → tạo phiên bản dữ liệu mới, train lại, đồng bộ backend.
- Cắt PM2.5 còn 1 chữ số thập phân, PM10 còn số nguyên; nội suy; làm tròn gần nhất (`.5` làm tròn lên, **không dùng `round()` mặc định của Python**); vượt bảng → 500; lấy `max` hai chỉ số thành phần.
- Pipeline **đọc AQI trong CSV**, không tính lại khi train. Bổ sung `ml_xgb/src/aqi.py` + test để tái lập khi nhập dữ liệu mới.

### EDA trước khi train

Trước khi chạy pipeline đầy đủ: vẽ phân phối AQI/PM2.5/PM10 và khoảng thiếu
theo năm/mùa/nguồn; kiểm tra sự thay đổi phân phối quanh mốc 01/07/2025; đếm
số mẫu AQI bị giới hạn 500 theo giai đoạn. Hai đoạn có phân phối khác nhau
không tự suy ra quan hệ nhân quả — chỉ dùng để quyết định có cần báo cáo
metric tách theo nguồn/mùa hay không (mục 9).

### Tái lập dữ liệu

Ngoài `ml_xgb/src/aqi.py`, viết một script nhận các CSV nguồn đã chuẩn hóa, ghép
theo mốc 01/07/2025, tính AQI và xuất `data/dataset.csv` có phiên bản. Script
ghi lại: nguồn mỗi giai đoạn, ánh xạ cột, cách xử lý timestamp trùng/thiếu,
công thức AQI dùng, và hash đầu vào/đầu ra. Việc này tách khỏi và không làm
chậm bước thử pipeline offline trên `data/dataset.csv` hiện tại.

### Ý nghĩa một hàng dữ liệu theo giờ (liên quan ánh xạ CSDL, mục 11)

- Một hàng đại diện cho **giá trị trung bình của một giờ đã hoàn tất** (khớp
  cách `hourly_measurements` tổng hợp theo báo cáo), không phải một lần đo tức thời.
- AQI đầu vào được tính từ PM **trung bình đại diện của giờ đó**, theo hàm ở
  mục dưới — không tính AQI cho từng phép đo trong giờ rồi lấy trung bình các
  AQI đó. Vì phép quy đổi AQI tuyến tính từng đoạn và lấy `max`, hai cách này
  cho kết quả khác nhau; train và inference phải dùng **cùng một cách**
  (trung bình PM trước, quy đổi AQI sau).
- Chưa xác nhận các CSV nguồn tổng hợp theo đúng cách này; cần kiểm chứng khi
  có dữ liệu cảm biến thật, nhưng không cần trì hoãn thử pipeline trên CSV hiện tại.

## 3. Cấu trúc (thư mục `ml_xgb/`)

```
ml_xgb/
├── notebooks/train_colab.ipynb
├── src/
│   ├── config.py              # đường dẫn (suy ra từ vị trí file), horizons, seed, mốc cắt split
│   ├── aqi.py                 # hàm tính AQI theo báo cáo (dùng cho dữ liệu mới + test)
│   ├── data_loading.py        # đọc CSV (ISO8601: 2 định dạng timestamp), kiểm tra hash
│   ├── preprocessing.py       # lưới giờ liên tục, mask quan sát gốc, chính sách NaN
│   ├── feature_engineering.py # time/lag/rolling/diff (+ feature bổ sung tùy chọn), cột tường minh
│   ├── targets.py             # target_AQI_h{h} từ chuỗi quan sát gốc
│   ├── split.py               # chia theo thời gian, chọn mẫu theo timestamp nhãn
│   ├── baselines.py           # persistence, trung bình 24h, cùng giờ gần nhất
│   ├── train.py               # train 24 model + metadata; --eval-test, --legacy-only
│   ├── evaluate.py            # metric, bảng theo nguồn/mùa, biểu đồ
│   ├── predict.py             # suy luận từ lịch sử đến t
│   ├── eda.py                 # EDA trước train
│   ├── tune.py                # Optuna cho một horizon (chỉ dùng validation)
│   └── experiments.py         # so sánh cấu hình, walk-forward CV, phân tích sai số
├── tests/
├── models/                    # sinh khi chạy, không commit
└── requirements.txt           # phiên bản đã ghim
```

Mọi đường dẫn dữ liệu cấu hình trong `config.py`. Lệnh chạy từ trong `ml_xgb/`:
`.venv/bin/pytest`, `python -m src.train --horizons all --eval-test`, `python -m src.evaluate`,
`python -m src.predict`.

## 4. Tiền xử lý (`preprocessing.py`)

Thứ tự:
1. Parse `time`, sort, kiểm tra/loại timestamp trùng.
2. **Reindex lên lưới giờ liên tục `1h`** (giữ lưới 1h cho mọi horizon; không resample 3h) để `shift(-h)` đúng nghĩa h giờ.
3. Tạo mask quan sát gốc (`observed`) phân biệt giờ có dữ liệu thật và giờ thiếu/được điền.
4. Xử lý thiếu **chỉ bằng dữ liệu đã biết tại thời điểm dự báo**:
   - **Cấu hình mặc định cho lần chạy đầu (`config: no_fill`)**:
     - Giữ lưới giờ đầy đủ, **không điền** giờ thiếu.
     - Target chỉ lấy AQI quan sát gốc hợp lệ đúng tại `t+h`; không dùng giá trị đã điền làm nhãn.
     - Lag lấy đúng timestamp tương ứng trên lưới (không dịch bù khi thiếu).
     - Rolling theo số dòng giờ, cửa sổ `w` dùng `min_periods=w` (không tính rolling từ cửa sổ thiếu dữ liệu).
     - Một mẫu bị loại nếu thiếu bất kỳ feature bắt buộc hoặc thiếu target của horizon đó.
     - Ghi log số mẫu bị loại theo nguyên nhân (thiếu feature nào/thiếu target), theo tập và theo horizon.
   - **Cấu hình thử thêm, đặt tên riêng, không phải mặc định:**
     - `config: ffill3h` — forward-fill tối đa 3h cho đầu vào, kèm cờ thiếu và độ cũ giá trị (số giờ kể từ quan sát gốc gần nhất).
     - `config: xgb_native_nan` — giữ NaN và để XGBoost tự xử lý thiếu qua tham số `missing` (mặc định NaN); đây là lựa chọn về dữ liệu, không phải yêu cầu bắt buộc của model.
   - **Không dùng** nội suy tuyến tính toàn chuỗi (dùng đầu mút tương lai); không ffill khoảng thiếu 24 giờ (31/12/2023); không xóa hàng rồi shift trên chuỗi bị nén thời gian.
   - Cấu hình NaN/rolling đã chọn phải được lưu trong metadata model (mục 10) và dùng **giống hệt** ở inference.
5. Outlier: **không** loại giá trị PM chỉ vì vượt ngưỡng ví dụ (PM10 max 1.103 µg/m³). Chỉ loại khi có căn cứ chất lượng dữ liệu/giới hạn thiết bị; AQI đã có xử lý vượt bảng.
6. Tham số tiền xử lý nào học từ dữ liệu chỉ fit trên train.

## 5. Feature engineering

Quy ước: `t` = timestamp giờ dữ liệu mới nhất đã hoàn tất và có sẵn khi dự báo. Mọi feature tính được tại `t`.

- Giá trị hiện tại tại `t` của AQI, PM2.5, PM10, Humidity, Temperature.
- Lag tại `t-1, t-3, t-6, t-12, t-24, t-48, t-72`.
- Rolling (mean/std/min/max) cửa sổ 3h, 6h, 12h, 24h, 72h **kết thúc tại `t`**, một quy ước chung train/inference, không dùng cửa sổ có tâm.
- Diff/trend giữa giá trị tại `t` và các lag.
- Time features (giờ, thứ, tháng, sin/cos) tại `t`, và có thể thêm giờ/ngày của `t+h` (biết trước). **Không có đầu vào dự báo thời tiết/bụi tương lai** — model chỉ dùng lịch sử; ghi rõ giới hạn này khi diễn giải kết quả ở horizon lớn (72h).
- Danh sách cột feature **chỉ định tường minh**; không để cột `target_*` lọt vào X.
- AQI tại `t` làm feature không leakage vì nhãn là AQI tại `t+h`, `h > 0`.
- Nếu thêm feature giờ/ngày của `t+h`, truyền `h` vào hàm tạo feature (hoặc tạo bộ feature riêng cho từng horizon) để tránh nhầm `h` giữa các model; **lưu thứ tự cột feature của từng model trong metadata** (mục 10).

## 6. Nhãn và chiến lược mô hình

```python
horizons = list(range(3, 73, 3))
for h in horizons:
    df[f"target_AQI_h{h}"] = df["AQI"].shift(-h)   # trên lưới giờ, từ chuỗi quan sát gốc
```

Một `XGBRegressor` mỗi horizon (24 model). Hàng có NaN target/feature bị loại riêng cho từng horizon.

## 7. Chia train/val/test (`split.py`)

- Theo thời gian, không shuffle. **Tính ngày cắt trên lưới thời gian đầy đủ (41.136 timestamp), trước khi drop NaN hoặc lọc theo horizon.** Mọi horizon dùng chung các mốc cắt dưới đây.
- Tỷ lệ 70/15/15 theo `floor(N * tỷ_lệ_tích_lũy)`, đoạn nửa kín, giờ địa phương UTC+7:

  | Tập | Bắt đầu (bao gồm) | Kết thúc (không bao gồm) |
  | --- | --- | --- |
  | Train | `2022-01-13 00:00` | `2025-04-26 19:00` |
  | Validation | `2025-04-26 19:00` | `2026-01-08 21:00` |
  | Test | `2026-01-08 21:00` | `2026-09-23 00:00` |

  Đây là mốc cắt khởi điểm cho pipeline, chưa phải kết quả thực nghiệm đã chạy.
- Mẫu `(t, t+h)` thuộc một tập khi **cả `t` và `t+h`** thuộc đoạn đó; loại mẫu cuối đoạn có nhãn vượt ranh giới.
- Feature val/test được dùng lịch sử trước ranh giới (đã biết), không cần xóa 72h đầu mỗi tập, nhưng vẫn phải kiểm tra đủ feature.
- Chọn theo từng horizon, hoặc bỏ 72h cuối mỗi đoạn để dùng chung timestamp đầu vào.
- Mọi bước tune chỉ dùng train/val; test dành cho đánh giá cuối.
- **Ghi lại số mẫu hợp lệ theo nguồn dữ liệu (trước/sau 01/07/2025, xem mục 2) cho mỗi tập và mỗi horizon**, để không quy nhầm chênh lệch metric cho riêng việc đổi nguồn.
- Bổ sung một lần chia/đánh giá theo thời gian riêng, nằm hoàn toàn trong đoạn nguồn cũ (trước 01/07/2025), để có một phép đo không bị ảnh hưởng bởi chuyển nguồn.

## 8. Huấn luyện (`train.py`)

- Thư viện: `xgboost`, `scikit-learn`, `pandas`, `numpy`, `matplotlib`, `optuna` (tùy chọn). **Cố định phiên bản trong `requirements.txt` sau khi pipeline chạy đúng ở local**, dùng cùng phiên bản trên Colab.
- Hyperparameter khởi điểm: `n_estimators=1000, max_depth=6, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8, early_stopping_rounds=50`, `objective="reg:squarederror"`, seed cố định; metric dừng sớm là RMSE (hoặc MAE, ghi rõ trong metadata).
- **Quy trình early stopping / model lưu / model đánh giá (phải nhất quán, cố định trước khi xem kết quả test):**
  1. Train trên train, chọn tham số và dừng sớm bằng validation (`eval_set=[val]`).
  2. Cố định cấu hình và `best_iteration`; dùng chính model này để dự đoán validation và test.
  3. Lưu đúng model đã tạo ra các metric công bố, cùng `best_iteration`, metric dừng sớm, cấu hình, ngày cắt split và seed.
  4. **Refit (tùy chọn, không bắt buộc cho lần chạy đầu):** sau khi chốt cấu hình bằng train/val, train lại trên **train + validation** với số vòng boosting cố định `best_iteration + 1` (không early-stop bằng test), rồi đánh giá model refit trên test. Khi ghép train+validation, dùng lại các mẫu có nhãn thuộc toàn bộ đoạn ghép — có thể khôi phục mẫu từng bị loại chỉ vì nhãn vượt đúng ranh giới train/validation cũ.
  5. Nếu thử nhiều biến thể (cấu hình NaN khác nhau, tham số khác nhau), chọn bằng validation; **không** chọn bằng test.
  6. `XGBRegressor.predict()` dùng `best_iteration` tự động khi có early stopping; API native `Booster.predict()` có mặc định khác — chọn một API nhất quán giữa train/lưu/inference, và kiểm tra dự đoán trước/sau khi tải lại model khớp nhau.
- Lưu `models/xgb_AQI_h{h}.json` là model đúng theo bước 3 (hoặc bước 4 nếu dùng refit) — không lưu model khác với model đã sinh ra metric.
- Tune (optuna) chỉ cho vài horizon đại diện (3h, 24h, 72h) sau khi đã so baseline, chọn bằng validation.
- Không phụ thuộc GPU; cấu hình tái lập giữa local và Colab.

## 9. Đánh giá (`evaluate.py`)

- Metric chính: MAE, RMSE theo horizon (điểm AQI). MAPE là phụ (nhạy khi AQI thấp). Có thể thêm tỷ lệ đúng mức AQI theo Bảng 3.2.
- Baseline, đánh giá **trên cùng mẫu hợp lệ**:
  - Persistence: AQI tại `t`.
  - Trung bình 24h đã biết tại `t`.
  - Chu kỳ ngày: giá trị gần nhất có cùng giờ với `t+h` mà timestamp ≤ `t` (không dùng `t+h-24h` khi h > 24).
- Biểu đồ: sai số theo horizon; predicted vs actual ở 3h, 24h, 72h; báo cáo theo nguồn/mùa khi đủ dữ liệu (dùng thống kê nguồn theo tập ở mục 7, so sánh theo mùa để không quy mọi khác biệt cho việc đổi nguồn).
- Không ép metric tăng đều theo horizon, không mặc định model thắng baseline; chỉ ra horizon nào model có ích để chọn mốc hiển thị dashboard.
- Dự báo giữ giá trị liên tục khi đánh giá; nếu clip 0–500/làm tròn khi hiển thị, ghi rõ chính sách và ảnh hưởng đến metric.
- Báo cáo riêng kết quả trên lần chia trong đoạn nguồn cũ (mục 7) bên cạnh kết quả trên split chính, để tách ảnh hưởng của việc chuyển nguồn dữ liệu.

## 10. Lưu model và suy luận (`predict.py`)

Metadata kèm mỗi model: thứ tự/tên feature, horizons, định nghĩa `t` và `target_time = t + h`, **tên cấu hình NaN/rolling đã dùng** (`no_fill`/`ffill3h`/`xgb_native_nan`, mục 4), quy tắc lag/rolling/múi giờ, định nghĩa AQI, hash dataset, ngày cắt split (mục 7), seed, phiên bản thư viện, cấu hình model, `best_iteration`, API predict dùng để tạo kết quả (`XGBRegressor.predict` hay `Booster.predict`), có refit hay không, kết quả và baseline.

Inference dùng **cùng hàm feature engineering** với train, kiểm tra dữ liệu đủ mới và đủ lịch sử. Đầu ra: `input_time, target_time, horizon_hours, predicted_aqi, model_version` (+ `node_id` khi dùng cho trạm thực tế).

## 11. Chuẩn bị tích hợp backend (chưa triển khai ngay)

- Backend là Node.js/Express; FastAPI (nếu dùng) chỉ là dịch vụ suy luận Python backend gọi.
- Ánh xạ cột: `pm2_5`→`pm25`, `Humidity`→`humidity`, `Temperature`→`temperature`; AQI tính từ PM (không có cột AQI trong ERD). Xác nhận tên cột, giờ bucket, độ trễ của `hourly_measurements` khi viết truy vấn.
- Backend phải dùng cùng định nghĩa AQI với dataset.
- Raw `measurements` retention 3 tháng → cần giữ aggregate theo giờ lâu hơn/snapshot để train lại; phối hợp refresh policy và retention của Continuous Aggregate.
- Phân biệt dữ liệu thật (`NODE_076`), mô phỏng, và dữ liệu ngoài.
- Nếu lưu dự báo: bảng riêng gồm node, thời điểm đầu vào, thời điểm đích, horizon, AQI dự báo, phiên bản model.

## 12. Quy trình VSCode ↔ Colab

1. VSCode: viết code trong `ml_xgb/src/`, test bằng `pytest` + mẫu nhỏ (chỉ để kiểm tra logic, không đánh giá chất lượng).
2. Commit/push GitHub.
3. Colab: clone repo (hoặc mount Drive), `pip install -r ml_xgb/requirements.txt`, chạy full pipeline, lưu model/metric/biểu đồ vào Drive.
4. Sửa code ở VSCode, commit, pull lại trên Colab.

`requirements.txt`: pandas, numpy, xgboost, scikit-learn, matplotlib, seaborn, optuna, pytest.

## 13. Thứ tự triển khai

1. Kiểm tra schema/hash dataset; viết `aqi.py` + test (bảng biên, ví dụ ở dưới).
2. Loading/preprocessing: timestamp, lưới giờ, gap, mask quan sát gốc (cấu hình mặc định `no_fill`, mục 4).
3. Feature/target; kiểm tra `t+h` quanh khoảng thiếu 31/12/2023.
4. Split cố định theo mốc ở mục 7; thống kê số mẫu hợp lệ theo tập, horizon và **theo nguồn dữ liệu**.
5. Chạy 1 horizon (3h) trên mẫu nhỏ để kiểm tra logic, đảm bảo feature chỉ dùng dữ liệu đã biết tại `t`.
6. Train + đánh giá 3h trên full, so baseline trên validation trước khi tune rộng.
7. Mở rộng 24h, 72h, rồi đủ 24 horizon; cố định cấu hình (early stopping/refit, mục 8) trước khi xem kết quả test.
8. Lưu model, metadata, metric, biểu đồ, notebook Colab.
9. Chuẩn bị contract suy luận (`predict.py`); đánh giá trên dữ liệu cảm biến thật `NODE_076` trước khi kết luận model phù hợp để triển khai tại node đó; tích hợp backend khi kết quả đã rõ.

### Ví dụ kiểm thử AQI

| PM2.5 | PM10 | AQI PM2.5 | AQI PM10 | AQI |
| --- | --- | --- | --- | --- |
| 45,3 | 82 | 125 | 64 | 125 |
| 25 | 50 | 78 | 46 | 78 |
| 77,67 | 109,3 | 162 | 78 | 162 |
| 71,9 | 74,5 | 159 | 60 | 159 |
| 374,67 | 521,7 | 400 | 408 | 408 |

### Kiểm tra bắt buộc trước khi train full

- Không trùng timestamp; index là lưới giờ liên tục.
- Target đúng giờ `t+h`, kể cả gần khoảng thiếu.
- Feature tại `t` không đổi khi sửa dữ liệu sau `t`.
- Không có `target_*` trong X; nhãn thiếu không bị thay bằng nhãn nội suy.
- Nhãn train/val/test nằm trong đoạn tương ứng với mốc cắt ở mục 7.
- Feature train và inference cho cùng kết quả với cùng lịch sử.
- `aqi.py` tái lập bảng biên và ví dụ trên.
- Model và baseline đánh giá trên cùng timestamp hợp lệ.
- Dự đoán trước và sau khi tải lại model đã lưu khớp nhau (kiểm tra `best_iteration`/API predict nhất quán, mục 8).

## 14. Tiêu chí hoàn thành

Pipeline chạy được cho 24 horizon, có kết quả đánh giá trung thực so với baseline, và model đủ metadata để tái lập suy luận. Độ chính xác và khả năng áp dụng cho cảm biến thật phải được xác định bằng kết quả thực nghiệm, không suy ra từ việc code chạy thành công.

## 15. Kết quả thực nghiệm (01/10/2026)

Trạng thái: pipeline hoàn thành cho 24 horizon, 83 test xanh. Cấu hình chốt (E0): feature mục 5,
chính sách `no_fill`, tham số mục 8, không refit. Test chỉ được đánh giá **một lần**, sau khi chốt.
Model/metric/biểu đồ nằm ở `ml_xgb/models/` (không commit; tạo lại bằng các lệnh ở mục 3).

### 15.1. Phát hiện về dữ liệu

- `dataset.csv` có 2 định dạng timestamp (có giây trước 07/2025, không giây sau đó) → parse ISO8601.
- Hai nguồn khác phân phối rõ: mùa hè AQI trung bình 86 (nguồn cũ) và 120 (Open-Meteo); biên độ chu
  kỳ ngày khoảng 22 và 47 điểm; Open-Meteo không có giờ nào ở mức "Nguy hại" (max 265).
- Nguồn cũ có 192 lần PM2.5 đổi > 100 µg/m³ trong 1 giờ (Open-Meteo: 0), thường kèm PM10 = PM2.5,
  và 69 dòng PM10 < PM2.5. Đây là nguyên nhân chính của các sai số lớn nhất. **Quyết định: giữ
  nguyên, không xử lý** (người dùng chốt), ghi nhận như một giới hạn.
- Không bổ sung dữ liệu thời tiết (gió, mưa có trong file nguồn cũ) — người dùng chốt.

### 15.2. Thí nghiệm tối ưu (validation, h = 3/6/9/12, 3 seed)

| Thay đổi so với E0 | Kết quả |
|---|---|
| Target delta (AQI(t+h) − AQI(t)) | −1,2% đến +0,7% MAE, không ổn định |
| Feature bổ sung (tỷ lệ PM, AQI thành phần, EWM, ngày trong năm) | **Kém hơn ở cả 4 horizon** (−1,2% đến −2,4%) |
| Delta + feature bổ sung | +0,9 / +1,3 / 0,0 / +0,2%: chỉ có ích ở 3–6h |
| XGBoost NaN native | −0,4% đến +0,6%, không khác biệt (dữ liệu chỉ thiếu 1 ngày) |
| Optuna 60 trial (h=3) | RMSE −0,5%, nằm trong nhiễu |
| Chính sách `ffill3h` | khác < 0,1% |

Không áp dụng thay đổi nào: mọi mức cải thiện < 1,5% và không nhất quán giữa các horizon.

### 15.3. Kết quả cuối (MAE / RMSE, điểm AQI)

"Baseline tốt nhất" là baseline có sai số thấp nhất ở từng horizon. Persistence đơn thuần tốt theo
chu kỳ 24h (h = 24, 48, 72) nên so riêng với nó sẽ phóng đại lợi ích của model.

| h | Val XGBoost | Test XGBoost | Test baseline tốt nhất | Cải thiện MAE / RMSE trên test |
|---|---|---|---|---|
| 3 | 19,11 / 25,71 | 17,51 / 23,24 | 18,18 / 25,93 | +3,7% / +10,4% |
| 6 | 25,86 / 32,95 | 24,28 / 30,98 | 27,25 / 34,78 | +10,9% / +10,9% |
| 9 | 27,91 / 35,27 | 26,64 / 33,78 | 27,24 / 35,85 | +2,2% / +5,8% |
| 12 | 28,50 / 35,84 | 27,25 / 34,45 | 27,23 / 36,04 | −0,1% / +4,4% |
| 24 | 30,20 / 37,43 | 27,30 / 34,05 | 27,18 / 35,97 | −0,4% / +5,3% |
| 48 | 35,23 / 41,30 | 32,37 / 38,42 | 33,71 / 43,64 | +4,0% / +12,0% |
| 72 | 35,61 / 41,52 | 33,03 / 38,82 | 36,66 / 45,73 | +9,9% / +15,1% |

- Test không kém validation → không có dấu hiệu overfit vào validation.
- Theo MAE, ở h = 12–24 model **chỉ ngang** baseline "cùng giờ gần nhất". Theo RMSE, model tốt hơn
  baseline tốt nhất ở mọi horizon (4–15%), tức là chủ yếu giảm các lỗi lớn.
- Model co dự báo về trung bình: đánh giá thấp các đợt AQI cao và đánh giá cao khi AQI thấp.
- Split riêng trong đoạn nguồn cũ (`--legacy-only`): model tốt hơn baseline tốt nhất 8–12% MAE ở
  mọi horizon trên test của đoạn đó. Model có ích hơn khi train và test cùng một nguồn.

### 15.4. Giới hạn

- Kết quả đo trên chuỗi Hà Nội tổng hợp; test hoàn toàn là Open-Meteo, train chủ yếu là nguồn cũ.
  Chưa kiểm chứng trên dữ liệu cảm biến thật `NODE_076`.
- Không có đầu vào thời tiết dự báo; giới hạn này lớn nhất ở horizon xa.
- Các điểm nhảy vọt trong nguồn cũ được giữ nguyên trong cả train và nhãn đánh giá.
