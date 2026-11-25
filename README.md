# LyricNow - Ứng Dụng Lời Bài Hát Nổi Đa Ngôn Ngữ Cho Windows

**LyricNow** là ứng dụng hiển thị lời bài hát nổi (Floating Lyrics Overlay) dành cho **Windows 10 / Windows 11**. Ứng dụng tự động nhận diện bài hát đang phát từ YouTube, Chrome, Edge, Spotify hoặc các trình phát nhạc trên Windows, đồng bộ lời bài hát theo thời gian thực, hỗ trợ **tự nhận diện bài hát nước ngoài -> tạo phiên âm (Romaji / Pinyin / Latin) -> tự dịch tiếng Việt** ngay dưới lời gốc.

---

## Tải App Về Máy Tính (Không Cần Clone Code Hay Cài Python)

[![Tải LyricNow cho Windows](https://img.shields.io/badge/T%E1%BA%A3i%20LyricNow.exe-Windows%2010%2F11-0ea5e9?style=for-the-badge&logo=windows)](https://github.com/quanganh296/MyLyricForMusic/releases/latest/download/LyricNow.exe)
[![Xem Tất Cả Bản Phát Hành](https://img.shields.io/badge/GitHub%20Releases-Xem%20phi%C3%AAn%20b%E1%BA%A3n-27272a?style=for-the-badge&logo=github)](https://github.com/quanganh296/MyLyricForMusic/releases/latest)

### Hướng dẫn cài đặt & sử dụng nhanh (2 bước)
1. Nhấn nút **[Tải LyricNow.exe](https://github.com/quanganh296/MyLyricForMusic/releases/latest/download/LyricNow.exe)** (hoặc mở mục **[Releases](https://github.com/quanganh296/MyLyricForMusic/releases/latest)** và tải file `LyricNow.exe`).
2. Nhấp đúp mở file **`LyricNow.exe`** là dùng được ngay — không cần cài đặt, không cần Python, không cần tải mã nguồn.
   - *Lưu ý:* Nếu lần đầu mở Windows SmartScreen hiện thông báo bảo vệ tệp tải từ mạng, chọn **More info** -> **Run anyway**.
   - Bật nhạc trên YouTube (Chrome / Edge), Spotify hoặc trình phát bất kỳ — lời bài hát sẽ tự động hiện và chạy theo nhạc.

---

## Tính Năng Nổi Bật

- **2 chế độ hiển thị linh hoạt:**
  - **Mode 1 (Video + Lyric):** Phát video nhạc bên phải, lời bài hát đồng bộ bên trái trên nền mờ từ video; màu chữ tự điều chỉnh tương phản hài hòa theo nền video; hỗ trợ phóng to toàn màn hình (`F11` / `Esc`) tự tắt độ mờ nền khi toàn màn hình.
  - **Mode 2 (Lyric Only):** Chỉ hiển thị lời ở chính giữa cửa sổ kính mờ, có thể phóng to / thu nhỏ chữ & khung (`Ctrl + Cuộn chuột` hoặc nút `+` / `-`), thu gọn nhanh (Compact) và kéo đổi kích thước 8 cạnh mượt mà.
- **Đa ngôn ngữ & Tự dịch 3 tầng chuẩn Vietsub:**
  - Hỗ trợ tìm, giải mã UTF-8 và hiển thị sắc nét lời tiếng **Nhật, Hàn, Trung, Anh, Thái, Nga, Việt...**
  - Tự động nhận diện bài hát nước ngoài và hiển thị chuẩn 3 tầng: **Lời gốc -> Phiên âm (Romaji / Pinyin / Latin) -> Khoảng tách -> Bản dịch tiếng Việt in đậm** (tự ẩn phiên âm với ngôn ngữ hệ Latin và tự ẩn dòng dịch khi bài hát đã là tiếng Việt).
  - Có nút bật/tắt dịch nhanh trên thanh công cụ và tùy chọn ngôn ngữ dịch (Tiếng Việt, English, 日本語, 한국어, 中文) trong Cài đặt.
- **Đồng bộ thời gian thực chính xác:**
  - Bắt bài hát qua Windows GSMTC kể cả khi chuyển tab trình duyệt; tự phát hiện và bù độ lệch nhạc dạo cho video YouTube bị cắt ngắn; cho phép chỉnh nhanh bằng nút **Câu Trước / Câu Tiếp** và lưu riêng từng bài.
- **Theo dõi pin tai nghe Bluetooth:**
  - Tự động hiển thị phần trăm pin tai nghe Bluetooth đang kết nối và trạng thái kết nối **tai Trái / tai Phải / cả 2 bên** (hỗ trợ HFP, AirPods BLE, Google Fast Pair, BLE GATT).
- **Tìm kiếm lời linh hoạt:**
  - Tìm lời trực tuyến từ **ZingMP3, LRCLIB, NetEase**, tìm theo **đường link YouTube (URL)** hoặc dán lời thủ công.
- **Tùy biến giao diện đầy đủ:**
  - Chỉnh phông chữ, cỡ chữ, bảng màu highlight tùy chọn, độ trong suốt đồng bộ toàn app, khóa vị trí cửa sổ, điều chỉnh âm lượng hệ thống trực tiếp.

---

## Dành Cho Lập Trình Viên (Chạy Từ Mã Nguồn)

Nếu bạn muốn tự chỉnh sửa mã nguồn hoặc tự đóng gói lại `.exe`:

```powershell
git clone https://github.com/quanganh296/MyLyricForMusic.git
cd MyLyricForMusic
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Đóng gói lại thành file `.exe` đơn lẻ:

```powershell
.\.venv\Scripts\pyinstaller.exe LyricNow.spec --noconfirm
```

Tệp chạy sẽ nằm tại `dist\LyricNow.exe`.

---

## Cấu Trúc Dự Án

```text
MyLyricForMusic/
├── .github/workflows/
│   └── release.yml           # Tự động build & đăng LyricNow.exe lên GitHub Releases
├── assets/                   # Biểu tượng ứng dụng (.ico / .png)
├── modules/
│   ├── media_listener.py     # Lắng nghe bài hát & thời gian thực từ Windows GSMTC
│   ├── lyrics_provider.py    # Tìm, xếp hạng & phân tích lời đồng bộ (ZingMP3 / LRCLIB / NetEase)
│   ├── lyrics_translator.py  # Tự nhận diện ngôn ngữ, tạo phiên âm & dịch chạy ngầm
│   ├── overlay_window.py     # Cửa sổ nổi Mode 1 (Video+Lyric) & Mode 2 (Lyric Only)
│   ├── video_player.py       # Phát & đồng bộ video cho Mode 1
│   ├── theme_extractor.py    # Tạo nền mờ video & tính màu chữ tương phản tự động
│   ├── bt_battery_monitor.py # Đọc pin tai nghe Bluetooth (Trái / Phải / Tổng)
│   ├── settings_dialog.py    # Bảng cài đặt giao diện, đồng bộ & ngôn ngữ dịch
│   ├── search_dialog.py      # Tìm lời trực tuyến, theo link YouTube & dán lời thủ công
│   ├── volume_manager.py     # Điều khiển âm lượng hệ thống Windows
│   ├── icon_factory.py       # Bộ biểu tượng Font Awesome (QtAwesome)
│   └── cache_manager.py      # Lưu đệm lời, độ lệch thời gian & bản dịch
├── app.py                    # Điểm khởi chạy ứng dụng
├── LyricNow.spec             # Cấu hình đóng gói PyInstaller
├── requirements.txt          # Danh sách thư viện Python
└── README.md
```
