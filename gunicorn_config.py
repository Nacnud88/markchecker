# gunicorn_config.py
# Optimized for 512MB RAM environment
import multiprocessing

# Server socket settings
bind = "0.0.0.0:5000"

# Worker settings - reduce for memory constraints
workers = 2  # Reduced from dynamic calculation to fixed small number
worker_class = "sync"  # Using sync worker to avoid memory overhead from async workers
threads = 2  # Reduced threads per worker

# Worker timeout settings
timeout = 300  # 5 minutes for long-running requests
graceful_timeout = 60

# Restart workers to prevent memory leaks
max_requests = 500  # Restart workers after handling fewer requests
max_requests_jitter = 100  # Add randomness to avoid all workers restarting at once

# Memory management
worker_tmp_dir = "/dev/shm"  # Use shared memory for temp files
limit_request_line = 4096
limit_request_fields = 100
limit_request_field_size = 8190

# Logging - reduce verbosity for production
loglevel = "warning"  # Less verbose than info
accesslog = "-"  # Log to stdout
errorlog = "-"   # Log errors to stdout
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# Prevents the worker from sending data if the client has been gone too long
keepalive = 60

# Process naming
proc_name = "voila_price_checker"

# Memory optimization settings
# Don't preload app to save memory at startup
preload_app = False

# More aggressive worker recycling for memory management
max_requests_jitter = 50

def post_fork(server, worker):
    # Force garbage collection after fork to clean up memory
    import gc
    gc.collect()

def worker_int(worker):
    # Run garbage collection on worker shutdown
    import gc
    gc.collect()
