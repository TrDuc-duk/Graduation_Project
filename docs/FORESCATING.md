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

#### 5.2. Kết quả

Train MAE khoảng 14,5–16,6 ở mọi horizon; MAE test 18,63 (h = 3), 27,21 (h = 24), 30,80 (h = 48), 31,79 (h = 72). Bảng đủ 24 horizon và phân tích so với XGBoost ở mục 6.

---

### 6. So sánh Random Forest và XGBoost

Hai mô hình dùng **cùng 184 feature, cùng split và cùng tập mẫu đánh giá** ở từng horizon, nên chênh lệch chỉ đến từ thuật toán. Ngoài ba baseline ở mục 3, phần này thêm baseline **"luôn dự báo trung bình nhãn tập train"** (ký hiệu *hằng số*) để kiểm tra model có thực sự nắm được diễn biến AQI hay không. Script: [`ml/ml_rf/rf/analysis.py`](../ml/ml_rf/rf/analysis.py); số liệu đủ 24 horizon: `ml/ml_rf/models/comparison/full_comparison.csv`.

#### 6.1. Tóm tắt

| Tiêu chí | Random Forest | XGBoost | Bên tốt hơn |
|---|---|---|---|
| MAE test, h = 3–15 | 18,63–27,86 | 17,51–27,45 | **XGBoost** (1,5–6,4%) |
| MAE test, h = 18–24 | 26,81–27,21 | 26,84–27,50 | Ngang nhau |
| MAE test, h = 27–72 | 29,57–31,99 | 30,33–33,24 | **RF** (1,3–4,9%) |
| RMSE test, h = 27–72 | 36,88–39,95 | 37,09–39,03 | **XGBoost** ở h ≥ 30 (0–3,3%) |
| Tương quan dự báo–thực tế, h ≥ 36 | 0,23–0,34 | 0,06–0,27 | **RF** |
| Tỷ lệ đoán đúng mức AQI, h = 3 | 61,8% | 63,7% | **XGBoost** |
| Tỷ lệ đoán đúng mức AQI, h ≥ 36 | 37,6–40,4% | 31,9% (bằng *hằng số*) | **RF** |
| Bias trung bình trên test | −4 đến −9 | −1 đến −8 | **XGBoost** |
| Dự báo đợt ô nhiễm (AQI ≥ 151), h ≥ 27 | MAE khoảng 50 | MAE khoảng 50 | Cả hai thất bại |
| Dung lượng 24 model | 371 MB | 20 MB | **XGBoost** (nhỏ hơn 19 lần) |
| Dự báo 1 thời điểm × 24 horizon | khoảng 0,8 s | khoảng 0,3–0,5 s | **XGBoost** |

**Kết luận ngắn:** XGBoost tốt hơn ở giờ gần, nơi mô hình thật sự có giá trị dự báo. Ở giờ xa, RF nhỉnh hơn theo MAE, nhưng **không mô hình nào dự báo tốt**, và lợi thế của RF chủ yếu đến từ việc XGBoost gần như dự báo hằng số (mục 6.3, 6.6).

#### 6.2. Sai số theo horizon (test, MAE / RMSE, điểm AQI)

