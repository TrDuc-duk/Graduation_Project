# FORECASTING.md

## Dự báo chỉ số AQI (3h → 72h) — các việc đã thực hiện

Cập nhật: 02/10/2026. Kế hoạch chi tiết và các quyết định thiết kế nằm ở [`PLAN.md`](../PLAN.md); tài liệu này tổng hợp những gì **đã chạy được và kết quả thực tế**.

| Mô hình | Thư mục | Trạng thái |
|---|---|---|
| XGBoost | [`ml/ml_xgb/`](../ml/ml_xgb/) | Hoàn thành 24 horizon, đã đánh giá test, 83 test pass |
| Random Forest | [`ml/ml_rf/`](../ml/ml_rf/) | Hoàn thành 24 horizon, đã đánh giá test, 7 test pass |
| LSTM | [`ml/ml_lstm/`](../ml/ml_lstm/) | Chưa bắt đầu |

---

### 1. Bài toán

- **Mục tiêu:** dự báo AQI tại `t + h` với `h = 3, 6, …, 72` giờ (24 mốc), trong đó `t` là giờ dữ liệu mới nhất đã hoàn tất.
- **Chiến lược:** direct multi-step — **một model riêng cho mỗi horizon** (24 model mỗi thuật toán).
- **Đầu vào:** chỉ dùng lịch sử đến `t` của 5 cột `AQI, pm10, pm2_5, Humidity, Temperature`. Không dùng dự báo thời tiết tương lai.
- **Định nghĩa AQI:** theo Bảng 3.3–3.4 của báo cáo (US EPA, PM2.5 mức Tốt 0–12), tính trực tiếp từ PM của từng giờ (không trung bình 24h, không NowCast), lấy `max` của hai chỉ số thành phần. Hàm tái lập: [`ml/ml_xgb/src/aqi.py`](../ml/ml_xgb/src/aqi.py).

---

### 2. Dữ liệu

**File:** [`ml/data/dataset.csv`](../ml/data/dataset.csv) — SHA-256 `45b710f8f7cc701ee8f8885704c1bcec4b7aa74ac2f34053a56bc86fd2d1e7c4` (pipeline kiểm tra hash trước khi train).

- 41.112 dòng theo giờ, từ `2022-01-13 00:00` đến `2026-09-22 23:00`, giờ địa phương UTC+7.
- Thiếu trọn ngày 31/12/2023 (24 giờ) → lưới giờ liên tục có 41.136 mốc.
- Ghép từ hai nguồn, mốc chuyển **01/07/2025**:
  - **Nguồn cũ** (`2022.csv` … `2025.csv`): đến 30/06/2025.
  - **Open-Meteo** (`open-meteo-AQI.csv`, `open-meteo-HaNoi-Temperature.csv`): từ 01/07/2025, 10.776 dòng.
- Cột AQI đã được **tính lại** từ PM2.5/PM10 cho toàn bộ dataset để thống nhất định nghĩa (commit `612964a`).

**Kết quả EDA** ([`ml/ml_xgb/models/eda/`](../ml/ml_xgb/models/eda/)):

| Nguồn | Năm | Số giờ | AQI TB | AQI p95 | Giờ AQI = 500 | PM2.5 nhảy > 100 µg/m³/giờ | PM10 < PM2.5 |
|---|---|---|---|---|---|---|---|
| Cũ | 2022 | 8.472 | 114,3 | 185 | 0 | 6 | 0 |
| Cũ | 2023 | 8.736 | 118,8 | 193 | 0 | 92 | 4 |
| Cũ | 2024 | 8.784 | 115,0 | 192 | 59 | 54 | 50 |
| Cũ | 2025 | 4.344 | 133,4 | 196 | 0 | 40 | 15 |
| Open-Meteo | 2025 | 4.416 | 118,3 | 183 | 0 | 0 | 0 |
| Open-Meteo | 2026 | 6.360 | 118,4 | 182 | 0 | 0 | 0 |

- Hai nguồn **khác phân phối rõ rệt**: mùa hè AQI trung bình 86 (nguồn cũ) so với 120 (Open-Meteo); biên độ chu kỳ ngày khoảng 22 so với 47 điểm; Open-Meteo không có giờ nào ở mức "Nguy hại" (max 265).
- Nguồn cũ có 192 lần PM2.5 nhảy hơn 100 µg/m³ trong một giờ (thường kèm PM10 = PM2.5) và 69 dòng PM10 < PM2.5. Đây là nguyên nhân của các sai số lớn nhất. **Quyết định: giữ nguyên, không lọc**, ghi nhận như một giới hạn.

