# Sửa các lỗi còn tồn đọng — 22/09/2026

Đợt này sửa những lỗi đã xác nhận trên working tree hiện tại, giữ các thay đổi
loại bỏ Office và các bản sửa trước. Không commit, không sửa config/credential
đang dùng của người dùng. Các báo cáo ngày 12/09 là lịch sử tại thời điểm đó;
bảng dưới ghi trạng thái mới sau sửa.

## Các lỗi đã xử lý

| Phần | Bằng chứng và thay đổi |
| --- | --- |
| Memory queue | Tái hiện an toàn bằng timer giả: 20 callback tạo thêm chuỗi timer không độ trễ khi worker vẫn bận. Worker hoàn tất nay chịu trách nhiệm lên lịch một batch tiếp theo; giữ deadline debounce, ưu tiên flush, hủy theo owner/thread và chặn callback cũ bằng generation. |
| Phân trang hội thoại | Cache rename/map làm cursor từ 3 thành 2 khi backend có hàng sidecar bị ẩn; thêm chat vào trang cuối cũng tạo nhầm cursor mới. Đổi page thành `{ threads, nextOffset }`; mọi thao tác cache và hai giao diện danh sách giữ cursor từ backend, kể cả qua TanStack structural sharing. |
| Tải lịch sử | HTTP 500 chứa `{data:[]}` từng bị coi là lịch sử rỗng thành công. Nay kiểm tra HTTP, cấu trúc dữ liệu và cursor; giữ tin nhắn đã tải, hiện lỗi và nút Retry history ở chat chính/sidecar. Hủy request và loại kết quả cũ khi chuyển phạm vi hội thoại. |
| SDK khác origin | Request SDK thực tế thiếu `credentials`. Nay mặc định gửi cookie trong đúng origin/path backend đã cấu hình; giữ lựa chọn credentials và CSRF header của caller, không thêm token ra ngoài phạm vi đó. |
| Nhiều Gateway worker | Guard từng cho phép PostgreSQL chạy nhiều worker dù RunManager/StreamBridge còn process-local. Nay chỉ chấp nhận 1 worker qua `GATEWAY_WORKERS` và `WEB_CONCURRENCY`, kiểm tra trước khi mở persistence. Compose truyền cùng số worker vào môi trường container để guard nhìn thấy override. |
| Token budget | Subagent chưa có middleware giới hạn riêng; lead còn kiểm tra trước khi cộng usage của child do thứ tự hook đảo ngược. Khi bật budget, mỗi child graph có bộ đếm riêng; lead cộng usage đã hoàn tất trước khi cho chạy công cụ tiếp theo. Khi tắt usage reporting vẫn tính budget nhưng không thêm log/attribution. Mặc định budget vẫn tắt. |
| Test isolation | Chạy test scaffold trước test migration gây dư bảng `_tmp_test`. Model thử nay dùng metadata riêng, engine được đóng trong finally. Bỏ mock executor toàn cục đã lỗi thời; 7 thứ tự import ở process mới đều dùng executor thật và thành công. |
| Accessibility dialog | Bổ sung mô tả có liên kết cho chọn model, sửa memory fact, đổi tên chat, điều hướng mobile và settings tại nơi sử dụng; không sửa generated components. |

## Kiểm chứng

- Backend trước sửa: **5.770 passed, 50 skipped**.
- Backend sau sửa: **5.814 passed, 50 skipped**, chạy toàn bộ `tests/` với
  `CI=true`, `VASSILFLOW_RUN_LIVE_TESTS=0`, trừ test Docker live
  `test_sandbox_orphan_reconciliation_e2e.py`. Không có test thất bại.
- Cặp scaffold → migration từng thất bại nay qua; nhóm kiểm tra liên quan sau
  khi chuẩn hóa format: **35 passed**.
- Frontend: **508 passed, 60 test files**, typecheck và ESLint qua.
- Production build của frontend qua: compile, TypeScript và tạo đủ 81 trang
  tĩnh; build là kiểm tra đóng gói, chưa thay cho triển khai production thật.
- Ruff trên các file Python của đợt sửa qua. Các file Python mới/thay đổi được
  kiểm tra format; giữ nguyên đoạn format cũ không liên quan trong lead agent.
- Thêm 3 browser specs cho history error/retry/chuyển thread; đã kiểm tra
  collection, chưa chạy toàn bộ Playwright suite.

## Thử trực tiếp trên Chrome

Dùng frontend thật ở `localhost:3044`, API giả lập chỉ lắng nghe loopback ở
`localhost:8049`, dữ liệu thử riêng; không gọi model thật trong lượt này.

1. API yêu cầu cookie HttpOnly/SameSite=Strict giả lập trên request SDK search.
   Danh sách chat tải được qua hai cổng khác nhau; API ghi nhận request có cookie.
2. API messages trả 500: giao diện hiện thông báo an toàn và Retry history;
   câu hỏi/câu trả lời hiện tại vẫn còn. Chỉ một lần gọi messages trong lúc lỗi,
   không có vòng lặp tự gọi lại liên tục.
3. Chuyển fixture sang 200 rồi bấm Retry history: lịch sử cũ xuất hiện, thông báo
   lỗi biến mất, các tin nhắn hiện tại vẫn còn. Tổng số request messages là 2.
4. Mở hộp chọn model và đổi tên chat: có mô tả accessibility; console không
   ghi warning/error trong các thao tác đã kiểm tra.

Đã đóng tab và dừng hai service thử; xác nhận không còn listener ở 3044/8049.
Mã fixture và số đếm giữ tại `.vassilflow/outstanding-fixes-20260922/` (Git ignore).
Log kiểm tra tại `logs/outstanding-fixes-*-20260922.txt`.

## Phạm vi và giới hạn còn lại

- Không còn lỗi đã xác nhận trong danh sách trên. Đây không phải khẳng định
  toàn bộ ứng dụng không thể có lỗi khác.
- Memory extraction chờ xử lý và bản khôi phục câu hỏi lỗi trên trang vẫn là
  trạng thái trong bộ nhớ; không bổ sung lưu bền qua crash/reload trong đợt này.
- Token budget kiểm tra sau response và cần usage metadata từ provider. Một
  response hoặc nhiều child đồng thời có thể vượt phần còn lại của budget;
  đây chưa phải cơ chế đặt trước một quỹ token chung.
- Cookie khác cổng trên cùng hostname đã thử. Đổi sang hostname không liên
  quan vẫn cần thiết kế proxy/auth phù hợp với host-only cookies và SameSite.
- Gateway vẫn chỉ hỗ trợ một process/worker. Guard không thể dò mọi lệnh CLI
  hoặc replica do trình quản lý bên ngoài khởi chạy; tài liệu yêu cầu giữ một.
- Loader credential Codex vẫn có hợp đồng `CODEX_AUTH_PATH` hoặc đường dẫn
  mặc định; custom `CODEX_HOME` cần cấu hình đường dẫn rõ ràng như lượt thử trước.
- Hiện tượng form tạo agent quay lại bước đặt tên từng gặp trong dev chưa tái
  hiện ổn định, chưa có bằng chứng đủ để sửa. Không thay đổi flow theo suy đoán.
- Chưa thử triển khai Docker/PostgreSQL thật, channel ngoài hoặc mọi model
  provider trong đợt này. Các skip/live-test exclusion không được tính là pass.
