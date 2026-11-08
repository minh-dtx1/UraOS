"""Bộ não của Ura: vòng lặp hội thoại + gọi công cụ trên Claude API (streaming)."""
from __future__ import annotations

import json
import threading
from typing import Any, Iterator

import anthropic

from . import tools
from .config import settings

SYSTEM_PROMPT = f"""Bạn là Ura — trợ lý AI cá nhân của {settings.user_name}, lấy cảm hứng từ J.A.R.V.I.S. \
trong phim Iron Man nhưng là một nhân cách riêng.

Tính cách:
- Điềm tĩnh, thông minh, lịch thiệp, hơi dí dỏm kiểu quản gia Anh; trung thành và chủ động.
- Gọi người dùng là "{settings.user_name}". Mặc định trả lời bằng tiếng Việt; dùng ngôn ngữ khác nếu người dùng dùng.
- Câu trả lời thường được đọc thành giọng nói, nên hãy ngắn gọn, tự nhiên như đang nói chuyện: \
1–3 câu cho câu hỏi đơn giản, không dùng bảng, tránh markdown rườm rà trừ khi người dùng xin chi tiết.

Cách làm việc:
- Chủ động dùng công cụ: xem giờ, tính toán chính xác, ghi nhớ/tra cứu bộ nhớ dài hạn, quản lý việc cần làm \
và lời nhắc, kiểm tra hệ thống, mở trang web, tìm kiếm Internet cho thông tin mới.
- Khi người dùng chia sẻ thông tin cá nhân đáng nhớ (sở thích, lịch, dự án), hãy lưu bằng công cụ remember.
- Nếu không chắc, nói thẳng và đề xuất cách kiểm tra; không bịa số liệu.
- Sau khi dùng công cụ, báo kết quả ngắn gọn như J.A.R.V.I.S. báo cáo cho Tony Stark."""


def _server_tools() -> list[dict]:
    if not settings.web_search:
        return []
    return [{
        "type": "web_search_20260209",
        "name": "web_search",
        "max_uses": 5,
        "user_location": {"type": "approximate", "country": "VN", "timezone": "Asia/Ho_Chi_Minh"},
    }]


TOOLS = tools.definitions() + _server_tools()


def _context_block() -> str:
    """Bối cảnh chèn vào tin nhắn đầu tiên của phiên (để system prompt cố định -> cache tốt)."""
    now = tools.get_datetime()
    memories = tools.recall()["memories"]
    mem_txt = "\n".join(f"- [{m['id']}] {m['fact']}" for m in memories) or "(chưa có)"
    return (f"<context>\nThời điểm bắt đầu phiên: {now['weekday']}, {now['iso']} (giờ Việt Nam)\n"
            f"Những điều Ura đã ghi nhớ về {settings.user_name}:\n{mem_txt}\n</context>\n\n")