---

### 3. Pipeline

Toàn bộ phần dữ liệu (lưới giờ, feature, nhãn, split, baseline, metric) nằm trong `ml/ml_xgb/src/` và được Random Forest dùng lại, nên hai mô hình được so sánh trên **cùng feature và cùng tập mẫu**.

| Bước | Module | Nội dung |
|---|---|---|
| Đọc dữ liệu | `data_loading.py` | Parse ISO8601 (dataset có 2 định dạng timestamp: có giây trước 07/2025, không giây sau đó), kiểm tra hash |
| Tiền xử lý | `preprocessing.py` | Reindex lên lưới giờ 1h liên tục, mask "quan sát gốc"; chính sách thiếu mặc định `no_fill` (không điền) |
| Feature | `feature_engineering.py` | **184 feature**: giá trị tại `t`; lag 1/3/6/12/24/48/72h; rolling mean/std/min/max cửa sổ 3/6/12/24/72h kết thúc tại `t`; diff; đặc trưng thời gian (giờ, thứ, tháng, sin/cos). Cần 73 giờ lịch sử |
| Nhãn | `targets.py` | `target_AQI_h{h}` = AQI quan sát gốc tại `t+h`; giờ thiếu cho nhãn NaN (không nội suy) |
| Split | `split.py` | Theo thời gian, không shuffle, mốc cắt tính trên lưới đầy đủ; một mẫu thuộc một tập khi **cả `t` và `t+h`** nằm trong tập đó |
| Baseline | `baselines.py` | Persistence (AQI tại `t`), trung bình 24h gần nhất, giá trị cùng giờ gần nhất |
| Train | `train.py` | 24 model + metadata; kiểm tra dự đoán trước/sau khi lưu–tải lại khớp nhau |
| Đánh giá | `evaluate.py` | MAE, RMSE, MAPE theo horizon, theo nguồn, theo mùa; biểu đồ |
| Suy luận | `predict.py` | Dùng cùng hàm feature với train; kiểm tra đủ lịch sử và độ mới của dữ liệu |

**Split 70/15/15** (dùng chung cho mọi horizon; số mẫu ở h = 3):

| Tập | Khoảng thời gian | Số mẫu | Nguồn |
|---|---|---|---|
| Train | 13/01/2022 → 26/04/2025 19:00 | 28.621 | 100% nguồn cũ |
| Validation | 26/04/2025 19:00 → 08/01/2026 21:00 | 6.167 | 1.565 cũ + 4.602 Open-Meteo |
| Test | 08/01/2026 21:00 → 23/09/2026 | 6.168 | 100% Open-Meteo |

Ngoài split chính, có thêm một **split riêng trong đoạn nguồn cũ** (`--legacy-only`, 70/15/15 trước 01/07/2025) để đo năng lực mô hình khi không có chuyển nguồn.

Mỗi model lưu kèm metadata đủ để tái lập suy luận: thứ tự feature, chính sách NaN, định nghĩa `t`/`t+h`, định nghĩa AQI, hash dataset, mốc split, seed, phiên bản thư viện, tham số, `best_iteration`, API predict, số mẫu theo nguồn và metric.

---

### 4. XGBoost

#### 4.1. Cấu hình

- `n_estimators=1000, max_depth=6, learning_rate=0.03, subsample=0.8, colsample_bytree=0.8`, `objective=reg:squarederror`, seed 42.
- Early stopping 50 vòng theo RMSE validation; **không refit** trên train + validation.
- Test chỉ được đánh giá **một lần**, sau khi đã chốt cấu hình bằng validation.

#### 4.2. Thí nghiệm tối ưu (validation, h = 3/6/9/12, 3 seed)

