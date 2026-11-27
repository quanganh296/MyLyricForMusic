# Lịch sử cập nhật LyricNow

## v1.1.9
- **Tìm kiếm lời bài hát bất đồng bộ 100% — hết delay/đứng lyric và video khi mở tìm kiếm:** Chuyển toàn bộ thao tác tìm lời trực tuyến, phân tích link YouTube và tải xem trước LRC sang các luồng nền (`_OnlineSearchWorker`, `_YouTubeSearchWorker`, `_RemoteLrcWorker`) kết hợp mở hộp thoại Tìm kiếm không khóa cửa sổ chính, giúp nhạc, video và lời Karaoke tiếp tục chạy mượt 60 FPS không hề giật lag.
- **Giao diện Cài đặt đồng bộ nền mờ & màu sắc thích ứng giống hệt cửa sổ ứng dụng:** Bảng Cài đặt (`SettingsDialog`) hiển thị cùng nền mờ từ ảnh/video bài hát đang phát kèm thẻ kính mờ trong suốt và màu nhấn thích ứng (`accent_hex`), đồng thời tự động chuyển nền theo thời gian thực nếu bài hát đổi trong lúc đang mở Cài đặt.
- **Thêm 2 nút tua video/bài hát 10 giây (`-10s`, `+10s`) và nút chuyển video/bài hát tiếp theo (`Bài Tiếp`):** Gửi lệnh điều khiển bất đồng bộ qua Windows GSMTC (`try_change_playback_position_async` / `try_skip_next_async`) kèm đồng bộ tức thì cho video và lời bài hát trong app, tự động thu gọn thông minh khi cửa sổ Mode 2 hẹp và hỗ trợ đầy đủ 8 ngôn ngữ.

## v1.1.8
- **Nhận diện chính xác tai nghe Trái / Phải đang đeo trên Apple AirPods (`AirPods 2` / `AirPods Pro`):** Nâng cấp bộ giải mã Apple Proximity Pairing theo đúng chuẩn 27 byte (`CAPod` / `AirPodsDesktop`), đọc chính xác cảm biến đeo tai (`in_ear`) cùng cờ đổi chiều khi tai còn lại nằm trong hộp sạc (`bit 6` XOR) và ưu tiên gói tin từ bên tai đang đeo — sửa triệt để tình trạng đeo tai bên **Phải** nhưng bị hiển thị thành **Trái**.
- **Gộp trọn vẹn toàn bộ bản sửa ổn định từ v1.1.7:** Không còn cửa sổ lỗi `Failed to load Python DLL ...\_MEIxxxx\python311.dll` khi tự khởi động lại sau update, không kẹt con trỏ/dừng video khi đóng bảng chọn thiết bị loa/tai nghe, và lọc ổn định % pin Bluetooth hết nhảy 90%–60%–50%–90%.

## v1.1.7
- **Chấm dứt hoàn toàn lỗi `Failed to load Python DLL ...\_MEIxxxx\python311.dll` sau khi tự cập nhật:** Dọn sạch toàn bộ biến môi trường cũ của PyInstaller/Qt (`_PYI_*`, `_MEIPASS*`, đường dẫn `_MEI` trong `PATH`) kèm `PYINSTALLER_RESET_ENVIRONMENT=1` và tách nhóm tiến trình sạch khi khởi chạy bản mới; đồng thời sửa lỗi đóng gói manifest trên GitHub Actions (`manifestVersion="1.0"`) để bản release Windows luôn build chuẩn xác.
- **Sửa triệt để lỗi treo con trỏ chuột & dừng video/âm thanh sau khi đóng bảng chọn thiết bị loa/tai nghe:**
  - Chuyển bảng chọn loa (`AudioOutputPopup`) khỏi cơ chế `Qt.WindowType.Popup` chiếm chuột mức hệ điều hành sang cửa sổ trượt mượt `Tool` + làm mờ trực tiếp bằng painter (không gọi `setWindowOpacity` gây lỗi lớp trong suốt trên Windows) và kích hoạt mở bảng khi nhả chuột (`mouseReleaseEvent`).
  - Nuốt gọn cú click ra ngoài để đóng bảng chọn mà không làm bấm nhầm vào khung video gây dừng nhạc, đồng thời giữ con trỏ dạng bấm (`PointingHandCursor`) và mọi nút hoạt động bình thường ngay lập tức.
  - Thu hẹp vùng bấm tạm dừng video chỉ trong đúng khung hình 16:9 của video.
