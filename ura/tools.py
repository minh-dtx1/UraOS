"""Bộ công cụ (tools) mà Ura có thể sử dụng.

Mỗi công cụ gồm: định nghĩa JSON Schema gửi cho Claude + hàm Python thực thi.
Muốn thêm năng lực mới cho Ura? Viết một hàm, rồi đăng ký bằng decorator @tool.
"""
from __future__ import annotations

import ast
import json
import math
import operator
import os
import platform
import shutil
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from .config import settings

VN_TZ = ZoneInfo("Asia/Ho_Chi_Minh")


# ---------------------------------------------------------------------------
# Lưu trữ JSON đơn giản (bộ nhớ dài hạn + danh sách việc cần làm)
# ---------------------------------------------------------------------------
class JsonStore:
    def __init__(self, name: str):
        self.path = settings.data_dir / f"{name}.json"
        self._lock = threading.Lock()

    def load(self) -> list[dict]:
        if not self.path.is_file():
            return []
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def save(self, items: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)


memory_store = JsonStore("memory")
task_store = JsonStore("tasks")


def _now() -> datetime:
    return datetime.now(VN_TZ)


# ---------------------------------------------------------------------------
# Đăng ký công cụ
# ---------------------------------------------------------------------------
@dataclass
class Tool:
    name: str
    description: str
    schema: dict
    fn: Callable[..., Any]
    # Công cụ "client" trả về một hành động để giao diện web thực hiện (mở web, ...)
    client_action: bool = False

    def definition(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.schema,
            # Đầu vào công cụ được stream ngay khi sinh ra; ta tự kiểm tra hợp lệ bên dưới.
            "eager_input_streaming": True,
        }


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, properties: dict | None = None,
         required: list[str] | None = None, client_action: bool = False):
    schema = {
        "type": "object",
        "properties": properties or {},
        "required": required or [],
        "additionalProperties": False,
    }

    def wrap(fn):
        REGISTRY[name] = Tool(name, description, schema, fn, client_action)
        return fn

    return wrap


_JSON_TYPES = {"string": str, "integer": int, "number": (int, float), "boolean": bool}


def validate(t: Tool, args: Any) -> str | None:
    """Kiểm tra đầu vào theo schema. Trả về thông báo lỗi, hoặc None nếu hợp lệ."""
    if not isinstance(args, dict):
        return "đầu vào phải là một object JSON"
    props = t.schema["properties"]
    for key in t.schema["required"]:
        if key not in args:
            return f"thiếu trường bắt buộc '{key}'"
    for key, value in args.items():
        if key not in props:
            return f"trường không hợp lệ '{key}'"
        expected = _JSON_TYPES.get(props[key].get("type"))
        if expected and (not isinstance(value, expected) or
                         (expected is not bool and isinstance(value, bool))):
            return f"trường '{key}' phải có kiểu {props[key]['type']}"
        if "enum" in props[key] and value not in props[key]["enum"]:
            return f"trường '{key}' phải là một trong {props[key]['enum']}"
    return None


def run_tool(name: str, args: Any) -> tuple[str, bool, dict | None]:
    """Thực thi công cụ. Trả về (nội_dung_kết_quả, có_lỗi, hành_động_cho_client)."""
    t = REGISTRY.get(name)
    if t is None:
        return f"Không có công cụ tên '{name}'.", True, None
    err = validate(t, args)
    if err:
        return json.dumps({"INVALID_INPUT": err}, ensure_ascii=False), True, None
    try:
        result = t.fn(**args)
    except Exception as e:  # lỗi công cụ được báo lại cho Claude, không làm sập Ura
        return f"Lỗi khi chạy {name}: {e}", True, None
    action = None
    if t.client_action and isinstance(result, dict):
        action = result
    text = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
    return text, False, action


def definitions() -> list[dict]:
    # Thứ tự cố định (sắp theo tên) để prompt cache không bị vô hiệu hóa
    return [REGISTRY[k].definition() for k in sorted(REGISTRY)]


