# Tests

```
tests/
├── unit/                     # Unit test, không cần server/DB  →  pytest tests/unit
├── test_search.py            # Unit test cho search tool (mock)
├── test_ws_cancellation.py   # Test WebSocket in-process (TestClient, mock graph)
├── test_state{1..5}_cli.py   # Giả lập hội thoại từng State bằng CLI (gọi LLM thật)
├── test_state1_validation.py # Validation hobby của State 1
├── test_e2e_full_linh.py     # E2E đi qua đủ 5 State (persona Linh)
├── test_ws_chat.py           # Client WebSocket gọi server đang chạy (--host, --tc)
└── performance/              # Locust scripts dùng cho số liệu báo cáo + results/
```

Chạy:

```bash
python -m pytest tests/unit -q                       # nhanh, không cần gì
python tests/test_state1_cli.py                      # cần OPENAI_API_KEY trong .env
python tests/test_ws_chat.py --host localhost        # cần docker compose up
```

Các script cũ (trỏ tới server production đã bỏ, trùng lặp, hoặc file rỗng) nằm ở `archive/tests/`.