- **Ổn định hiển thị % pin tai nghe Bluetooth (hết nhảy bất thường 90% → 60% → 50% → 90%):**
  - Sửa bộ giải mã Google Fast Pair BLE theo đúng chuẩn khung TLV (`i += 1 + field_len`) để không đọc nhầm byte ngẫu nhiên làm % pin giả, và chỉ nhận gói BLE khớp đúng địa chỉ MAC hoặc tên tai nghe đang kết nối.
  - Thêm bộ lọc chống nhiễu nhảy vọt (`_BatteryValueFilter`): cập nhật ngay bước pin bình thường (`<= 10%`), còn các bước nhảy bất thường (`> 10%`) phải ổn định qua 3 chu kỳ liên tiếp mới cập nhật.

## v1.1.6
- **Kiểm tra cập nhật trực tiếp mỗi 60 giây khi app đang chạy:** Dùng cơ chế kiểm tra chuyển hướng nhẹ không bị giới hạn GitHub API; ngay khi bản phát hành mới sẵn sàng, ứng dụng đang mở sẽ lập tức đóng cửa sổ cũ (kể cả hộp thoại phụ) và bật ngay bảng yêu cầu cập nhật lên trên cùng.
- **Giảm tối đa báo nhầm của Windows Defender / Antivirus:**
  - Tắt nén **UPX** (`upx=False`) trong `LyricNow.spec` (nguyên nhân chính gây báo nhầm nhận diện heuristic trên file đóng gói PyInstaller).
  - Nhúng đầy đủ thông tin tệp Windows PE (`version_info.txt`: tên sản phẩm, mô tả, phiên bản) và Manifest `asInvoker` chuẩn Windows 10/11 (`LyricNow.manifest`).
  - Thay cơ chế tự cập nhật bằng tệp `.bat` ẩn / `cmd.exe` sang cơ chế đổi tên trực tiếp nguyên bản của Windows NTFS (`LyricNow.exe` -> `LyricNow.exe.old`) và tự dọn tệp cũ ở lần chạy tiếp theo, kèm mã kiểm tra toàn vẹn `SHA256SUMS.txt` trên GitHub Release.

## v1.1.5
- **Sửa triệt để lỗi ứng dụng tự thoát đột ngột sau một thời gian chạy:** Tắt chế độ tự thoát ngầm khi đóng popup/hộp thoại (`setQuitOnLastWindowClosed(False)`), khắc phục race condition hủy `QThread` khi chuyển bài/tải video/dịch lời, dừng sạch animation khi đóng bảng chọn loa, và bổ sung lớp bảo vệ lỗi toàn cục (`lyricnow_error.log`) giúp app chạy bền bỉ không bị văng bất ngờ.
- **Tải lời & dịch lời siêu tốc không còn đứng hình hay delay tới cuối bài:** Chuyển toàn bộ quá trình tìm lời bài hát sang luồng nền (`LyricFetchWorker`) để giao diện luôn mượt 60 FPS; nâng cấp bộ dịch truyền phát từng đoạn (`partial_translated`) ưu tiên dịch ngay câu đang hát trước (< 0.5 giây) kèm xử lý song song và giữ kết nối HTTP Keep-Alive.
- **Bảo vệ độ lệch thời gian (`sync_offset`) khi đổi ngôn ngữ / mở Cài đặt:** Mở rộng dải offset trong Cài đặt (`-120s` đến `+120s`), không ghi đè mất độ lệch của bài hát đang nghe khi chỉ đổi ngôn ngữ ứng dụng hoặc ngôn ngữ dịch, và chặn lưu các giá trị offset lệch quá đà vào cache.

