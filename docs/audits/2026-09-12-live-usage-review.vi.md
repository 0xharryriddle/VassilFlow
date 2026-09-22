# Kiểm tra sử dụng thực tế VassilFlow sau khi gỡ Office

Ngày kiểm tra: 2026-09-12.

## Cách kiểm tra

Thao tác trực tiếp trên Chrome với frontend Next.js tại `127.0.0.1:3044`
và Gateway thật tại `127.0.0.1:8018`. Chat dùng model
`gpt-5.3-codex-spark` đang được cấu hình, không dùng phản hồi replay/mock.

Runtime được tách vào `.vassilflow/live-smoke-20260912/`: config, SQLite,
agent, hội thoại, skills copy, uploads và outputs riêng. Trong phiên thử đã
bật API quản lý agent, dùng chế độ local không đăng nhập, tắt channels,
tracing và cập nhật memory nền. Cấu hình/dữ liệu làm việc sẵn có không bị sửa.

## Các luồng đã thử

| Luồng | Kết quả quan sát |
| --- | --- |
| Mở chat, chọn model, streaming tiếng Việt | Trả lời đúng `17 + 25 = 42` |
| Tải lại trang, tiếp tục hội thoại | Giữ lịch sử và nhớ mã `VASSIL-42` |
| Upload CSV qua multipart API | HTTP 200; danh sách upload có file 35 bytes |
| Agent đọc file và tạo kết quả | Gọi `read_file`, `write_file`, `present_files`; tổng quantity là `12` |
| Preview và download artifact | Mở được Markdown trong UI; download HTTP 200, bytes khớp file trên đĩa |
| Tạo agent bằng hội thoại | Tạo và lưu `flow-smoke-20260912` cùng SOUL tiếng Việt |
| Tên agent không hợp lệ/trùng tên | Chặn đúng, có thông báo trong UI |
| Catalog, tìm kiếm, ghim, profile, mở chat | Hoạt động; agent mới có trạng thái available |
| Áp dụng SOUL riêng | Trả lời `[FLOW-SMOKE] 8 + 13 + 21 = 42.` |
| Branch conversation | Tạo nhánh mới, giữ đúng agent và lịch sử |
| Khởi động lại Gateway | Agent, hội thoại, upload và artifact vẫn còn |
| Settings: Skills/Tools | Tải được; không có skill Office; MCP rỗng theo config thử |
| `/workspace/office` và `/api/office/projects` | 404 |
| Link chat agent Office cũ | Báo agent không khả dụng; không cho gửi tin |
| Model lỗi trước checkpoint | Sau sửa: giữ câu hỏi, có lỗi cố định và nút Restore message |
| Khôi phục, đổi model, gửi lại | Trả lời đúng `6 + 7 = 13`; câu hỏi chỉ xuất hiện một lần |
| Reasoning ở chế độ Pro | Hiện Medium; trả lời `10 + 4 = 14`; thời gian 2 giây giữ nguyên khi mở lại panel |

Tổng kiểm kê API cuối phiên: **4 threads idle, 7 runs thành công, 2 lỗi đã biết**.
Hai lỗi là lần đầu chưa tìm thấy credential và một model hỏng được thêm có
chủ đích để kiểm tra recovery. Không có lỗi mới trong console ở hai lượt gửi
thành công cuối sau bản sửa.

## Lỗi đã sửa trong đợt kiểm tra

1. `RuntimeFeatures(token_budget=True)` trước đây tạo middleware với
   `enabled=False`, khiến giới hạn không có hiệu lực. Đã bật config khi flag
   là True, giữ nguyên hành vi False và middleware được cấu hình riêng.
   Vị trí: `backend/packages/harness/vassilflow/agents/factory.py`.
2. Run lỗi trước checkpoint làm mất câu hỏi đang hiển thị, chỉ còn lỗi trong
   console. Đã giữ bản human message chưa lưu, hiển thị lỗi được phân loại bằng
   thông báo cố định và cho khôi phục vào composer để sửa/gửi lại thủ công.
   Không đưa traceback hoặc nội dung cấu hình model vào lỗi UI.
   Vị trí: `frontend/src/core/threads/hooks.ts`, `submission-error.ts` và
   `frontend/src/components/workspace/chats/thread-chat-page.tsx`.
