from fastapi import Request, Response, File, UploadFile, Form
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel
import hashlib, tools, html, traceback, asyncio, os, hmac, urllib
import orjson as json
from operator import itemgetter
import auth, settings
import asyncpg


class Blueprint:
  def __init__(self, rt, tmpl, app):
    self.rt = rt
    self.tmpl = tmpl
    self.app = app
    
    
    @rt.on_event("startup")
    async def startup():
      async with self.app.state.db_core.acquire() as conn:
        bot_api = 'https://api.telegram.org/bot%s' % await settings.get(conn, 'bot_token')

    @rt.on_event("shutdown")
    async def shutdown():
        pass
        
    
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
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
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
      async with self.app.state.db_core.acquire() as conn:
        data = {key: value for key, value in tgSiteOuth.dict().items() if value is not None}
        if auth.verify_telegram_auth(data.copy(), await settings.get(conn, 'bot_token')):
          item = conn.fetchrow('SELECT * FROM Users WHERE id = %s', data["id"])
          if item:
            await conn.execute('UPDATE Users SET username = $1, first_name =$2, last_name = $3, photo_url = $4 where id = $5', tgSiteOuth.username, tgSiteOuth.first_name, tgSiteOuth.last_name, tgSiteOuth.photo_url, tgSiteOuth.id)
          else:
            await conn.execute('INSERT INTO Users (id, username, first_name, last_name, photo_url) VALUES ($1, $2, $3, $4, $5)', tgSiteOuth.id, tgSiteOuth.username, tgSiteOuth.first_name, tgSiteOuth.last_name, tgSiteOuth.photo_url)
          response.set_cookie("auth", urllib.parse.urlencode({'type': 'telegram', 'auth': json.dumps(data)}), max_age=14*24*60*60, httponly=True)
          return {'ok': True}
        return {'ok': False}

    
    class TgWebAppOuth(BaseModel):
      data: str

    @rt.post('/web_telegram')
    async def wtauth(request: Request, tgWebAppOuth: TgWebAppOuth, response: Response):
      async with self.app.state.db_core.acquire() as conn:
        parsed_data = dict(urllib.parse.parse_qsl(tgWebAppOuth.data))
        if "hash" in parsed_data:
          hash_ = parsed_data.pop('hash')
          data_check_string = "\n".join(
              f"{k}={v}" for k, v in sorted(parsed_data.items(), key=itemgetter(0))
          )
          secret_key = hmac.new(
              key=b"WebAppData", msg=(await settings.get(conn, 'bot_token')).encode(), digestmod=hashlib.sha256
          )
          calculated_hash = hmac.new(
              key=secret_key.digest(), msg=data_check_string.encode(), digestmod=hashlib.sha256
          ).hexdigest()
          if calculated_hash == hash_:
            data = json.loads(parsed_data.pop('user'))
            del data['allows_write_to_pm'], data['language_code']
            data['hash'] = auth.create_telegram_auth(data, (await settings.get(conn, 'bot_token')))
            item = await conn.fetchrow('SELECT * FROM Users WHERE id = $1', data["id"])
            if item:
              await conn.execute('UPDATE Users SET username = $1, first_name = $2, last_name = $3 where id = $4', data.get("username"), data["first_name"], data.get("last_name"), data["id"])
            else:
              await conn.execute('INSERT INTO Users (id, username, first_name, last_name) VALUES ($1, $2, $3, $4)', data["id"], data.get("username"), data["first_name"], data.get("last_name"))
            response.set_cookie('auth', urllib.parse.urlencode({'type': 'telegram', 'auth': json.dumps(data)}), max_age=14*24*60*60, httponly=True)
            return {'ok': True}
        return {'ok': False}


    class PasswdData(BaseModel):
      passwd: str

    @rt.post('/password')
    async def password(request: Request, passwdData: PasswdData):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
        if user and dict(urllib.parse.parse_qsl(request.cookies['auth']))['type'] == 'telegram':
          passw = hashlib.sha256(passwdData.passwd.encode()).hexdigest()
          await conn.execute('UPDATE Users SET password = $1 WHERE id = $2', passw, user[0])
          return {'ok': True}
        return {'ok': False, 'message': 'auth is wrong or without telegram'}


    class LoginData(BaseModel):
      passwd: str
      username: str

    @rt.post('/login')
    async def login(request: Request, loginData: LoginData, response: Response):
      async with self.app.state.db_core.acquire() as conn:
        passw = hashlib.sha256(loginData.passwd.encode()).hexdigest()
        item = await conn.fetchrow('SELECT password FROM Users WHERE $1 in (id::varchar,username)', loginData.username)
        if item and item[0] == passw:
          response.set_cookie('auth', urllib.parse.urlencode({'type': 'password', 'auth': json.dumps({"username": loginData.username, "password": loginData.passwd})}), max_age=14*24*60*60, httponly=True)
          return {'ok': True}
        else:
          return {'ok': False, 'message': 'wrong password or email'}

      
    @rt.get('/logout')
    async def logout(request: Request, response: Response):
      response.set_cookie('auth', '', max_age=0, httponly=True)
      return {'ok': True}