| h | Random Forest | XGBoost | Baseline tốt nhất | *Hằng số* | RF so với XGB (MAE / RMSE) |
|---|---|---|---|---|---|
| 3 | 18,63 / 24,53 | 17,51 / 23,24 | 18,18 / 25,93 | 33,60 / 39,29 | −6,4% / −5,6% |
| 6 | 25,42 / 32,19 | 24,28 / 30,98 | 27,25 / 34,78 | 33,58 / 39,26 | −4,7% / −3,9% |
| 9 | 27,83 / 35,00 | 26,64 / 33,78 | 27,24 / 35,85 | 33,56 / 39,24 | −4,5% / −3,6% |
| 12 | 27,74 / 34,83 | 27,25 / 34,45 | 27,23 / 36,04 | 33,54 / 39,22 | −1,8% / −1,1% |
| 18 | 27,06 / 33,87 | 27,50 / 34,04 | 27,19 / 35,98 | 33,53 / 39,22 | +1,6% / +0,5% |
| 24 | 27,21 / 33,96 | 27,30 / 34,05 | 27,18 / 35,97 | 33,52 / 39,20 | +0,4% / +0,3% |
| 36 | 31,12 / 38,90 | 32,24 / 38,24 | 33,72 / 42,49 | 33,49 / 39,18 | +3,5% / −1,7% |
| 48 | 30,80 / 38,41 | 32,37 / 38,42 | 33,71 / 43,64 | 33,50 / 39,18 | +4,9% / 0,0% |
| 60 | 31,70 / 39,49 | 32,99 / 38,82 | 36,18 / 45,05 | 33,41 / 39,06 | +3,9% / −1,7% |
| 72 | 31,79 / 39,40 | 33,03 / 38,82 | 36,66 / 45,73 | 33,41 / 39,06 | +3,8% / −1,5% |

Dấu "+" nghĩa là RF tốt hơn XGBoost. Biểu đồ: `ml/ml_rf/models/comparison/rf_vs_xgb_{val,test}.png`.

- Validation cho cùng bức tranh: XGBoost tốt hơn ở h = 3–15 và 60–69, RF tốt hơn ở h = 18–57 và 72 (theo MAE).
- **So với *hằng số*:** ở h ≥ 51, RMSE của RF (39,4–40,0) **cao hơn** *hằng số* (39,1). Trên validation còn rõ hơn: RF 43–44 so với *hằng số* 41,5, còn XGBoost bằng đúng *hằng số* (41,5). Theo MAE thì cả hai vẫn tốt hơn *hằng số* (RF khoảng 5%, XGBoost khoảng 1%).
- "Baseline tốt nhất" (persistence, trung bình 24h, cùng giờ gần nhất) ở horizon xa còn kém *hằng số*, nên dùng nó làm mốc sẽ phóng đại lợi ích của cả hai mô hình.

#### 6.3. Mô hình có nắm được diễn biến AQI không

| h | Độ lệch chuẩn dự báo (RF / XGB) | Tương quan (RF / XGB) | Đúng mức AQI (RF / XGB / *hằng số*) | Bias (RF / XGB) |
|---|---|---|---|---|
| 3 | 28,9 / 29,7 | 0,79 / 0,81 | 61,8 / 63,7 / 31,8% | −4,0 / −3,8 |
| 6 | — | 0,59 / 0,63 | 49,3 / 52,5 / 31,8% | −5,9 / −6,0 |
| 24 | 20,5 / 19,3 | 0,54 / 0,54 | 45,8 / 45,5 / 31,8% | −7,6 / −7,8 |
| 48 | 17,8 / 5,1 | 0,33 / 0,24 | 40,3 / 31,9 / 31,9% | −9,4 / −3,3 |
| 72 | 17,4 / 2,9 | 0,24 / 0,12 | 40,3 / 31,9 / 31,9% | −6,9 / −1,0 |

(AQI thật trên test: trung bình khoảng 118,5, độ lệch chuẩn khoảng 39. "Đúng mức AQI" = dự báo và thực tế rơi vào cùng mức trong 6 mức của Bảng 3.2 báo cáo.)

- Ở h ≥ 36, XGBoost đoán đúng mức AQI đúng bằng tỷ lệ của *hằng số* (31,9%): **mọi dự báo rơi vào cùng một mức**. RF vẫn phân biệt được một phần (khoảng 40%).
- Cả hai đều **dự báo thấp** trên test; RF lệch thấp đến 7–9 điểm ở h = 27–60. Nguyên nhân nhiều khả năng là chuyển nguồn: quan hệ học từ nguồn cũ (mùa hè AQI trung bình 86) không đúng với Open-Meteo (mùa hè 120). XGBoost ở horizon xa ít lệch hơn chỉ vì nó dự báo gần trung bình train.