## v1.1.4
- **Chuyển nhanh thiết bị phát âm thanh (Loa máy tính / Tai nghe Bluetooth) bằng menu trượt lên:** Nhấn trực tiếp vào thanh pin tai nghe ở góc dưới bên trái để trượt lên danh sách toàn bộ loa/tai nghe đang hoạt động trên Windows, cho phép chuyển đổi tức thì giữa loa Bluetooth và loa hệ thống máy tính mà không cần bật/tắt Bluetooth; thanh âm lượng cũng tự động đồng bộ ngay theo thiết bị vừa chọn.

## v1.1.3
- **Sửa triệt để lỗi nhận sai lời & dịch sai ngôn ngữ (VD: nhạc Nhật/Hàn/Trung bị nhận nhầm sang bản Tiếng Anh trùng tên):** Khóa ưu tiên khớp ca sĩ (từ cả tên kênh lẫn tên video YouTube như `Michita ft 愛海`) và kiểm tra tương thích hệ chữ trước khi so thời lượng, tự động làm mới cache cũ bị khớp sai ca sĩ.
- **Khóa đúng video YouTube khi bật/tắt nút `Video` trong Mode Karaoke:** Chấm điểm chọn chính xác video đang phát theo tiêu đề + tên kênh + thời lượng, khóa `video_id` và lưu đệm luồng phát để khi bật/tắt `Video` trong Mode 3 luôn giữ nguyên đúng video đó mà không tự tìm sang video khác.
- **Bổ sung Ngôn ngữ ứng dụng (App Language) trong Cài đặt:** Hỗ trợ chuyển đổi trực tiếp giao diện ứng dụng sang **Tiếng Việt, English, 日本語 (Tiếng Nhật), 中文 (Tiếng Trung), 한국어 (Tiếng Hàn), ภาษาไทย, Español, Français** và mở rộng thêm các ngôn ngữ đích khi dịch lời bài hát.

## v1.1.2
- **Hiển thị tên bài hát thông minh & tự di chuyển mượt mà:** Khi có khung **Video** (Mode 1 hoặc Mode 3 bật Video), tên bài hát tự động hiển thị căn giữa ngay bên dưới khung video; khi chuyển sang chế độ chỉ có lời (**Mode 2 Lyric** hoặc **Mode 3 tắt Video**), tên bài hát tự trượt mượt lên đầu cửa sổ ở chính giữa (`Center`) còn phần lời nhạc nằm gọn phía dưới.
- **Kiểm tra & bắt buộc cập nhật khi có phiên bản mới:** Ứng dụng tự động kiểm tra bản phát hành mới nhất từ GitHub; nếu đang chạy phiên bản cũ sẽ hiển thị thông báo bắt buộc cập nhật (kèm danh sách thay đổi và nút tải/cập nhật tự động 1 chạm) thay vì cho dùng tiếp bản cũ.

## v1.1.1
- **Nút chọn chế độ dạng menu thả xuống (Dropdown):** Gộp nút chọn chế độ thành 1 ô gọn đẹp có mũi tên chỉ xuống bên phải, bấm vào sẽ thả danh sách chọn giữa **Video (Mode 1)**, **Lyric (Mode 2)** và **Karaoke (Mode 3)**.
- **Thêm Mode 3 — Hát Karaoke sáng chữ từng từ khớp nhịp:** Chữ chưa hát luôn nhạt màu, hát tới từ nào sẽ sáng màu quét mượt từ trái sang phải theo đúng nhịp bài hát — tự động nhận diện nhịp chậm (ballad) lẫn nhịp nhanh (rap) và hỗ trợ dấu phẩy/ngắt nghỉ tự nhiên cũng như LRC timestamp từng từ.
- **Nút bật/tắt `Video` riêng ngay dưới nút chọn Mode + Hiệu ứng chuyển cảnh mượt mà:** Khi tắt Video trong Mode 3, khung Video trượt nhanh sang trái và mờ dần biến mất, còn phần Lyric trượt mượt sang phải rồi tự căn dừng đúng chính giữa màn hình (và đảo chiều mượt mà khi bật lại Video).

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