class Conversation:
    """Một phiên hội thoại. Lịch sử chỉ được nối thêm (append-only), không sửa lượt cũ."""

    def __init__(self, client: anthropic.Anthropic | None = None):
        self.client = client or anthropic.Anthropic()
        self.messages: list[dict[str, Any]] = []
        self.lock = threading.Lock()

    def _stream_once(self) -> Iterator[dict]:
        """Gửi một request, phát sự kiện ra ngoài; giá trị trả về cuối là Message hoàn chỉnh."""
        with self.client.beta.messages.stream(
            model=settings.model,
            max_tokens=settings.max_tokens,
            system=SYSTEM_PROMPT,
            tools=TOOLS,
            messages=self.messages,
            thinking={"type": "adaptive"},
            output_config={"effort": settings.effort},
            cache_control={"type": "ephemeral"},
            # Nếu bộ lọc an toàn từ chối nhầm, API tự chạy lại trên mô hình dự phòng phù hợp
            fallbacks="default",
            betas=["server-side-fallback-2026-07-01"],
        ) as stream:
            for event in stream:
                if event.type == "text":
                    yield {"type": "text", "text": event.text}
                elif event.type == "content_block_start":
                    block = event.content_block
                    if block.type == "server_tool_use":
                        yield {"type": "status", "text": "Đang tìm kiếm trên Internet..."}
                    elif block.type == "tool_use":
                        yield {"type": "status", "text": f"Đang dùng công cụ: {block.name}"}
            return stream.get_final_message()

    def ask(self, user_text: str) -> Iterator[dict]:
        """Gửi câu hỏi của người dùng, phát ra các sự kiện: text / status / tool / action / done / error."""
        with self.lock:
            yield from self._ask(user_text)

    def _ask(self, user_text: str) -> Iterator[dict]:
        start = len(self.messages)  # để hoàn tác lượt này nếu lỗi
        if not self.messages:
            user_text = _context_block() + user_text
        self.messages.append({"role": "user", "content": user_text})

        json_retries = 0
        rounds = 0
        while True:
            try:
                response = yield from self._stream_once()
                json_retries = 0
            except ValueError:
                # Đầu vào công cụ là JSON hỏng hoàn toàn -> gửi lại lượt này (giới hạn số lần)
                json_retries += 1
                if json_retries > 2:
                    del self.messages[start:]
                    yield {"type": "error", "text": "Ura gặp lỗi khi đọc lệnh công cụ."}
                    return
                continue
            except TypeError as e:
                if "authentication" not in str(e):
                    raise
                del self.messages[start:]
                yield {"type": "error", "text": "Ura chưa có khóa API. Hãy đặt ANTHROPIC_API_KEY trong file .env rồi khởi động lại."}
                return
            except anthropic.AuthenticationError:
                del self.messages[start:]
                yield {"type": "error", "text": "Khóa API không hợp lệ. Hãy kiểm tra ANTHROPIC_API_KEY trong file .env."}
                return
            except anthropic.RateLimitError:
                del self.messages[start:]
                yield {"type": "error", "text": "Ura đang bị giới hạn tần suất. Thử lại sau ít phút nhé."}
                return
            except anthropic.APIStatusError as e:
                del self.messages[start:]
                yield {"type": "error", "text": f"Lỗi API ({e.status_code}): {e.message}"}
                return
            except anthropic.APIConnectionError:
                del self.messages[start:]
                yield {"type": "error", "text": "Mất kết nối tới máy chủ AI. Kiểm tra mạng giúp tôi."}
                return

            if response.stop_reason == "refusal":
                # Phần trả lời dở dang (nếu có) bị bỏ; ghi một lượt trợ lý ngắn để lịch sử hợp lệ
                self.messages.append({"role": "assistant", "content": [
                    {"type": "text", "text": "(Ura không thể hỗ trợ yêu cầu này.)"}]})
                yield {"type": "error", "text": "Xin lỗi, tôi không thể hỗ trợ yêu cầu này."}
                return

            # Nối nguyên vẹn nội dung phản hồi (gồm cả khối thinking) vào lịch sử
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "pause_turn":
                continue  # công cụ máy chủ (tìm kiếm web) cần chạy tiếp

            tool_uses = [b for b in response.content if b.type == "tool_use"]
            if not tool_uses:
                yield {"type": "done", "usage": _usage(response)}
                return

            if response.stop_reason == "max_tokens":
                results = [{"type": "tool_result", "tool_use_id": b.id, "is_error": True,
                            "content": "Đầu vào bị cắt cụt do hết max_tokens; không thực thi."}
                           for b in tool_uses]
            else:
                results = []
                for block in tool_uses:
                    yield {"type": "tool", "name": block.name, "input": block.input}
                    content, is_error, action = tools.run_tool(block.name, block.input)
                    if action:
                        yield {"type": "action", **action}
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": content, "is_error": is_error})
            # Mọi kết quả công cụ gửi lại trong MỘT tin nhắn user
            self.messages.append({"role": "user", "content": results})

            rounds += 1
            if rounds == settings.max_tool_rounds:
                self.messages.append({"role": "user", "content":
                                      "Đã đạt giới hạn số lần dùng công cụ. Hãy tóm tắt kết quả hiện có."})


def _usage(response) -> dict:
    u = response.usage
    return {"input": u.input_tokens, "output": u.output_tokens,
            "cache_read": getattr(u, "cache_read_input_tokens", 0) or 0}


def to_json_line(event: dict) -> str:
    return json.dumps(event, ensure_ascii=False, default=str)