| Thay đổi so với cấu hình gốc (E0) | Thay đổi MAE validation |
|---|---|
| E1 — Target dạng delta (AQI(t+h) − AQI(t)) | −1,2% đến +0,5%, không ổn định |
| E2 — Feature bổ sung (tỷ lệ PM, AQI thành phần, EWM, ngày trong năm) | **Kém hơn ở cả 4 horizon** (−1,2% đến −2,4%) |
| E3 — Delta + feature bổ sung | +0,9 / +1,3 / 0,0 / +0,2% — chỉ có ích ở 3–6h |
| E4 — Để XGBoost tự xử lý NaN | −0,4% đến +0,6% (dữ liệu chỉ thiếu 1 ngày) |
| E5 — Delta + feature bổ sung + NaN native | +1,1 / +1,3 / +0,4 / −0,3% |
| Optuna 60 trial (h = 3) | RMSE −0,5%, nằm trong nhiễu |
| Chính sách `ffill3h` | khác < 0,1% |

**Kết luận:** giữ cấu hình E0. Mọi mức cải thiện đều dưới 1,5% và không nhất quán giữa các horizon.

#### 4.3. Kết quả (MAE / RMSE, điểm AQI)

"Baseline tốt nhất" là baseline có sai số thấp nhất ở từng horizon (persistence rất mạnh ở h = 24/48/72 do chu kỳ ngày).

| h | Validation | Test | Test — baseline tốt nhất | Cải thiện MAE / RMSE trên test |
|---|---|---|---|---|
| 3 | 19,11 / 25,71 | 17,51 / 23,24 | 18,18 / 25,93 | +3,7% / +10,4% |
| 6 | 25,86 / 32,95 | 24,28 / 30,98 | 27,25 / 34,78 | +10,9% / +10,9% |
| 9 | 27,91 / 35,27 | 26,64 / 33,78 | 27,24 / 35,85 | +2,2% / +5,8% |
| 12 | 28,50 / 35,84 | 27,25 / 34,45 | 27,23 / 36,04 | −0,1% / +4,4% |
| 24 | 30,20 / 37,43 | 27,30 / 34,05 | 27,18 / 35,97 | −0,4% / +5,3% |
| 48 | 35,23 / 41,30 | 32,37 / 38,42 | 33,71 / 43,64 | +4,0% / +12,0% |
| 72 | 35,61 / 41,52 | 33,03 / 38,82 | 36,66 / 45,73 | +9,9% / +15,1% |

Đủ 24 horizon: [`ml/ml_xgb/models/metrics/`](../ml/ml_xgb/models/metrics/) (`summary_MAE_test.csv`, `summary_RMSE_test.csv`, …). Biểu đồ: [`ml/ml_xgb/models/plots/`](../ml/ml_xgb/models/plots/).

- Test không kém validation → không có dấu hiệu overfit vào validation.
- Theo MAE, ở h = 12–24 model **chỉ ngang** baseline "cùng giờ gần nhất". Theo RMSE, model tốt hơn baseline tốt nhất ở mọi horizon (4–15%), tức là chủ yếu giảm các lỗi lớn.
- Model co dự báo về giá trị trung bình: đánh giá thấp các đợt AQI cao, đánh giá cao khi AQI thấp.
- Sai số theo mùa (h = 3, test): Đông 14,5 · Xuân 15,3 · Hè 20,1 · Thu 22,8 (mùa Thu chỉ có 528 mẫu).

#### 4.4. Phát hiện: ở horizon xa, model gần như chỉ dự báo giá trị trung bình

Số cây mà early stopping giữ lại giảm mạnh theo horizon:

| Horizon | 3 | 6 | 9 | 12 | 15 | 18 | 21 | 24 | 27 | 30 | 33 | 36–48 | 51–72 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Số cây (split chính) | 336 | 328 | 255 | 314 | 272 | 61 | 115 | 98 | 36 | 22 | 21 | 10–11 | 3–7 |
| Số cây (split nguồn cũ) | 334 | 223 | 195 | 149 | 169 | 164 | 190 | 151 | 145 | 189 | 152 | 123–171 | 118–199 |

Với learning rate 0,03, mô hình chỉ 3–10 cây gần như không rời khỏi giá trị khởi tạo (trung bình nhãn tập train). Kiểm tra trực tiếp trên tập test:

| h | Số cây | Độ lệch chuẩn của dự báo | Độ lệch chuẩn AQI thật | Tương quan dự báo–thực tế | MAE XGBoost | MAE nếu luôn dự báo trung bình train |
|---|---|---|---|---|---|---|
| 3 | 336 | 29,7 | 39,3 | 0,81 | 17,51 | 33,60 |
| 24 | 98 | 19,3 | 39,2 | 0,54 | 27,30 | 33,52 |
| 48 | 10 | 5,1 | 39,2 | 0,24 | 32,37 | 33,50 |
| 72 | 4 | 2,9 | 39,1 | 0,12 | 33,03 | 33,41 |

