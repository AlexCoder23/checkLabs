import hmac, hashlib
import os, urllib
import orjson as json
import settings

def create_telegram_auth(data: dict, bot_token: str) -> str:
  data_check_string = '\n'.join([f'{k}={v}' for k, v in sorted(data.items())])
  secret_key = hashlib.sha256(bot_token.encode()).digest()
  return hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

def verify_telegram_auth(data: dict, bot_token: str) -> bool:
  if 'hash' not in data.keys(): return False
  received_hash = data.pop('hash')
  computed_hash = create_telegram_auth(data, bot_token)
  return hmac.compare_digest(computed_hash, received_hash)

def get_hash(data):
  return hashlib.sha256(str(data).encode()).hexdigest()

async def check_auth(db, cookies):
  if cookies.get('auth'):
    data = dict(urllib.parse.parse_qsl(cookies['auth']))
    async with db.transaction():
      if data.get('type') == 'telegram' and data.get('auth'):
        auth_data = json.loads(data['auth'])
        if verify_telegram_auth(auth_data.copy(), await settings.get(db, 'bot_token')):
          user = await db.fetchrow('SELECT id, username, first_name, last_name, photo_url FROM Users WHERE id = $1', auth_data['id'])
          if user: return user
      elif data.get('type') == 'password' and data.get('auth'):
        auth_data = json.loads(data['auth'])
        if auth_data.get('password') and auth_data.get('username'):
          username = str(auth_data['username'])
          passw = hashlib.sha256(str(auth_data['password']).encode()).hexdigest()
          user = await db.fetchrow('SELECT password FROM Users WHERE $1 in (id::varchar,username)', username)
          if user and user[0] == passw:
            user = await db.fetchrow('SELECT id, username, first_name, last_name, photo_url FROM Users WHERE $1 in (id::varchar,username)', auth_data['username'])
            return user
  return None
