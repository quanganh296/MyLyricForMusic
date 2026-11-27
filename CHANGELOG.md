# Lịch sử cập nhật LyricNow

## v1.1.0
- **Thanh công cụ tối giản chuẩn Windows 11 với hiệu ứng di chuột mượt mà:** Bỏ toàn bộ viền/khung nút thô trên thanh công cụ — ở trạng thái thường các biểu tượng hiển thị gọn nhẹ trong suốt; khi di chuột vào nút nào sẽ nổi nền tương ứng, riêng nút đóng **`X`** đổi nền **đỏ (`#e81123`)** cùng dấu **`X` màu trắng** sắc nét.
- **Bổ sung cụm nút điều khiển cửa sổ (`—` Thu nhỏ, `□`/`❐` Phóng to / Thu gọn, `✕` Đóng):** Hỗ trợ thu nhỏ cửa sổ xuống thanh tác vụ và biểu tượng vector nét mảnh đồng bộ trên cả Mode 1 và Mode 2.
- **Chuẩn hóa quy tắc đánh số phiên bản:** Từ bản này áp dụng quy tắc tăng số theo mốc 9 (`1.0.9` -> `1.1.0`, tiếp theo `1.1.1` ... `1.1.9` -> `1.2.0`).

## v1.0.10
- **Bắt đúng nhịp & đúng câu hát khi mở app ở bất kỳ đoạn nào (kể cả MV dài hơn bản Audio):** Ưu tiên đối khớp chính xác thời lượng giữa video YouTube (như *Lỡ Say Bye Là Bye* MV `4:08` hay *Đừng Làm Trái Tim Anh Đau* MV `5:26`) với bản lời có cùng thời lượng MV thay vì chọn nhầm bản audio studio ngắn hơn 30–45 giây bị lệch nhịp.
- **Tự cập nhật lại bản lời khớp thời lượng khi Chrome báo trễ `duration`:** Khi mới chuyển bài mà trình duyệt chưa kịp gửi độ dài video, app sẽ tự căn chỉnh lại ngay khi có thời lượng thật và tự làm mới cache cũ bị lệch thời lượng.
- **Hỗ trợ tốc độ phát (`playback_rate`):** Đồng bộ chính xác cả khi bạn mở app giữa bài hoặc tăng/giảm tốc độ phát nhạc (1.25x, 1.5x...).

## v1.0.9
- **Nút kéo âm lượng hình tròn mượt mà:** Thiết kế lại thanh âm lượng với nút kéo tròn mịn (khắc phục lỗi hiển thị ô vuông và lỗi số `%` đè lên thanh trượt khi thu nhỏ cửa sổ), màu thanh âm lượng đồng bộ theo tông màu video và hỗ trợ bấm chọn nhanh mức âm lượng.
- **Tự động đồng bộ âm lượng theo thiết bị phát đang dùng (Loa máy / Tai nghe):** Tự động nhận diện khi chuyển đổi giữa loa máy tính và tai nghe Bluetooth / tai nghe dây, cập nhật thời gian thực mức âm lượng và trạng thái tắt tiếng (Mute) theo hệ thống Windows (sửa lỗi hiển thị `0%` khi đang nghe nhạc bằng tai nghe, đồng thời sửa lỗi nhận trạng thái Mute `GetMute`).
- **Tự động ghi chú cập nhật cho mỗi bản Release:** GitHub Release nay tự động trích xuất nội dung cập nhật chi tiết của từng phiên bản từ `CHANGELOG.md`.

## v1.0.8
- **Nền mờ & đổi màu tự động cho Mode 2:** Mode 2 (chỉ hiện Lyric) nay có cùng nền mờ theo ảnh/video bài hát và tự đổi màu chữ, viền, nút chọn giống hệt Mode 1 mà không cần giải mã luồng video tốn CPU.

## v1.0.7
- **Hiển thị phiên bản ứng dụng:** Thêm dòng chữ phiên bản gọn đẹp ở góc dưới bên trái cửa sổ ứng dụng (hiển thị trên cả Mode 1, Toàn màn hình và Mode 2).

## v1.0.6
- **Nhận diện chuẩn phiên bản bài hát & xem trước lời trực tiếp:** Giữ nguyên nhãn phiên bản (`Solo Version`, `Remix`, `Acoustic`, `Demo`...) khi tự động tải và tìm kiếm; thêm khung xem trước lời ngay trong hộp thoại tìm kiếm; sửa phím `Enter` và lọc khớp ca sĩ chính xác hơn.

## v1.0.5
- **Sửa lỗi chọn sang lời bài hát khác trong ô tìm kiếm:** Loại bỏ các mục rỗng lời từ ZingMP3/LRCLIB, hiển thị thời lượng + câu lời xem trước, cập nhật lời tức thì ngay khi bấm Áp dụng và lưu cache lựa chọn thủ công.

## v1.0.4
- **Sửa lỗi nền mờ dính logo Chrome/Google khi chuyển bài:** Lọc bỏ biểu tượng trình duyệt khi chuyển tab, ưu tiên tải thumbnail HD theo video và khóa chống ghi đè ngược từ GSMTC.

## v1.0.3
- **Sửa lỗi đồng bộ nhảy sớm & nhận diện bài hát:** Cố định đồng hồ thời gian thực khi chuyển bài trên Chrome, chặn nhận nhầm lời tiếng Hàn/Trung cho bài hát tiếng Việt và lọc bài Demo/Remix chuẩn hơn.

## v1.0.2
- **Nhận diện bài hát chính xác hơn:** Cải thiện đối khớp tên bài & nghệ sĩ (như *Đừng Làm Trái Tim Anh Đau - Sơn Tùng M-TP*), tách rõ tên bài có dấu gạch nối.

## v1.0.1
- **Cải thiện đồng bộ thời gian thực & lời đa ngôn ngữ:** Sửa kẹt lời ở câu đầu khi mở giữa bài, tự bù intro cho video cắt ngắn, cải thiện chất lượng dịch 3 tầng (Lời gốc + Phiên âm + Bản dịch).

## v1.0.0
- **Phát hành đầu tiên:** Ứng dụng lời bài hát nổi `LyricNow.exe` chạy độc lập trên Windows 10/11 với 2 chế độ hiển thị, dịch lời đa ngôn ngữ và theo dõi pin tai nghe Bluetooth.

