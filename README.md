# UraOS — Ura, trợ lý AI cá nhân kiểu J.A.R.V.I.S.

Ura là trợ lý AI lấy cảm hứng từ J.A.R.V.I.S. trong *Iron Man*: nói chuyện bằng giọng nói tiếng Việt,
nhớ thông tin về bạn, quản lý việc cần làm, nhắc việc, tìm kiếm Internet, mở trang web, kiểm tra hệ thống…
Bộ não của Ura là mô hình Claude (Anthropic) với khả năng gọi công cụ (tool use).

## Tính năng

| Năng lực | Mô tả |
|---|---|
| 🎙 Giọng nói | Nói với Ura bằng micro (nhận dạng giọng nói tiếng Việt của trình duyệt), Ura đọc câu trả lời thành tiếng |
| 👂 Từ khóa đánh thức | Bật **WAKE**, rồi nói “**Ura ơi**, …” mà không cần bấm nút |
| 🧠 Bộ nhớ dài hạn | “Nhớ giúp tôi là tôi thích cà phê đen” → Ura ghi nhớ qua các phiên (`data/memory.json`) |
| ✅ Việc cần làm & nhắc việc | “Nhắc tôi gọi cho mẹ sau 30 phút” → Ura đọc lời nhắc + thông báo trên máy |
| 🌐 Tìm kiếm Internet | Tin tức, thời tiết, tỷ giá… qua công cụ tìm kiếm web của Claude |
| 🧮 Tính toán chính xác | Biểu thức toán học, lượng giác, logarit… |
| 🖥 Trạng thái hệ thống | CPU, RAM, ổ đĩa của máy chạy Ura |
| 🔗 Điều khiển giao diện | “Mở YouTube”, “đổi giao diện sang màu đỏ” |
| ⌨️ Chế độ terminal | `python cli.py` cho ai thích gõ lệnh |

## Cài đặt nhanh

Yêu cầu: Python 3.10+, khóa API Anthropic (tạo tại https://platform.claude.com).

```bash
git clone https://github.com/minh-dtx1/UraOS.git
cd UraOS
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env        # rồi mở .env và điền ANTHROPIC_API_KEY, URA_USER_NAME
python server.py            # mở http://localhost:8000 bằng Chrome hoặc Edge
```

Hoặc trò chuyện trong terminal: `python cli.py`

> Nhận dạng giọng nói cần **Chrome/Edge** và quyền micro. Để có giọng đọc tiếng Việt, hệ điều hành cần có giọng
> “Vietnamese” (Windows: Settings → Time & Language → Speech → Add voices → Tiếng Việt).

## Cấu hình (`.env`)

| Biến | Mặc định | Ý nghĩa |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | Khóa API (bắt buộc) |
| `URA_USER_NAME` | `sếp` | Ura gọi bạn bằng tên này |
| `URA_MODEL` | `claude-opus-5-5` | Mô hình Claude |
| `URA_EFFORT` | `medium` | Mức suy nghĩ: `low` (nhanh, rẻ) … `max` (kỹ nhất) |
| `URA_WEB_SEARCH` | `1` | `0` để tắt tìm kiếm Internet |
| `URA_PORT` | `8000` | Cổng máy chủ web |

## Kiến trúc

```
UraOS/
├── server.py        # Máy chủ FastAPI: phục vụ giao diện + API streaming (NDJSON)
├── cli.py           # Giao diện dòng lệnh
├── ura/
│   ├── config.py    # Đọc cấu hình .env
│   ├── brain.py     # Nhân cách Ura + vòng lặp Claude ⇄ công cụ (streaming)
│   └── tools.py     # Các công cụ: bộ nhớ, việc cần làm, tính toán, hệ thống, mở web…
├── web/index.html   # Giao diện HUD: lõi năng lượng, giọng nói, từ khóa “Ura ơi”
└── data/            # Bộ nhớ và danh sách việc (tự tạo, không đưa lên git)
```

Luồng xử lý: Trình duyệt (giọng nói → văn bản) → `POST /api/chat` → `brain.Conversation` gửi tới Claude →
Claude gọi công cụ → `tools.py` thực thi → kết quả trả lại Claude → câu trả lời stream về trình duyệt → đọc thành tiếng.

## Dạy Ura kỹ năng mới

Thêm một hàm vào `ura/tools.py` với decorator `@tool` là xong — Claude tự biết khi nào dùng:

```python
@tool("bat_den", "Bật/tắt đèn trong nhà.",
      {"phong": {"type": "string"}, "bat": {"type": "boolean"}}, ["phong", "bat"])
def bat_den(phong: str, bat: bool) -> dict:
    # gọi API nhà thông minh (Home Assistant, Tuya, ...) ở đây
    return {"phong": phong, "trang_thai": "bật" if bat else "tắt"}
```

## Lộ trình phát triển

- [ ] Giọng đọc tự nhiên hơn (TTS chất lượng cao) và nhận dạng giọng nói ngoại tuyến (Whisper)
- [ ] Điều khiển nhà thông minh (Home Assistant), lịch Google, email
- [ ] Ứng dụng di động / chạy thường trú trên Raspberry Pi
- [ ] Kết nối kho dữ liệu kỹ thuật cầu đường (DTXM_GROUP) để Ura tra cứu tiêu chuẩn, định mức
