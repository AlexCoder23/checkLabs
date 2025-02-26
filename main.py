import dotenv
dotenv.load_dotenv()

import os, datetime, time, sys, json, traceback, html, importlib, glob, logging
from collections import defaultdict
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect, APIRouter
from fastapi.responses import Response, HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from fastapi.templating import Jinja2Templates
from fastapi.exceptions import HTTPException
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.middleware.gzip import GZipMiddleware
import auth
import asyncpg


app = FastAPI()


class DisableCacheMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-cache"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

app.add_middleware(DisableCacheMiddleware)
app.add_middleware(GZipMiddleware)


HOST = 'alexcoder23.ru'
LOGS = []
routes_path = 'blueprints/'
routes = {}
DBS = {
# ['id', 'user', 'password', 'database', 'host']
  'core': ['alexcoder23', 'qywter132', 'core', '0.0.0.0'],
  'checklabs': ['alexcoder23', 'qywter132', 'checklabs', '0.0.0.0'],
}

logging.basicConfig(level=logging.NOTSET)
logger = logging.getLogger(__name__)


@app.on_event("startup")
async def startup():
  for k, v in DBS.items():
    try:
      app.state._state['db_'+k] = await asyncpg.create_pool(user=v[0], password=v[1], database=v[2], host=v[3])
    except: pass

@app.on_event("shutdown")
async def shutdown():
  for k, v in DBS.items():
    await app.state._state['db_'+k].close()
        

def log(*data):
  print(*data)
  LOGS.append(' '.join(map(str, data)))


log('loading routes')
app.state.log = log
for path in glob.glob(f'{routes_path}*.py'):
  try:
    path = path.replace('\\','/')[:-3]
    mod_path = path.replace("/", ".")
    name = mod_path.split('.')[-1]
    mod = importlib.import_module(mod_path)
    router = APIRouter()
    templates = Jinja2Templates(directory=f"templates/{name}")
    routes[name] = [mod, router, mod.Blueprint(router, templates.TemplateResponse, app)]
    app.include_router(router, prefix=('' if name == 'index' else f'/{name}'))
    log('route', name, 'loaded')
  except:
    log('loading error', name, traceback.format_exc())


# app.mount("/static", StaticFiles(directory="static"), name="static")
@app.get("/static/{file_path:path}")
async def get_static(file_path: str, request: Request):
  full_path = os.path.join("static", file_path)
  if not os.path.exists(full_path):
    return Response(status_code=404)
  file_stat = os.stat(full_path)
  last_modified = datetime.datetime.fromtimestamp(file_stat.st_mtime)
  if_modified_since = request.headers.get("If-Modified-Since")
  if if_modified_since:
    if_modified_since = datetime.datetime.strptime(if_modified_since, "%a, %d %b %Y %H:%M:%S GMT")
    if last_modified <= if_modified_since:
      return Response(status_code=304)
  response = FileResponse(full_path)
  response.headers["Last-Modified"] = last_modified.strftime("%a, %d %b %Y %H:%M:%S GMT")
  return response

templates = Jinja2Templates(directory="templates")


ws_clients = {}
ws_users = {}
ws_col = defaultdict(int)
binds = defaultdict(list)

log_subs = []

@app.websocket("/core")
async def websocket(ws: WebSocket):
  ip =  ws.headers.get("cf-connecting-ip") or ws.client.host
  if ws_col[ip] > 40:
    await ws.close(code=1008, reason="Too many connections from this IP")
    return
  await ws.accept()
  ws_col[ip] += 1
  token = ws.headers.get("sec-websocket-key")
  async with app.state.db_core.acquire() as conn:
    user = await auth.check_auth(conn, ws.cookies)
  ws_clients[token] = ws
  ws_users[token] = user
  try:
    while True:
      data = await ws.receive_text()
      try:
        data = json.loads(data)
        for bind in binds[data[0]]:
          await bind(ws, token, data[1:])
      except:
        print(traceback.format_exc())
  except WebSocketDisconnect:
    pass
  finally:
    del ws_clients[token]
    ws_col[ip] -= 1
    
    del log_subs[token]


async def sub_logs(ws, token, data):
  if not ws_users[token] or ws_users[token][0] != 5795045879: return
  if token not in log_subs: log_subs.append(token)

async def get_logs(ws, token, data):
  if not ws_users[token] or ws_users[token][0] != 5795045879: return
  await ws.send_text(json.dumps(['logs', LOGS]))

async def runc(ws, token, data):
  if not ws_users[token] or ws_users[token][0] != 5795045879: return
  try:
    exec('async def __ex(): ' + data[0])
    await locals()['__ex']()
  except: await log(traceback.format_exc())

binds['sub_logs'].append(sub_logs)
binds['get_logs'].append(get_logs)
binds['runc'].append(runc)

async def log(*data):
  print(*data, 'gdjfh')
  logt = ' '.join(map(str, data))
  LOGS.append(logt)
  for token in log_subs:
    try: await ws_clients[token].send_text(json.dumps(['log', logt]))
    except Exception as ex: print(ex)

@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
  if exc.status_code == 404:
    return templates.TemplateResponse(name="404Page.html", context={"request": request}, status_code=404)
  return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

@app.exception_handler(Exception)
async def generic_exception_handler(request: Request, exc: Exception):
  fexc = traceback.format_exc()
  await log("in " + request.scope['root_path'] + request.scope['route'].path + " " + fexc)
  return PlainTextResponse(fexc)
