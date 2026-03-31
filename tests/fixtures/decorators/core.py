def log_calls(func):
    def wrapper(*args, **kwargs):
        print(f"Calling {func.__name__}")
        return func(*args, **kwargs)
    return wrapper


def retry(times=3):
    def decorator(func):
        def wrapper(*args, **kwargs):
            for i in range(times):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    if i == times - 1:
                        raise
        return wrapper
    return decorator


@log_calls
def process_data(data):
    cleaned = clean(data)
    return transform(cleaned)


@retry(times=5)
def fetch_remote(url):
    return download(url)


def clean(data):
    return [x for x in data if x is not None]


def transform(data):
    return [x * 2 for x in data]


def download(url):
    return f"content of {url}"