3. Agent không tồn tại chỉ có khung chat không gửi được. Đã thêm giải thích
   sau khi tải catalog xong, không báo lỗi trong lúc đang tải.
   Vị trí: `frontend/src/components/workspace/agent-welcome.tsx`.
4. Nhãn reasoning trống khi chưa lưu lựa chọn riêng. Đã hiển thị cùng mức
   mặc định mà request thực sự sử dụng; không thay đổi cách gửi request.
   Vị trí: `frontend/src/components/workspace/input-box.tsx`.
5. Hoàn tất stream gây cảnh báo chuyển controlled/uncontrolled ở phần reasoning.
   Đã thêm adapter giữ trạng thái mở/đóng và thời gian đo được, không sửa
   component `ai-elements` sinh tự động.
   Vị trí: `frontend/src/components/workspace/messages/message-reasoning.tsx`.

Đây là các lỗi tìm thấy trong nền tảng dùng chung; không quy toàn bộ nguyên
nhân cho việc loại bỏ Office.

## Kiểm tra tự động

- Backend: **5.770 passed, 50 skipped**. Không chạy
  `test_sandbox_orphan_reconciliation_e2e.py` vì cần Docker thật; live tests của
  suite bị tắt, các lượt model thật được thực hiện riêng qua UI như trên.
- Frontend: **496/496 unit tests**, 58 files; typecheck và lint đều pass.
- Thêm regression cho reasoning completion; Playwright thu thập được test,
  chưa chạy spec bằng browser tự động. Luồng tương ứng đã thử trực tiếp với
  model thật, bao gồm kiểm tra console và mở lại panel.
- `git diff --check`: pass.

## Các giới hạn và lưu ý còn lại

- Cấu hình local hiện có `agents_api.enabled=false`. Muốn tạo/quản lý agent
  qua UI cần bật mục này; trong đợt kiểm tra chỉ bật trên bản config riêng.
- Credential Codex trên máy nằm trong `CODEX_HOME`; loader hiện hỗ trợ
  `CODEX_AUTH_PATH` hoặc `~/.codex/auth.json`. Phiên thử đặt
  `CODEX_AUTH_PATH` tới file đăng nhập đang có. Đây là điều kiện cấu hình,
  chưa thay đổi cơ chế dò credential của provider.
- Nút đính kèm mở được file chooser, nhưng extension Chrome từ chối
  `setFiles` do chưa cho truy cập file URL. Vì vậy chưa xác nhận đầy đủ luồng
  chọn file qua UI; upload backend và sử dụng file trong chat đã được kiểm tra.
- Khôi phục câu hỏi lỗi là trạng thái của phiên trang hiện tại, chưa được lưu
  bền qua reload nếu backend chưa checkpoint câu hỏi.
- Còn cảnh báo development về thiếu mô tả accessibility ở một số dialog.
  Có một lần form tạo agent trở về bước đặt tên trong phiên dev; agent đã lưu
  thành công, nhưng chưa tái hiện ổn định để xác định nguyên nhân reset form.
- Chưa kiểm tra triển khai Docker/production, các channel bên ngoài hoặc toàn
  bộ provider model khác.

## Dữ liệu kiểm tra và dọn phiên

Hai service test và các tab test đã được đóng; model lỗi chủ đích đã được gỡ
khỏi config/launcher test. Dữ liệu thử được giữ lại để đối chiếu:

- `.vassilflow/live-smoke-20260912/final-api-inventory.json`
- `.vassilflow/live-smoke-20260912/gateway.stderr.log`
- `.vassilflow/live-smoke-20260912/gateway.before-credential-override.stderr.log`
- `logs/direct-review-backend-tests.txt`
- `logs/frontend-app-review-3044-20260912.stdout.log`
- `logs/frontend-app-review-3044-20260912.stderr.log`

Các file runtime/config nằm trong thư mục bị Git ignore; không đưa chúng vào
commit vì bản config thử có thể chứa thông tin đăng nhập được kế thừa.