- Ở **h ≥ 48**, dự báo gần như là hằng số và chỉ tốt hơn "luôn dự báo trung bình" khoảng 1–3%. Con số "+9,9% so với baseline tốt nhất" ở h = 72 đến từ việc **trung bình dài hạn tốt hơn persistence**, không phải do model nắm được diễn biến AQI. Bộ baseline hiện tại chưa có baseline trung bình dài hạn (climatology), nên bảng 4.3 làm lợi ích ở horizon xa trông lớn hơn thực tế.
- Nguyên nhân chính là **khác biệt nguồn dữ liệu**: train toàn nguồn cũ, validation chủ yếu Open-Meteo. Ở horizon xa, quan hệ học được trên nguồn cũ không còn đúng trên Open-Meteo, nên early stopping dừng gần như ngay lập tức. Trong split nguồn cũ, mọi horizon đều giữ 118–334 cây.

#### 4.5. Split riêng trong đoạn nguồn cũ (`--legacy-only`)

Train 13/01/2022 → 16/06/2024 · Validation → 23/12/2024 · Test → 01/07/2025 (test 4.551 mẫu ở h = 3).

| h | MAE XGBoost | MAE baseline tốt nhất | Cải thiện |
|---|---|---|---|
| 3 | 18,96 | 20,68 | +8,3% |
| 24 | 27,89 | 31,75 | +12,1% |
| 48 | 30,83 | 34,84 | +11,5% |
| 72 | 32,77 | 37,08 | +11,6% |

Khi train và test cùng một nguồn, model tốt hơn baseline tốt nhất **8–12% MAE ở mọi horizon**. Năng lực dự báo ở horizon xa có tồn tại, nhưng không chuyển được sang nguồn dữ liệu khác.

---

### 5. Random Forest

#### 5.1. Cấu hình và tune

- `RandomForestRegressor`, 300 cây, `max_depth=None`, `max_samples=0.7`, bootstrap, seed 42. Cùng 184 feature, cùng split, cùng chính sách `no_fill` với XGBoost; số mẫu đánh giá khớp từng horizon (`rf.compare` kiểm tra điều này).
- `min_samples_leaf` và `max_features` chọn bằng **grid search trên validation**, tiêu chí RMSE validation trung bình tại h = 3/24/72, mỗi bộ 150 cây. Test không tham gia vào việc chọn.
  - **Vòng 1** (leaf 5/10/25 × max_features 0,2/0,33/0,5; dừng giữa chừng sau 8/12 bộ): `max_features=0,5` kém nhất ở h = 24/72; `0,2` tốt nhất nhưng nằm ở biên lưới; leaf lớn giảm overfit mà không làm validation kém đi. Log: `models/tune_round1_partial.log`.
  - **Vòng 2** (leaf 10/25/50/100 × max_features 0,1/0,2/0,33): chọn **`min_samples_leaf=10, max_features=0,1`** (RMSE val trung bình 36,02). Bốn bộ đứng đầu đều có `max_features=0,1` và chỉ chênh nhau < 0,3%, nên kết quả ít nhạy với `min_samples_leaf`. Kết quả: `models/tuning/grid_summary.csv`.
- `max_features` nhỏ (mỗi lần tách chỉ xét 10% feature) đóng vai trò regularization mạnh. Ở h = 72, bộ có validation tốt nhất lại nằm ở góc lưới (leaf 100, max_features 0,1), tức càng gần dự báo trung bình thì validation càng tốt — cùng hiện tượng với XGBoost ở mục 4.4, nên không mở rộng lưới thêm theo hướng này.
- Một bộ tham số chung cho mọi horizon nên ở h = 3 kém hơn bộ tốt nhất riêng cho h = 3 (RMSE val 27,25 so với 26,98).
- Model khoảng 15 MB/horizon (joblib nén), train khoảng 15 giây/horizon trên 8 nhân.

#### 5.2. Kết quả trên test và so sánh với XGBoost (MAE / RMSE, điểm AQI)

