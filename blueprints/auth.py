from fastapi import Request, Response, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel
import random, pickle, hashlib, tools, html, traceback, asyncio, os, hmac, urllib, json
from operator import itemgetter
import auth, settings

bot_api = 'https://api.telegram.org/bot%s' % settings.get('bot_token', 'opqwerty')

class Blueprint:
  def __init__(self, rt, tmpl):
    self.rt = rt
    self.tmpl = tmpl
    
    conn = auth.get_conn('opqwerty')
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS Users (
    id bigint not null,
    username varchar(64),
    first_name varchar(128) not null,
    last_name varchar(128),
    photo_url TEXT,
    password varchar(128)
    )
    """)
    cursor.close()
    conn.commit()

    
    @rt.get('/regblock.html')
    async def regblock(request: Request):
      return tmpl(name='regblock.html', context={"request": request})
    
    
    @rt.get('/profile')
    async def profilech(request: Request, tg: str = 'false'):
      if tg == 'true':
        return tmpl(name='tgprofile.html', context={"request": request})
      else:
        return tmpl(name='profile.html', context={"request": request})

      
    @rt.get('/logined')
    async def logined(request: Request):
      user = await auth.check_auth(request.cookies)
      return {"ok": True, "user": user}

    
    class TgSiteOuth(BaseModel):
      id: int
      first_name: str
      hash: str
      username: str = None
      last_name: str = None
      photo_url: str = None
      auth_date: int = None

    @rt.post('/telegram')
    async def tauth(request: Request, tgSiteOuth: TgSiteOuth, response: Response):
      conn = auth.get_conn('opqwerty')
      data = {key: value for key, value in tgSiteOuth.dict().items() if value is not None}
      if auth.verify_telegram_auth(data.copy(), settings.get('bot_token', 'opqwerty')):
        cur = conn.cursor()
        cur.execute('SELECT * FROM Users WHERE id = %s', (data["id"],))
        res = cur.fetchall()
        if len(res) == 0:
          cur.execute('INSERT INTO Users (id, username, first_name, last_name, photo_url) VALUES (%s, %s, %s, %s, %s)', (tgSiteOuth.id, tgSiteOuth.username, tgSiteOuth.first_name, tgSiteOuth.last_name, tgSiteOuth.photo_url, ))
        else:
          cur.execute('UPDATE Users SET username = %s, first_name = %s, last_name = %s, photo_url = %s where id = %s', (tgSiteOuth.username, tgSiteOuth.first_name, tgSiteOuth.last_name, tgSiteOuth.photo_url, tgSiteOuth.id, ))
          cur.close()
        conn.commit()
        response.set_cookie(key="auth", value=urllib.parse.urlencode({'type': 'telegram', 'auth': json.dumps(data, separators=(',', ':'))}), max_age=14*24*60*60, httponly=True)
        return {'ok': True}
      return {'ok': False}

    
    class TgWebAppOuth(BaseModel):
      data: str

    @rt.post('/web_telegram')
    async def wtauth(request: Request, tgWebAppOuth: TgWebAppOuth, response: Response):
      conn = auth.get_conn('opqwerty')
      parsed_data = dict(urllib.parse.parse_qsl(tgWebAppOuth.data))
      if "hash" in parsed_data:
        hash_ = parsed_data.pop('hash')
        data_check_string = "\n".join(
            f"{k}={v}" for k, v in sorted(parsed_data.items(), key=itemgetter(0))
        )
        secret_key = hmac.new(
            key=b"WebAppData", msg=settings.get('bot_token', 'opqwerty').encode(), digestmod=hashlib.sha256
        )
        calculated_hash = hmac.new(
            key=secret_key.digest(), msg=data_check_string.encode(), digestmod=hashlib.sha256
        ).hexdigest()
        if calculated_hash == hash_:
          data = json.loads(parsed_data.pop('user'))
          del data['allows_write_to_pm'], data['language_code']
          data['hash'] = auth.create_telegram_auth(data, settings.get('bot_token', 'opqwerty'))
          cur = conn.cursor()
          cur.execute('SELECT * FROM Users WHERE id = %s', (data["id"], ))
          res = cur.fetchall()
          if len(res) == 0:
            cur.execute('INSERT INTO Users (id, username, first_name, last_name) VALUES (%s, %s, %s, %s)', (data["id"], data.get("username"), data["first_name"], data.get("last_name"), ))
          else:
            cur.execute('UPDATE Users SET username = %s, first_name = %s, last_name = %s where id = %s', (data.get("username"), data["first_name"], data.get("last_name"), data["id"], ))
          cur.close()
          conn.commit()
          response.set_cookie('auth', urllib.parse.urlencode({'type': 'telegram', 'auth': json.dumps(data, separators=(',', ':'))}), max_age=14*24*60*60, httponly=True)
          return {'ok': True}
      return {'ok': False}


    class PasswdData(BaseModel):
      passwd: str

    @rt.post('/password')
    async def password(request: Request, passwdData: PasswdData):
      user = await auth.check_auth(request.cookies)
      conn = auth.get_conn('opqwerty')
      if user and dict(urllib.parse.parse_qsl(request.cookies['auth']))['type'] == 'telegram':
        cur = conn.cursor()
        passw = hashlib.sha256(passwdData.passwd.encode()).hexdigest()
        cur.execute('UPDATE Users SET password = %s WHERE id = %s', (passw, user[0],))
        cur.close()
        conn.commit()
        return {'ok': True}
      return {'ok': False, 'message': 'auth is wrong or without telegram'}


    class LoginData(BaseModel):
      passwd: str
      username: str

    @rt.post('/login')
    async def login(request: Request, loginData: LoginData, response: Response):
      conn = auth.get_conn('opqwerty')
      passw = hashlib.sha256(loginData.passwd.encode()).hexdigest()
      cur = conn.cursor()
      cur.execute('SELECT password FROM Users WHERE %s in (id::varchar,username)', (loginData.username,))
      res = cur.fetchall()
      cur.close()
      if len(res) != 0 and res[0][0] == passw:
        response.set_cookie('auth', urllib.parse.urlencode({'type': 'password', 'auth': json.dumps({"username": loginData.username, "password": loginData.passwd}, separators=(',', ':'))}), max_age=14*24*60*60, httponly=True)
        return {'ok': True}
      else:
        return {'ok': False, 'message': 'wrong password or email'}

      
    @rt.get('/logout')
    async def logout(request: Request, response: Response):
      response.set_cookie('auth', '', max_age=0, httponly=True)
      return {'ok': True}