#### 6.4. Khi có ô nhiễm nặng (AQI thật ≥ 151, khoảng 1.800 mẫu, 30% tập test)

| h | MAE RF | MAE XGB | MAE *hằng số* | Bias RF / XGB |
|---|---|---|---|---|
| 3 | 26,1 | 24,5 | 49,1 | −24,4 / −22,2 |
| 6 | 37,7 | 35,9 | 49,1 | −36,7 / −34,7 |
| 12 | 43,3 | 41,4 | 49,0 | −42,6 / −40,3 |
| 24 | 43,2 | 43,5 | 49,0 | −42,1 / −42,8 |
| 27–72 | 48,3–52,5 | 49,4–51,4 | 48,8–49,0 | khoảng −50 / −50 |

- Cả hai mô hình **đánh giá thấp đợt ô nhiễm** ở mọi horizon (bias âm gần bằng MAE).
- Từ h = 27, cả hai sai khoảng 50 điểm, **không khác *hằng số***: không mô hình nào báo trước được đợt ô nhiễm quá một ngày. Đây là điểm cần lưu ý nhất nếu dùng dự báo để cảnh báo.

#### 6.5. Theo mùa (test, MAE)

| Mùa | h = 3 (RF / XGB) | h = 24 (RF / XGB) | h = 72 (RF / XGB) |
|---|---|---|---|
| Xuân (2.208 mẫu) | 16,43 / 15,33 | 26,47 / 25,88 | **30,23** / 32,43 |
| Hè (2.208) | 21,03 / 20,12 | **27,96** / 28,45 | 33,34 / 33,28 |
| Thu (456–525) | 25,18 / 22,74 | **30,03** / 32,29 | 39,66 / 39,79 |
| Đông (1.227) | 15,48 / 14,50 | 26,01 / 25,75 | **28,91** / 31,16 |

XGBoost tốt hơn ở mọi mùa tại h = 3. Ở h = 72, lợi thế của RF tập trung vào mùa Xuân và Đông — hai mùa có chu kỳ theo mùa rõ, RF giữ lại được còn XGBoost thì không (mục 6.6).

#### 6.6. Vì sao XGBoost tốt hơn ở giờ gần, RF lại nhỉnh hơn ở giờ xa

**Mức khớp dữ liệu train** (MAE train so với validation):

| h | XGB train / val | RF train / val |
|---|---|---|
| 3 | 14,6 / 19,1 | 14,5 / 20,4 |
| 24 | 22,7 / 30,2 | 16,6 / 29,6 |
| 48 | 36,2 / 35,2 | 16,5 / 34,1 |
| 72 | 38,8 / 35,6 | 16,3 / 35,5 |

**Giờ gần (3–15h).** AQI sắp tới phụ thuộc mạnh và khá "mượt" vào AQI hiện tại và vài giờ trước.
- XGBoost xây cây tuần tự, mỗi cây sửa phần sai còn lại của các cây trước, nên khớp quan hệ này rất sát.
- RF lấy trung bình nhiều cây sâu, độc lập. Với `max_features=0,1`, mỗi lần tách RF chỉ xét khoảng 18/184 feature, nên nhiều lần không thấy feature mạnh nhất (AQI hiện tại, lag 1h). Dự báo của RF là trung bình nhãn trong lá cây nên bị kéo về giữa và không ngoại suy được xu hướng.
- Đây là khác biệt của thuật toán, không phải do tune: ngay cả bộ tham số RF tốt nhất riêng cho h = 3 (RMSE val 26,98, `max_features` 0,33–0,5) vẫn kém XGBoost (25,71).