| h | Random Forest | XGBoost | Baseline tốt nhất | RF so với XGBoost (MAE / RMSE) |
|---|---|---|---|---|
| 3 | 18,63 / 24,53 | 17,51 / 23,24 | 18,18 / 25,93 | −6,4% / −5,6% |
| 6 | 25,42 / 32,19 | 24,28 / 30,98 | 27,25 / 34,78 | −4,7% / −3,9% |
| 9 | 27,83 / 35,00 | 26,64 / 33,78 | 27,24 / 35,85 | −4,5% / −3,6% |
| 12 | 27,74 / 34,83 | 27,25 / 34,45 | 27,23 / 36,04 | −1,8% / −1,1% |
| 18 | 27,06 / 33,87 | 27,50 / 34,04 | 27,19 / 35,98 | +1,6% / +0,5% |
| 24 | 27,21 / 33,96 | 27,30 / 34,05 | 27,18 / 35,97 | +0,4% / +0,3% |
| 36 | 31,12 / 38,90 | 32,24 / 38,24 | 33,72 / 42,49 | +3,5% / −1,7% |
| 48 | 30,80 / 38,41 | 32,37 / 38,42 | 33,71 / 43,64 | +4,9% / 0,0% |
| 72 | 31,79 / 39,40 | 33,03 / 38,82 | 36,66 / 45,73 | +3,8% / −1,5% |

Dấu "+" nghĩa là RF tốt hơn XGBoost. Đủ 24 horizon: [`ml/ml_rf/models/comparison/`](../ml/ml_rf/models/comparison/) (`rf_vs_xgb_{MAE,RMSE}_{val,test}.csv`, `rf_vs_xgb_{val,test}.png`).

- **h = 3–15: XGBoost tốt hơn** RF 1,5–6,4% MAE. Ở h = 3 và 9, RF còn kém baseline tốt nhất theo MAE.
- **h = 18–24: hai mô hình ngang nhau** và cùng ngang baseline "cùng giờ gần nhất" theo MAE.
- **h = 27–72: RF tốt hơn XGBoost 2–5% MAE**, nhưng RMSE ngang hoặc kém hơn tới 3%. Cả hai đều tốt hơn baseline tốt nhất (RF 6–13% MAE).
- Validation cho cùng bức tranh: XGBoost tốt hơn ở h = 3–15 và 60–69; RF tốt hơn ở h = 18–57 và 72.

#### 5.3. RF ở horizon xa: có tín hiệu hơn XGBoost, nhưng lệch thấp

Cùng phép kiểm tra như mục 4.4, trên tập test:

| h | Độ lệch chuẩn dự báo (RF / XGB) | Tương quan dự báo–thực tế (RF / XGB) | MAE RF | MAE XGB | MAE nếu luôn dự báo trung bình train | Trung bình dự báo RF |
|---|---|---|---|---|---|---|
| 3 | 28,9 / 29,7 | 0,79 / 0,81 | 18,63 | 17,51 | 33,60 | 114,9 |
| 24 | 20,5 / 19,3 | 0,54 / 0,54 | 27,21 | 27,30 | 33,52 | 111,1 |
| 48 | 17,8 / 5,1 | 0,33 / 0,24 | 30,80 | 32,37 | 33,50 | 109,3 |
| 72 | 17,4 / 2,9 | 0,24 / 0,12 | 31,79 | 33,03 | 33,41 | 111,5 |

(AQI thật trên test: trung bình khoảng 118,5, độ lệch chuẩn khoảng 39.)

- RF không bị "co về hằng số" như XGBoost (không có early stopping), nên ở h ≥ 48 vẫn giữ được biến thiên và tương quan cao hơn. Tuy vậy, tương quan 0,24–0,33 vẫn là thấp: RF chỉ tốt hơn "luôn dự báo trung bình" khoảng 5–8% MAE.
- RF **dự báo thấp có hệ thống** khoảng 7–9 điểm AQI trên test (trung bình dự báo khoảng 110 so với thực tế 118,5). Đây nhiều khả năng là hệ quả của chuyển nguồn: quan hệ học từ nguồn cũ (mùa hè AQI trung bình 86) không đúng với Open-Meteo (mùa hè 120). Độ lệch này cũng giải thích vì sao RMSE của RF không tốt hơn XGBoost dù MAE tốt hơn.
- Kết luận: ở horizon xa, RF nhỉnh hơn XGBoost nhưng **chưa mô hình nào dự báo tốt**; giới hạn chính vẫn là dữ liệu (chuyển nguồn, không có dự báo thời tiết), không phải lựa chọn thuật toán.

