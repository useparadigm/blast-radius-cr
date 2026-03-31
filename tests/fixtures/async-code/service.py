import asyncio


async def fetch_user(user_id):
    await asyncio.sleep(0.1)
    return {"id": user_id, "name": f"User {user_id}"}


async def fetch_orders(user_id):
    await asyncio.sleep(0.1)
    return [{"id": 1, "total": 100}]


async def get_user_summary(user_id):
    user = await fetch_user(user_id)
    orders = await fetch_orders(user_id)
    total = calculate_total(orders)
    return {"user": user, "order_total": total}


def calculate_total(orders):
    return sum(o["total"] for o in orders)


async def batch_process(user_ids):
    tasks = [get_user_summary(uid) for uid in user_ids]
    return await asyncio.gather(*tasks)
