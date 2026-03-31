from service import get_user_summary, batch_process, fetch_user


async def handle_user_request(request):
    user_id = request["user_id"]
    summary = await get_user_summary(user_id)
    return {"status": 200, "body": summary}


async def handle_batch_request(request):
    user_ids = request["user_ids"]
    results = await batch_process(user_ids)
    return {"status": 200, "body": results}


async def handle_user_profile(request):
    user = await fetch_user(request["user_id"])
    return {"status": 200, "body": user}