---

### 6. Giới hạn

- Kết quả đo trên **chuỗi Hà Nội tổng hợp**; test hoàn toàn là Open-Meteo, train chủ yếu là nguồn cũ. **Chưa kiểm chứng trên dữ liệu cảm biến thật** (PMS7003/AHT10 của hệ thống, xem [`ARCHITECHTURE.md`](ARCHITECHTURE.md) mục 3.5).
- Không có đầu vào dự báo thời tiết; đây là giới hạn lớn nhất ở horizon xa.
- Các điểm nhảy vọt trong nguồn cũ được giữ nguyên cả trong train lẫn nhãn đánh giá.
- Bộ baseline chưa có baseline trung bình dài hạn (climatology), nên lợi ích ở horizon xa bị phóng đại (mục 4.4, 5.3).
- Random Forest dự báo thấp có hệ thống khoảng 7–9 điểm AQI trên test (mục 5.3).

### 7. Hệ quả cho hệ thống

- Không có mô hình nào thắng ở mọi horizon. Nếu cần một bộ model cho backend, có thể **chọn mô hình theo từng horizon bằng validation**: XGBoost cho h ≤ 15, Random Forest cho h ≥ 18. Cách chọn này phải dựa trên validation, không dựa trên test, và chưa được triển khai.
- Các mốc **3–24h** có giá trị dự báo thật (tương quan 0,5–0,8). Các mốc **48h và 72h** có tương quan chỉ 0,24–0,33 (RF) và gần với trung bình dài hạn, nên chưa nên hiển thị trên dashboard như một dự báo, hoặc chỉ hiển thị kèm nhãn "xu hướng / độ tin cậy thấp".
- [`ARCHITECHTURE.md`](ARCHITECHTURE.md) đang nêu mốc nổi bật 12h/24h/48h/72h; nên đổi sang nhấn mạnh 3h/6h/12h/24h cho đến khi cải thiện được horizon xa.

### 8. Việc tiếp theo

1. Thêm baseline trung bình dài hạn (climatology) vào `baselines.py` và đánh giá lại cả hai mô hình.
2. Chạy Random Forest trên split nguồn cũ (`--legacy-only`) để so với XGBoost ở mục 4.5 (hiện `rf.train` chưa có tùy chọn này).
3. Giảm tác động của chuyển nguồn ở horizon xa: train/val cùng nguồn, thêm cờ nguồn làm feature, hoặc refit trên train + validation.
4. Thử bổ sung đầu vào dự báo thời tiết (Open-Meteo forecast) cho horizon xa.
5. LSTM: chưa bắt đầu.
6. Đánh giá trên dữ liệu cảm biến thật trước khi tích hợp vào backend.

---

### 9. Tái lập

```bash
# XGBoost (chạy trong ml/ml_xgb/)
.venv/bin/python -m pytest                              # 83 test
.venv/bin/python -m src.eda
.venv/bin/python -m src.train --horizons all --eval-test
.venv/bin/python -m src.train --horizons all --eval-test --legacy-only
.venv/bin/python -m src.evaluate

# Random Forest (chạy trong ml/ml_rf/, dùng chung venv của ml_xgb)
../ml_xgb/.venv/bin/python -m pytest                    # 7 test
../ml_xgb/.venv/bin/python -m rf.tune
../ml_xgb/.venv/bin/python -m rf.train --horizons all --params models/tuning/best_params.json --eval-test
../ml_xgb/.venv/bin/python -m rf.compare
```

- Model, metric và biểu đồ sinh ra trong `ml/*/models/` (không commit).
- Phiên bản thư viện đã ghim trong [`ml/ml_xgb/requirements.txt`](../ml/ml_xgb/requirements.txt) (Python 3.12, xgboost 3.4.1, scikit-learn 1.9.1, pandas 3.0.6).
- Sau khi chuyển thư mục vào `ml/`, các script trong `.venv/bin/` (vd. `pytest`) vẫn trỏ về đường dẫn cũ → gọi qua `.venv/bin/python -m ...` như trên, hoặc tạo lại venv.
