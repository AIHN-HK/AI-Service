# Testing Guide — Chatbot Service

## 1. Cấu trúc Tests

```
tests/
├── unit/                    ← Unit tests (không cần service ngoài)
│   ├── test_config.py       # Config loading, YAML, secrets, CORS
│   ├── test_schemas.py      # Pydantic models validation
│   ├── test_middleware.py   # RateLimiter, CircuitBreaker, RequestQueue
│   ├── test_utils.py        # Token counting
│   └── test_api.py          # Health/root endpoints (mock dependencies)
├── performance/             ← Performance tests
└── conftest.py
```

---

## 2. Chạy Tests trên Local

### Cài dependencies

```bash
# Vào venv
# Windows:
.\venv\Scripts\activate
# Linux/Mac:
source venv/bin/activate

# Cài thêm python-dotenv (nếu chưa có)
pip install -r requirements.txt
```

### Chạy tất cả unit tests

```bash
# Giống lệnh CI chạy — chỉ unit tests, bỏ qua integration + performance
python -m pytest tests/ -v --tb=short --ignore=tests/integration --ignore=tests/performance -x
```

### Chạy từng file test

```bash
# Chỉ test config
python -m pytest tests/unit/test_config.py -v

# Chỉ test schemas
python -m pytest tests/unit/test_schemas.py -v

# Chỉ test middleware
python -m pytest tests/unit/test_middleware.py -v

# Chỉ test utilities
python -m pytest tests/unit/test_utils.py -v

# Chỉ test API endpoints
python -m pytest tests/unit/test_api.py -v
```

### Chạy một test cụ thể

```bash
# Chạy 1 class
python -m pytest tests/unit/test_config.py::TestSettings -v

# Chạy 1 test function
python -m pytest tests/unit/test_config.py::TestSettings::test_settings_loads_successfully -v
```

### Xem test coverage

```bash
pip install pytest-cov
python -m pytest tests/unit/ -v --cov=app --cov-report=term-missing
```

---

## 3. Test trên máy host (trong Docker)

```bash
# Chạy tests trong Docker
docker compose exec app python -m pytest tests/unit/ -v --tb=short

# Hoặc build image mới rồi test
docker compose build app
docker compose run --rm app python -m pytest tests/unit/ -v
```

