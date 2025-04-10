# gunicorn_config.py
# Save this file in the same directory as your main.py
import multiprocessing

# Server socket settings
bind = "0.0.0.0:5000"

# Worker settings - adjust based on your server's resources
workers = multiprocessing.cpu_count() * 2 + 1

# Changed from "gevent" to "sync" to avoid monkey-patching issues
worker_class = "sync"  

threads = 4

# Worker timeout settings - critical for preventing SIGKILL
timeout = 300  # Increase timeout to 5 minutes (300 seconds)
graceful_timeout = 60

# Worker restart settings
max_requests = 1000  # Restart workers after handling 1000 requests
max_requests_jitter = 200  # Add randomness to avoid all workers restarting at once

# Memory management
worker_tmp_dir = "/dev/shm"  # Use shared memory for temp files
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Logging
loglevel = "info"
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log errors to stdout

# Prevents the worker from sending data if the client has been gone too long
keepalive = 60

# Process naming
proc_name = "voila_price_checker"

# Preload application for better performance
preload_app = True
