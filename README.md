autoscaler/
│
├── cli/                     # SDK CLI (register, up, down, scale, status, logs, metrics)
│   ├── __init__.py
│   └── main.py              # CLI entrypoint using Typer/Click
│
├── controller/              # Daemon (core logic)
│   ├── __init__.py
│   ├── api.py               # FastAPI/Flask Admin API
│   ├── manager.py           # Container lifecycle mgmt (Docker API)
│   ├── scaler.py            # Scaling decisions (RPS, latency, CPU)
│   ├── health.py            # Health checks
│   ├── nginx.py             # Nginx config & reload logic
│   └── state.py             # State registry & DB access
│
├── metrics/
│   ├── __init__.py
│   └── exporter.py          # Prometheus/OpenMetrics exporter, log shipper
│
├── state/
│   ├── __init__.py
│   └── db.py                # SQLite/BoltDB wrapper
│
├── app_spec/                # App registration schema
│   ├── __init__.py
│   └── models.py            # Pydantic dataclasses for AppSpec (YAML/JSON)
│
├── tests/                   # Unit tests
│
├── docker/                  # Helper Dockerfiles & templates
│   └── nginx_template.conf  # Jinja2 template for per-app upstream
│
├── pyproject.toml            # Poetry/pipenv or requirements.txt
└── README.md

