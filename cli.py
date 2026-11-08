"""Trò chuyện với Ura ngay trong terminal.   Chạy:  python cli.py"""
from __future__ import annotations

import webbrowser

from ura.brain import Conversation
from ura.config import settings

CYAN, DIM, RED, RESET = "\033[96m", "\033[2m", "\033[91m", "\033[0m"


def main() -> None:
    convo = Conversation()
    print(f"{CYAN}URA ▸ Xin chào {settings.user_name}. Ura đã sẵn sàng. (gõ 'thoát' để kết thúc){RESET}")
    while True:
        try:
            text = input("\nBạn ▸ ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not text:
            continue
        if text.lower() in ("thoát", "thoat", "exit", "quit"):
            break
        print(f"{CYAN}URA ▸ ", end="", flush=True)
        for ev in convo.ask(text):
            t = ev["type"]
            if t == "text":
                print(ev["text"], end="", flush=True)
            elif t == "status":
                print(f"{DIM}[{ev['text']}]{RESET}{CYAN} ", end="", flush=True)
            elif t == "action" and ev.get("action") == "open_url":
                webbrowser.open(ev["url"])
            elif t == "error":
                print(f"{RED}{ev['text']}{RESET}", end="")
        print(RESET)
    print(f"{CYAN}URA ▸ Tạm biệt {settings.user_name}.{RESET}")


if __name__ == "__main__":
    main()