# ---------------------------------------------------------------------------
# Các công cụ
# ---------------------------------------------------------------------------
@tool("get_datetime",
      "Lấy ngày giờ hiện tại. Mặc định múi giờ Việt Nam; có thể truyền tên múi giờ IANA khác "
      "(vd 'Asia/Tokyo', 'Europe/London').",
      {"timezone": {"type": "string", "description": "Tên múi giờ IANA"}})
def get_datetime(timezone: str = "Asia/Ho_Chi_Minh") -> dict:
    now = datetime.now(ZoneInfo(timezone))
    thu = ["Thứ Hai", "Thứ Ba", "Thứ Tư", "Thứ Năm", "Thứ Sáu", "Thứ Bảy", "Chủ Nhật"]
    return {"iso": now.isoformat(timespec="seconds"), "weekday": thu[now.weekday()],
            "timezone": timezone}


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
        ast.Div: operator.truediv, ast.FloorDiv: operator.floordiv, ast.Mod: operator.mod,
        ast.Pow: operator.pow, ast.USub: operator.neg, ast.UAdd: operator.pos}
_FUNCS = {k: getattr(math, k) for k in
          ("sqrt", "sin", "cos", "tan", "asin", "acos", "atan", "log", "log10", "exp",
           "floor", "ceil", "radians", "degrees", "factorial", "hypot")}
_FUNCS.update(abs=abs, round=round, min=min, max=max)
_CONSTS = {"pi": math.pi, "e": math.e}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in _OPS:
        left, right = _eval(node.left), _eval(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise ValueError("số mũ quá lớn")
        return _OPS[type(node.op)](left, right)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _OPS:
        return _OPS[type(node.op)](_eval(node.operand))
    if isinstance(node, ast.Name) and node.id in _CONSTS:
        return _CONSTS[node.id]
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            and node.func.id in _FUNCS and not node.keywords):
        return _FUNCS[node.func.id](*[_eval(a) for a in node.args])
    raise ValueError("biểu thức không được hỗ trợ")


@tool("calculate",
      "Tính toán biểu thức toán học chính xác (cộng trừ nhân chia, **, sqrt, sin, cos, log, pi...). "
      "Dùng công cụ này thay vì tính nhẩm khi cần con số chính xác.",
      {"expression": {"type": "string", "description": "Biểu thức kiểu Python, vd '2*pi*3.5**2'"}},
      ["expression"])
def calculate(expression: str) -> dict:
    value = _eval(ast.parse(expression, mode="eval"))
    return {"expression": expression, "result": value}


@tool("remember",
      "Ghi nhớ lâu dài một thông tin về người dùng (sở thích, thói quen, dự án, người thân...). "
      "Dùng khi người dùng nói 'nhớ giúp tôi...' hoặc chia sẻ điều đáng nhớ.",
      {"fact": {"type": "string", "description": "Thông tin cần nhớ, viết ngắn gọn"}},
      ["fact"])
def remember(fact: str) -> dict:
    items = memory_store.load()
    item = {"id": uuid.uuid4().hex[:8], "fact": fact, "created": _now().isoformat(timespec="minutes")}
    items.append(item)
    memory_store.save(items)
    return {"saved": item}


@tool("recall",
      "Tìm trong bộ nhớ dài hạn. Để trống query để liệt kê mọi điều đã nhớ.",
      {"query": {"type": "string", "description": "Từ khóa cần tìm"}})
def recall(query: str = "") -> dict:
    items = memory_store.load()
    if query:
        q = query.lower()
        items = [i for i in items if q in i["fact"].lower()] or items
    return {"memories": items[-50:]}


@tool("forget", "Xóa một mục khỏi bộ nhớ dài hạn theo id.",
      {"id": {"type": "string"}}, ["id"])
def forget(id: str) -> dict:
    items = memory_store.load()
    kept = [i for i in items if i["id"] != id]
    memory_store.save(kept)
    return {"deleted": len(items) - len(kept)}