**Giờ xa (≥ 27h).** RF nhỉnh hơn chủ yếu vì **XGBoost gần như dừng học**, không phải vì RF dự báo tốt.
- XGBoost dùng early stopping trên validation, mà validation phần lớn là Open-Meteo, khác nguồn với train. Ở horizon xa, quan hệ học từ nguồn cũ không còn đúng, nên early stopping dừng sau 3–10 cây. Model gần như chỉ trả về trung bình train: MAE train (36–39) còn cao hơn MAE validation, tức là **underfit**.
- RF không có early stopping, nên giữ toàn bộ quy luật học được từ nguồn cũ: chu kỳ ngày, chu kỳ mùa, mức nền 72h (MAE train luôn khoảng 16 ở mọi horizon, tức **overfit**). Một phần quy luật này vẫn đúng trên Open-Meteo, nên tương quan và MAE tốt hơn XGBoost. Phần không đúng gây ra bias âm và các lỗi lớn, nên RMSE của RF lại kém.
- Bằng chứng: trên split chỉ dùng nguồn cũ (mục 4.5), XGBoost giữ 118–199 cây ở h ≥ 51 và tốt hơn baseline tốt nhất khoảng 11% MAE. Khi train và đánh giá cùng nguồn, XGBoost không còn "bỏ cuộc" ở horizon xa.

#### 6.7. Thử kết hợp: trung bình dự báo của hai mô hình

| h | MAE val (RF / XGB / trung bình) | MAE test (RF / XGB / trung bình) |
|---|---|---|
| 3 | 20,39 / 19,11 / 19,60 | 18,63 / 17,51 / 17,93 |
| 24 | 29,61 / 30,20 / 29,86 | 27,21 / 27,30 / 27,20 |
| 48 | 34,10 / 35,23 / 34,15 | 30,80 / 32,37 / 31,03 |
| 72 | 35,45 / 35,61 / 34,85 | 31,79 / 33,03 / 31,75 |

Trung bình hai mô hình hầu như không tốt hơn mô hình tốt hơn ở từng horizon (chỉ nhỉnh ở h ≥ 51 trên validation), trong khi phải chạy cả hai. **Không đề xuất dùng.**

#### 6.8. Chi phí triển khai

| | Random Forest | XGBoost |
|---|---|---|
| Dung lượng 24 model | 371 MB (khoảng 15 MB/model, joblib nén) | 20 MB (0,35–2,3 MB/model, JSON) |
| Thời gian train | khoảng 16 s/horizon, 6,5 phút cho 24 horizon (8 nhân) | 14–22 s ở h = 3, 1,5–8 s ở h = 72 (dừng sớm) |
| Tải 24 model | khoảng 5 s | khoảng 1 s |
| Dự báo 1 thời điểm × 24 horizon | khoảng 0,8 s | khoảng 0,3–0,5 s |
| Tune | Grid 12 bộ × 3 horizon (khoảng 7 phút) | Gần như không cần (Optuna chỉ cải thiện 0,5%) |

Cả hai đều đủ nhanh cho backend (dự báo mỗi giờ một lần cho mỗi trạm). Khác biệt đáng kể nhất là dung lượng: RF làm image Docker / bucket MinIO nặng thêm khoảng 370 MB.

#### 6.9. Kết luận so sánh

- **Giờ gần (3–15h), nơi dự báo có giá trị thật:** XGBoost tốt hơn ở mọi chỉ số (MAE, RMSE, tương quan, đúng mức AQI, đợt ô nhiễm, mọi mùa), lại nhẹ và nhanh hơn.
- **18–24h:** hai mô hình ngang nhau.
- **Giờ xa (≥ 27h):** RF nhỉnh hơn theo MAE và tương quan, nhưng kém theo RMSE, lệch thấp có hệ thống và không dự báo được đợt ô nhiễm. Lợi thế này đến từ việc XGBoost bị early stopping cắt gần như toàn bộ do chuyển nguồn dữ liệu, không phải từ sức mạnh của RF.
- **Đề xuất:** dùng **XGBoost làm mô hình chính**. Chưa nên chọn RF cho horizon xa chỉ vì MAE nhỉnh hơn: cần xử lý vấn đề chuyển nguồn trước (mục 9), sau đó so sánh lại.

