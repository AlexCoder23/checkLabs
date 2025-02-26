import asyncio
import orjson as json


async def add(db, key, val):
    await db.execute('insert into Settings (key, value) values ($1, $2)', key, val)
	
async def get(db, key):
	res = await db.fetch('select value from Settings where key = $1', key)
	if len(res) == 1: return json.loads(res[0][0])
	elif len(res) > 1: return list(map(lambda el: json.loads(el[0]), res))
	else: return None
	
async def set(db, key, val):
	await db.execute('update Settings set value = $1 where key = $2', val, key)