@tool("add_task",
      "Thêm việc cần làm / lời nhắc. Có thể kèm thời hạn (ISO 8601, giờ Việt Nam) "
      "hoặc số phút tính từ bây giờ.",
      {"title": {"type": "string"},
       "due": {"type": "string", "description": "Thời hạn ISO 8601, vd 2026-11-09T08:00"},
       "in_minutes": {"type": "integer", "description": "Nhắc sau bao nhiêu phút"}},
      ["title"])
def add_task(title: str, due: str = "", in_minutes: int = 0) -> dict:
    due_dt = None
    if in_minutes:
        due_dt = _now() + timedelta(minutes=in_minutes)
    elif due:
        due_dt = datetime.fromisoformat(due)
        if due_dt.tzinfo is None:
            due_dt = due_dt.replace(tzinfo=VN_TZ)
    items = task_store.load()
    item = {"id": uuid.uuid4().hex[:8], "title": title, "done": False,
            "due": due_dt.isoformat(timespec="minutes") if due_dt else None,
            "notified": False}
    items.append(item)
    task_store.save(items)
    return {"added": item}


@tool("list_tasks", "Liệt kê việc cần làm.",
      {"include_done": {"type": "boolean", "description": "Hiện cả việc đã xong"}})
def list_tasks(include_done: bool = False) -> dict:
    items = task_store.load()
    if not include_done:
        items = [i for i in items if not i["done"]]
    return {"now": _now().isoformat(timespec="minutes"), "tasks": items}


@tool("complete_task", "Đánh dấu một việc là đã xong theo id.",
      {"id": {"type": "string"}}, ["id"])
def complete_task(id: str) -> dict:
    items = task_store.load()
    hit = 0
    for i in items:
        if i["id"] == id:
            i["done"], hit = True, 1
    task_store.save(items)
    return {"completed": hit}


def due_reminders() -> list[dict]:
    """Các lời nhắc đã đến hạn mà chưa thông báo (giao diện web gọi định kỳ)."""
    items = task_store.load()
    now = _now()
    out = []
    for i in items:
        if i["done"] or i.get("notified") or not i.get("due"):
            continue
        if datetime.fromisoformat(i["due"]) <= now:
            i["notified"] = True
            out.append(i)
    if out:
        task_store.save(items)
    return out


@tool("system_status",
      "Báo cáo trạng thái máy chủ đang chạy Ura: hệ điều hành, CPU, tải, RAM, ổ đĩa.")
def system_status() -> dict:
    info: dict[str, Any] = {"os": f"{platform.system()} {platform.release()}",
                            "python": platform.python_version(), "cpu_count": os.cpu_count()}
    if hasattr(os, "getloadavg"):
        info["load_avg_1_5_15"] = [round(x, 2) for x in os.getloadavg()]
    du = shutil.disk_usage(settings.data_dir)
    info["disk_free_gb"] = round(du.free / 1e9, 1)
    info["disk_total_gb"] = round(du.total / 1e9, 1)
    try:
        with open("/proc/meminfo") as f:
            mem = {l.split(":")[0]: int(l.split()[1]) for l in f}
        info["ram_total_gb"] = round(mem["MemTotal"] / 1e6, 1)
        info["ram_available_gb"] = round(mem["MemAvailable"] / 1e6, 1)
    except (OSError, KeyError, ValueError):
        pass
    return info


@tool("open_url",
      "Mở một trang web trên màn hình của người dùng (tab mới trong trình duyệt). "
      "Dùng khi người dùng bảo 'mở YouTube', 'mở Google Maps chỗ ...'.",
      {"url": {"type": "string", "description": "URL đầy đủ, bắt đầu bằng https://"}},
      ["url"], client_action=True)
def open_url(url: str) -> dict:
    if not url.startswith(("https://", "http://")):
        raise ValueError("URL phải bắt đầu bằng http:// hoặc https://")
    return {"action": "open_url", "url": url}


@tool("set_theme", "Đổi màu giao diện HUD của Ura.",
      {"color": {"type": "string", "enum": ["cyan", "red", "gold", "green", "purple"]}},
      ["color"], client_action=True)
def set_theme(color: str) -> dict:
    return {"action": "set_theme", "color": color}
