import os
import multiprocessing

# Basic configuration
bind = f"0.0.0.0:{os.environ.get('PORT', 5000)}"
workers = min(4, (multiprocessing.cpu_count() * 2) + 1)  # ワーカー数を制限
worker_class = "sync"
worker_connections = 1000
max_requests = 1000
max_requests_jitter = 50

# Performance tuning
keepalive = 2
timeout = 30
graceful_timeout = 30
preload_app = True

# Memory management
worker_tmp_dir = "/dev/shm"  # メモリファイルシステムを使用
worker_rlimit_nofile = 1024

# Logging
loglevel = "info"
accesslog = "-"
errorlog = "-"
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)s'

# Security
limit_request_line = 4094
limit_request_fields = 100
limit_request_field_size = 8190

# Application
module = "app:app" 