# Các thay đổi cần làm trong PLAN.md

1. **Mục 7 — Chốt split:** tính mốc cắt trên lưới giờ đầy đủ trước khi lọc NaN, dùng chung cho mọi horizon. Nếu giữ 70/15/15, đề xuất hai mốc `2025-04-26 19:00` và `2026-01-08 21:00` (UTC+7); mỗi đoạn bao gồm đầu, không bao gồm cuối.

2. **Mục 4–6 — Chốt xử lý thiếu:** lần chạy đầu giữ NaN, rolling đặt `min_periods=window_size`, loại mẫu thiếu feature bắt buộc hoặc target. Forward-fill là thí nghiệm bổ sung; ghi số mẫu bị loại theo tập/horizon.

3. **Mục 7, 9 — Đánh giá theo nguồn:** với split trên, train dùng nguồn cũ, validation gồm hai nguồn, test là Open-Meteo. Thêm đánh giá theo thời gian trong đoạn nguồn cũ và thống kê mẫu theo nguồn. Kết quả hiện tại chưa chứng minh khả năng trên `NODE_076`.

4. **Mục 8, 10 — Chốt model lưu:** dùng validation để chọn tham số/early stopping, cố định cấu hình rồi đánh giá test; lưu đúng model đã đánh giá và `best_iteration`. Refit train + validation là tùy chọn, dùng `best_iteration + 1` vòng boosting và không dùng test để dừng sớm. Kiểm tra dự đoán trước/sau reload khớp.

5. **Mục 11 — Chốt dữ liệu inference:** xác định timestamp đầu/cuối bucket, múi giờ, độ trễ và điều kiện giờ đã hoàn tất. Tính AQI từ PM trung bình của giờ; không thay bằng trung bình các AQI. Kiểm chứng cách tổng hợp của CSV và CSDL trước tích hợp.

6. **Mục 8, 12, 13 — Bổ sung trước train:** EDA theo mùa/nguồn, kiểm tra mốc chuyển nguồn 01/07/2025; cố định phiên bản thư viện, objective và metric early stopping. Nếu thêm feature thời gian `t+h`, tạo theo từng horizon.

7. **Mục 2 — Sửa thông tin tham chiếu:** thay `2022–2025.csv` bằng `2022.csv`, `2023.csv`, `2024.csv`, `2025.csv`. Đưa hash dataset trực tiếp vào PLAN thay tham chiếu “PLAN_REVIEW.md mục 2.2”, vì review đã rút gọn. Hash hiện tại: `45b710f8f7cc701ee8f8885704c1bcec4b7aa74ac2f34053a56bc86fd2d1e7c4`.
