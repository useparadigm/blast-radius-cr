from core import process_data, fetch_remote


def handle_upload(file_data):
    result = process_data(file_data)
    return {"status": "ok", "result": result}


def handle_sync(source_url):
    content = fetch_remote(source_url)
    result = process_data(content)
    return {"status": "synced", "data": result}