### 7. Giới hạn

- Kết quả đo trên **chuỗi Hà Nội tổng hợp**; test hoàn toàn là Open-Meteo, train chủ yếu là nguồn cũ. **Chưa kiểm chứng trên dữ liệu cảm biến thật** (PMS7003/AHT10 của hệ thống, xem [`ARCHITECHTURE.md`](ARCHITECHTURE.md) mục 3.5).
- Không có đầu vào dự báo thời tiết; đây là giới hạn lớn nhất ở horizon xa.
- Các điểm nhảy vọt trong nguồn cũ được giữ nguyên cả trong train lẫn nhãn đánh giá.
- `baselines.py` chưa có baseline trung bình dài hạn, nên bảng metric chính (mục 4.3) phóng đại lợi ích ở horizon xa; baseline này mới được tính riêng trong `rf/analysis.py` (mục 6.2).
- Random Forest dự báo thấp có hệ thống khoảng 7–9 điểm AQI trên test (mục 6.3).

### 8. Hệ quả cho hệ thống

- **Dùng XGBoost làm mô hình dự báo chính** (mục 6.9): tốt hơn ở giờ gần, nhẹ hơn 19 lần, nhanh hơn. Phương án chọn mô hình theo từng horizon (RF cho h ≥ 18) chưa đáng làm lúc này, vì lợi thế của RF ở giờ xa chủ yếu do XGBoost bị cắt bởi early stopping (mục 6.6).
- Các mốc **3–24h** có giá trị dự báo thật (tương quan 0,5–0,8). Các mốc **48h và 72h** có tương quan chỉ 0,12–0,33 và không báo trước được đợt ô nhiễm (mục 6.4), nên chưa nên hiển thị trên dashboard như một dự báo, hoặc chỉ hiển thị kèm nhãn "xu hướng / độ tin cậy thấp".
- [`ARCHITECHTURE.md`](ARCHITECHTURE.md) đang nêu mốc nổi bật 12h/24h/48h/72h; nên đổi sang nhấn mạnh 3h/6h/12h/24h cho đến khi cải thiện được horizon xa.

### 9. Việc tiếp theo

1. Thêm baseline trung bình dài hạn (climatology) vào `baselines.py` và đánh giá lại cả hai mô hình.
2. Chạy Random Forest trên split nguồn cũ (`--legacy-only`) để so với XGBoost ở mục 4.5 (hiện `rf.train` chưa có tùy chọn này).
3. Giảm tác động của chuyển nguồn ở horizon xa: train/val cùng nguồn, thêm cờ nguồn làm feature, hoặc refit trên train + validation.
4. Thử bổ sung đầu vào dự báo thời tiết (Open-Meteo forecast) cho horizon xa.
5. LSTM: chưa bắt đầu.
6. Đánh giá trên dữ liệu cảm biến thật trước khi tích hợp vào backend.

---

### 10. Tái lập

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
../ml_xgb/.venv/bin/python -m rf.analysis                # phân tích sâu ở mục 6
```

- Model, metric và biểu đồ sinh ra trong `ml/*/models/` (không commit).
- Phiên bản thư viện đã ghim trong [`ml/ml_xgb/requirements.txt`](../ml/ml_xgb/requirements.txt) (Python 3.12, xgboost 3.4.1, scikit-learn 1.9.1, pandas 3.0.6).
- Sau khi chuyển thư mục vào `ml/`, các script trong `.venv/bin/` (vd. `pytest`) vẫn trỏ về đường dẫn cũ → gọi qua `.venv/bin/python -m ...` như trên, hoặc tạo lại venv.
