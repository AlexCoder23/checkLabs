from threading import Lock

with Lock():
  import hmac, hashlib
  import json, os, urllib
  import psycopg2
  import settings

  __conn = psycopg2.connect(
    dbname='core',
    user='alexcoder23', 
    password='qywter132',
    host='0.0.0.0'
  )
  
  def get_conn(token):
    if token == 'opqwerty': return __conn
    else: return 'poshol nafig'

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

  async def check_auth(cookies):
    cur = __conn.cursor()
    if cookies.get('auth'):
      data = dict(urllib.parse.parse_qsl(cookies['auth']))
      if data.get('type') == 'telegram' and data.get('auth'):
        auth_data = json.loads(data['auth'])
        if verify_telegram_auth(auth_data.copy(), settings.get('bot_token', 'opqwerty')):
          cur.execute('SELECT id, username, first_name, last_name, photo_url FROM Users WHERE id = %s', (auth_data['id'],))
          res = cur.fetchall()
          if len(res) != 0:
            cur.close()
            return res[0]
      elif data.get('type') == 'password' and data.get('auth'):
        auth_data = json.loads(data['auth'])
        if auth_data.get('password') and auth_data.get('username'):
          username = str(auth_data['username'])
          passw = hashlib.sha256(str(auth_data['password']).encode()).hexdigest()
          cur.execute('SELECT password FROM Users WHERE %s in (id::varchar,username)', (username,))
          res = cur.fetchall()
          if len(res) != 0 and res[0][0] == passw:
            cur.execute('SELECT id, username, first_name, last_name, photo_url FROM Users WHERE %s in (id::varchar,username)', (auth_data['username'],))
            res = cur.fetchall()
            cur.close()
            return res[0]
    return None
