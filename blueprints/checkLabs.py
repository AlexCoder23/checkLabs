from fastapi import Request, File, UploadFile, Form, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Annotated
from requests import post
import glob, os, tools, sys, hashlib, random, shutil, time
from pathlib import Path
import orjson as json
import auth
import g4f


class Blueprint:
  def __init__(self, rt, tmpl, app):
    self.app = app
    self.rt = rt
    self.tmpl = tmpl
    self.client = g4f.client.AsyncClient()
    
    self.root = Path('conteiner/checklabs')
    
    @rt.on_event("startup")
    async def startup():
      async with app.state.db_checklabs.acquire() as conn:
        await conn.execute('create table IF NOT EXISTS Teachers(id bigint, firstname varchar(64), lastname varchar(64), otch varchar(64), classes int[])')
        await conn.execute('create table IF NOT EXISTS Classes(id int, name varchar(64), description varchar(256), students json, teacher bigint, tasks json)')
        await conn.execute('create table IF NOT EXISTS Students(id bigint, classes int[], applications int[])')
        await conn.execute('create table IF NOT EXISTS Applications(id int, class_id int, student bigint, name varchar(64), surname varchar(64), otch varchar(64))')
    
    @rt.get('/teacher')
    async def tindex(request: Request):
      return tmpl('tindex.html', context={"request": request})
    
    @rt.get('/')
    async def sindex(request: Request):
      return tmpl('sindex.html', context={"request": request})
    
    @rt.get('/get-teacher')
    async def get_teacher(request: Request):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select firstname, lastname, otch, classes from Teachers where id = $1', us_id)
          if res:
            first_name, last_name, otch, classes = res
            return {"ok": True, "teacher": {"id": us_id, "username": username, "firstname": first_name, "lastname": last_name, "otch": otch, "clases": classes}}
          else:
            await conn.execute('insert into Teachers (id, firstname, lastname, otch, classes) values ($1, $2, $3, $4, $5)', us_id, firstname, lastname or '', '', [])
            return {"ok": True, "teacher": {"id": us_id, "username": username, "firstname": firstname, "lastname": lastname, "otch": '', "clases": []}}
      return {"ok": False, "message": "No authentication"}
    
    @rt.get('/get-me')
    async def get_me(request: Request):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select classes, applications from Students where id = $1', us_id)
          if res:
            classes, applications = res
            return {"ok": True, "data": {"id": us_id, "classes": classes, "applications": applications}}
          else:
            await conn.execute('insert into Students (id, classes, applications) values ($1, $2, $3)', us_id, [], [])
            return {"ok": True, "data": {"id": us_id, "classes": [], "applications": []}}
      return {"ok": False, "message": "No authentication"}
    
    class EditTeacher(BaseModel):
      firstname: str
      lastname: str
      otch: str

    @rt.post('/edit-teacher')
    async def edit_teacher(request: Request, data: EditTeacher):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          await conn.execute('update Teachers set firstname = $1, lastname = $2, otch = $3 where id = $4', data.firstname, data.lastname, data.otch, us_id)
          return {"ok": True}
      return {"ok": False, "message": "No authentication or no teacher"}
    
    class CreateClass(BaseModel):
      name: str = Field(..., max_length=64)
      description: str = Field(..., max_length=64)

    @rt.post('/create-class')
    async def create_class(request: Request, data: CreateClass):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          classes = await conn.fetchrow('select classes from Teachers where id = $1', us_id)
          if classes is not None:
            res = await conn.fetch('select id from Classes')
            existing_ids = [row[0] for row in res]
            new_id = 1
            while new_id in existing_ids:
                new_id += 1
            await conn.execute('insert into Classes (id, name, description, students, teacher, tasks) values ($1, $2, $3, $4, $5, $6)', new_id, data.name, data.description, '{}', us_id, '[]')
            classes = list(classes[0]) if classes[0] else []
            classes.append(new_id)
            cl_root = self.root / str(new_id)
            cl_root.mkdir()
            (cl_root / 'tasks').mkdir()
            (cl_root / 'students').mkdir()
            await conn.execute('update Teachers set classes = $1 where id = $2', classes, us_id)
            return {"ok": True, "class_id": new_id}
          return {"ok": False, "message": "No such teacher"}
      return {"ok": False, "message": "No authentication or teacher not found"}
    
    class GetClasses(BaseModel):
      id: list[int]

    @rt.post('/get-classes')
    async def get_classes(request: Request, data: GetClasses):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetch('select id, name, description, students, teacher, tasks from Classes where id = any($1)', data.id)
          classes = []
          for row in res:
            class_id, name, description, students, teacher, tasks = row
            students = json.loads(students)
            tasks = json.loads(tasks)
            if us_id == teacher:
              classes.append({"id": class_id, "name": name, "description": description, "students": students, "tasks": tasks})
            elif us_id in [st["id"] for st in students]:
              teacher_info = await conn.fetchrow('select firstname, lastname from Teachers where id = $1', teacher)
              if teacher_info:
                firstname, lastname = teacher_info
                classes.append({"id": class_id, "name": name, "description": description, "tasks": tasks, "teacher": {"firstname": firstname, "lastname": lastname}})
          return {"ok": True, "classes": classes}
      return {"ok": False, "message": "Authentication is needed"}
    
    class GetClass(BaseModel):
      id: int

    @rt.post('/get-class')
    async def get_class(request: Request, data: GetClass):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          item = await conn.fetchrow('select name, description, students, teacher, tasks from Classes where id = $1', data.id)
          if item:
            name, description, students, teacher, tasks = item
            students = json.loads(students)
            tasks = json.loads(tasks)
            if us_id == teacher:
              return {"ok": True, "class": {"id": data.id, "name": name, "description": description, "students": students, "tasks": tasks}}
            elif us_id in [st["id"] for st in students]:
              teacher_info = await conn.fetchrow('select firstname, lastname from Teachers where id = $1', teacher)
              if teacher_info:
                firstname, lastname = teacher_info
                wtasks = [int(x.name) for x in (self.root / str(data.id) / 'students' / str(us_id)).glob('*')]
                for task in tasks:
                  if task['id'] in wtasks and task['access'] == 1:
                    task['my_files'] = [x.name for x in (self.root / str(data.id) / 'students' / str(us_id) / str(task['id'])).glob('*')]
                    task['started'] = True
                  else:
                    task['my_files'] = []
                    task['started'] = False
                return {"ok": True, "class": {"id": data.id, "name": name, "description": description, "tasks": tasks, "teacher": {"firstname": firstname, "lastname": lastname}}}
            return {"ok": False, "message": "Only student or creator can"}
          return {"ok": False, "message": "Class not found"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class DeleteClass(BaseModel):
      id: int

    @rt.delete('/delete-class')
    async def delete_class(request: Request, data: DeleteClass):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          item = await conn.fetchrow('select teacher, students from Classes where id = $1', data.id)
          if item:
            teacher, students = item
            if us_id == teacher:
              await conn.execute('delete from Classes where id = $1', data.id)
              res = await conn.fetch('select id, classes from Students where id = any($1)', [st["id"] for st in students])
              for st_id, classes in res:
                classes.remove(data.id)
                await conn.execute('update Students set classes = $1 where id = $2', classes, st_id)
              classes = await conn.fetchrow('select classes from Teachers where id = $1', teacher)
              classes = list(classes[0]) if classes[0] else []
              classes.remove(data.id)
              await conn.execute('update Teachers set classes = $1 where id = $2', classes, teacher)
              shutil.rmtree(self.root / str(data.id))
              return {"ok": True}
            return {"ok": False, "message": "Only the teacher can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class Apply(BaseModel):
      class_id: int
      name: str = Field(..., max_length=64)
      surname: str = Field(..., max_length=64)
      otch: str = Field(..., max_length=64)
        
    @rt.post('/class/apply')
    async def apply(request: Request, data: Apply):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select id from Applications where class_id = $1 and student = $2', data.class_id, us_id)
          if res: return {"ok": False, "message": "You already apply in this class"}
          res = await conn.fetchrow('select students, teacher from Classes where id = $1', data.class_id)
          if res:
            students, teacher = res
            students = json.loads(students)
            if us_id in [st["id"] for st in students]:
              return {"ok": False, "message": "You already in this class"}
            elif us_id == teacher:
              return {"ok": False, "message": "You are teacher in this class"}
          else:
            return {"ok": False, "message": "No such class"}
          res = await conn.fetch('select id from Applications')
          existing_ids = [row[0] for row in res]
          new_id = 1
          while new_id in existing_ids: new_id += 1
          res = await conn.fetchrow('select applications from Students where id = $1', us_id)
          if not res: return {"ok": False, "message": "You not registered on /checkLabs"}
          applications = res[0] + [new_id]
          await conn.execute('update Students set applications = $1 where id = $2', applications, us_id)
          await conn.execute('insert into Applications (id, class_id, student, name, surname, otch) values ($1, $2, $3, $4, $5, $6)', new_id, data.class_id, us_id, data.name, data.surname, data.otch)
          return {"ok": True, "application": {"id": new_id, "student": us_id, "class_id": data.class_id, "name": data.name, "surname": data.surname, "otch": data.otch}}
      return {"ok": False, "message": "Authentication is needed"}
    
    class GetApplications(BaseModel):
      id: int

    @rt.post('/get-applications')
    async def get_applications(request: Request, data: GetApplications):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          if isinstance(data.id, int):
            res = await conn.fetchrow('select class_id, student, name, surname, otch from Applications where id = $1', data.id)
            if res:
              class_id, student, name, surname, otch = res
              if student == us_id:
                return {"ok": True, "application": {"class_id": class_id, "name": name, "surname": surname, "otch": otch}}
              return {"ok": False, "message": "You didn't submit this application"}
            return {"ok": False, "message": "No such application"}
          if isinstance(data.id, list):
            res = await conn.fetch('select id, class_id, student, name, surname, otch from Applications where id = any($1)', data.id)
            applications = []
            for row in res:
              appl_id, class_id, student, name, surname, otch = row
              if student == us_id:
                applications.append({"id": appl_id, "class_id": class_id, "name": name, "surname": surname, "otch": otch})
            return {"ok": True, "applications": applications}
          return {"ok": False, "message": "Id must be number or list"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class GetClassApplications(BaseModel):
      class_id: int

    @rt.post('/class/get-applications')
    async def get_class_applications(request: Request, data: GetClassApplications):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher from Classes where id = $1', data.class_id)
          if res:
            teacher = res[0]
            if us_id == teacher:
              res = await conn.fetch('select id, student, name, surname, otch from Applications where class_id = $1', data.class_id)
              applications = []
              for row in res:
                appl_id, student, name, surname, otch = row
                applications.append({"id": appl_id, "student": student, "name": name, "surname": surname, "otch": otch})
              return {"ok": True, "applications": applications}
            return {"ok": False, "message": "Only the teacher can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class CancelApplication(BaseModel):
      id: int

    @rt.delete('/cancel-application')
    async def cancel_application(request: Request, data: CancelApplication):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select applications from Students where id = $1', us_id)
          if res:
            applications = res[0]
            if data.id in applications:
              applications.remove(data.id)
              await conn.execute('update Students set applications = $1 where id = $2', applications, us_id)
              await conn.execute('delete from Applications where id = $1', data.id)
              return {"ok": True}
            return {"ok": False, "message": "Only the person who submitted this application can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class RejectApplication(BaseModel):
      id: int

    @rt.post('/class/reject-application')
    async def reject_application(request: Request, data: RejectApplication):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select student, class_id from Applications where id = $1', data.id)
          if res:
            student, class_id = res
            res = await conn.fetchrow('select teacher from Classes where id = $1', class_id)
            if res and res[0] == us_id:
              res = await conn.fetchrow('select applications from Students where id = $1', student)
              applications = res[0]
              applications.remove(data.id)
              await conn.execute('update Students set applications = $1 where id = $2', applications, student)
              await conn.execute('delete from Applications where id = $1', data.id)
              return {"ok": True}
            return {"ok": False, "message": "Only teacher can"}
          return {"ok": False, "message": "No such application"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class AcceptApplication(BaseModel):
      id: int

    @rt.post('/class/accept-application')
    async def accept_application(request: Request, data: AcceptApplication):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select student, class_id, name, surname, otch from Applications where id = $1', data.id)
          if res:
            student, class_id, name, surname, otch = res
            res = await conn.fetchrow('select teacher, students, tasks from Classes where id = $1', class_id)
            if res:
              teacher, students, tasks = res
              tasks = json.loads(tasks)
              students = json.loads(students)
              if us_id == teacher:
                await conn.execute('delete from Applications where id = $1', data.id)
                res = await conn.fetchrow('select applications, classes from Students where id = $1', student)
                applications, classes = res
                applications.remove(data.id)
                classes.append(class_id)
                await conn.execute('update Students set applications = $1, classes = $2 where id = $3', applications, classes, student)
                students[student] = {"name": name, "surname": surname, "otch": otch, "marks": []}
                await conn.execute('update Classes set students = $1 where id = $2', json.dumps(students).decode(), class_id)
                st_path = self.root / str(class_id) / 'students' / str(student)
                st_path.mkdir()
                return {"ok": True}
              return {"ok": False, "message": "Only teacher can"}
            return {"ok": False, "message": "No such class"}
          return {"ok": False, "message": "No such application"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class RemoveStudent(BaseModel):
      class_id: int
      stud_id: int

    @rt.delete('/class/remove-student')
    async def remove_student(request: Request, data: RemoveStudent):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with self.app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select students, teacher from Classes where id = $1', data.class_id)
          if res:
            students, teacher = res
            students = json.loads(students)
            if us_id == teacher:
              del students[data.stud_id]
              res = await conn.fetchrow('select classes from Students where id = $1', data.stud_id)
              if res:
                classes = res[0]
                classes.remove(data.class_id)
                await conn.execute('update Students set classes = $1 where id = $2', classes, data.stud_id)
                await conn.execute('update Classes set students = $1 where id = $2', json.dumps(students).decode(), data.class_id)
                return {"ok": True}
              return {"ok": False, "message": "No such student in this class"}
            return {"ok": False, "message": "Only the creator can"}
          return {"ok": False, "message": "No such class"}
        return {"ok": False, "message": "Authentication is needed"}

    @rt.get('/class/{class_id}')
    async def open_class(request: Request, class_id: int):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with self.app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher, students from Classes where id = $1', class_id)
          if res:
            teacher, students = res
            students = json.loads(students)
            if us_id == teacher:
              return tmpl('tclass.html', context={"request": request, "class_id": class_id})
            elif us_id in [st["id"] for st in students]:
              return tmpl('sclass.html', context={"request": request, "class_id": class_id})
            return 'You aren`t student or teacher'
          return 'No such class'
      return 'Authentication is needed'
    
    class AddTask(BaseModel):
        class_id: int
        name: str

    @rt.post('/class/add_task')
    async def add_task(request: Request, data: AddTask):
        async with self.app.state.db_core.acquire() as conn:
          user = await auth.check_auth(conn, request.cookies)
          if user:
            async with self.app.state.db_core.acquire() as conn:
              us_id, username, firstname, lastname, photo_url = user
              res = await conn.fetchrow('select teacher, tasks from Classes where id = $1', data.class_id)
              if res:
                teacher, tasks = res
                tasks = json.loads(tasks)
                if us_id == teacher:
                  new_id = 1
                  while any(task["id"] == new_id for task in tasks):
                    new_id += 1
                    task = {"id": new_id, "name": data.name, "files": [], "lastm": time.time(), "access": 0, "acct": 0}
                    tasks.append(task)
                    await conn.execute('update Classes set tasks = $1 where id = $2', json.dumps(tasks), data.class_id)
                    path = self.root / str(data.class_id) / "tasks" / str(new_id)
                    path.mkdir()
                  return {"ok": True, "task": task}
                return {"ok": False, "message": "Only the creator can"}
              return {"ok": False, "message": "No such class"}
        return {"ok": False, "message": "Authentication is needed"}
    
    class DeleteTask(BaseModel):
      class_id: int
      task_id: int

    @rt.delete('/class/delete_task')
    async def delete_task(request: Request, data: DeleteTask):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher, tasks from Classes where id = $1', data.class_id)
          if res:
            teacher, tasks = res
            tasks = json.loads(tasks)
            if us_id == teacher:
              tasks = [task for task in tasks if task["id"] != data.task_id]
              await conn.execute('update Classes set tasks = $1 where id = $2', json.dumps(tasks), data.class_id)
              path = self.root / str(data.class_id) / "tasks" / str(data.task_id)
              shutil.rmtree(path)
              return {"ok": True}
            return {"ok": False, "message": "Only the creator can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class AccessTask(BaseModel):
      class_id: int
      task_id: int
      access: int
      acct: int

    @rt.put('/class/access-task')
    async def access_task(request: Request, data: AccessTask):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher, tasks from Classes where id = $1', data.class_id)
          if res:
            teacher, tasks = res
            tasks = json.loads(tasks)
            if us_id == teacher:
              tasks = [task if task["id"] != data.task_id else {**task, "access": data.access, "acct": data.acct} for task in tasks]
              await conn.execute('update Classes set tasks = $1 where id = $2', json.dumps(tasks), data.class_id)
              return {"ok": True}
            return {"ok": False, "message": "Only the creator can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    @rt.post('/class/upload_task')
    async def upload_task(
        request: Request, 
        class_id: int = Form(...),
        task_id: int = Form(...),
        file: UploadFile = File(...),
        name: str = Form(..., max_length=32),
        dzchunkbyteoffset: int = Form(...),
        dzchunkindex: int = Form(...),
        dztotalchunkcount: int = Form(...),
    ):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher, tasks, students from Classes where id = $1', class_id)
          if res:
            teacher, tasks, students = res
            tasks = json.loads(tasks)
            students = json.loads(students)
            if us_id == teacher:
              path = self.root / str(class_id) / "tasks" / str(task_id) / name
              try:
                with open(path, 'ab') as f:
                  f.seek(dzchunkbyteoffset)
                  f.write(await file.read())
                  f.close()
                  if dztotalchunkcount - dzchunkindex == 1:
                    tasks[task_id]['files'].append(name)
                    await conn.execute('update Classes set tasks = $1 where id = $2', json.dumps(tasks), class_id)
                    return {"ok": True}
              except OSError:
                return {"ok": False, "message": "Couldn't write the file to disk"}
            elif us_id in students.keys():
              if tasks[task_id]['access'] != 1:
                return {"ok": False, "message": "Task not accessible"}
              path = self.root / str(class_id) / "students" / str(us_id) / str(task_id) / name
              try:
                with open(path, 'ab') as f:
                  f.seek(dzchunkbyteoffset)
                  f.write(await file.read())
                  f.close()
                  return {"ok": True}
              except OSError:
                return {"ok": False, "message": "Couldn't write the file to disk"}
            return {"ok": False, "message": "Only the creator can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class StartTask(BaseModel):
      class_id: int
      task_id: int

    @rt.post('/class/start_task')
    async def start_task(request: Request, data: StartTask):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select tasks, students from Classes where id = $1', data.class_id)
          if res:
            tasks, students = res
            tasks = json.loads(tasks)
            students = json.loads(students)
            if us_id in [st["id"] for st in students]:
              if tasks[data.task_id]['access'] != 1:
                return {"ok": False, "message": "Task not accessible"}
              path = self.root / str(data.class_id) / "students" / str(us_id) / str(data.task_id)
              path.mkdir()
              return {"ok": True}
            return {"ok": False, "message": "Only student of this class can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class EditFile(BaseModel):
      class_id: int = Form(...)
      task_id: int = Form(...)
      file: str
      name: str

    @rt.post('/class/edit_file')
    async def editfile(request: Request, data: EditFile):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with self.app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher, tasks, students from Classes where id = $1', data.class_id)
          if res:
            teacher, tasks, students = res
            tasks = json.loads(tasks)
            students = json.loads(students)
            if us_id == teacher:
              path = self.root / str(data.class_id) / "tasks" / str(data.task_id) / data.name
              try:
                with open(path, 'wb') as f:
                  f.write(data.file.encode())
                  f.close()
                return {"ok": True}
              except OSError:
                return {"ok": False, "message": "Couldn't write the file to disk"}
            elif us_id in [st["id"] for st in students]:
              if tasks[data.task_id]['access'] != 1:
                return {"ok": False, "message": "Task not accessible"}
              path = self.root / str(data.class_id) / "students" / str(us_id) / str(data.task_id) / data.name
              try:
                with open(path, 'wb') as f:
                  f.write(data.file.encode())
                  f.close()
                  return {"ok": True}
              except OSError:
                return {"ok": False, "message": "Couldn't write the file to disk"}
              return {"ok": False, "message": "Only the teacher or student of this class can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class GetTaskFiles(BaseModel):
      class_id: int
      stud_id: int
      task_id: list[int]

    @rt.post('/class/get_studs_tasks_files')
    async def get_task_files(request: Request, data: GetTaskFiles):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with self.app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher from Classes where id = $1', data.class_id)
          if res:
            teacher = res[0]
            if us_id == teacher:
              ans = {}
              wtasks = [int(x.name) for x in (self.root / str(data.class_id) / 'students' / str(data.stud_id)).glob('*')]
              for task_id in data.task_id:
                if task_id in wtasks:
                  ans[task_id] = {'started': True, "files": [x.name for x in (self.root / str(data.class_id) / 'students' / str(data.stud_id) / str(task_id)).glob('*')]}
                else:
                  ans[task_id] = {'started': False}
              return {'ok': True, 'tasks': ans}
            return {"ok": False, "message": "Only the creator can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    @rt.get('/class/get_task_file/{class_id}/{task_id}/{file_name}')
    async def get_task_file(request: Request, class_id: int, task_id: int, file_name: str):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with self.app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher, students, tasks from Classes where id = $1', class_id)
          if res:
            teacher, students, tasks = res
            students = json.loads(students)
            tasks = json.loads(tasks)
            if us_id == teacher:
              if file_name.startswith('stud$'):
                file_args = file_name.split("$")
                path = self.root / str(class_id) / "students" / str(file_args[1]) / str(task_id) / str(file_args[2])
                return FileResponse(path)
              else:
                path = self.root / str(class_id) / "tasks" / str(task_id) / file_name
                return FileResponse(path)
            elif us_id in [st["id"] for st in students]:
              if tasks[task_id]['access'] != 1:
                return 'Задание недоступно'
              if file_name.startswith('stud$'):
                file_args = file_name.split("$")
                path = self.root / str(class_id) / "students" / str(us_id) / str(task_id) / str(file_args[1])
                return FileResponse(path)
              else:
                path = self.root / str(class_id) / "tasks" / str(task_id) / file_name
                return FileResponse(path)
            return {"ok": False, "message": "Only the teacher or student of this class can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    @rt.delete('/class/delete_file')
    async def delete_file(request: Request, class_id: int, task_id: int, file_name: str):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
      if user:
        async with self.app.state.db_checklabs.acquire() as conn:
          us_id, username, firstname, lastname, photo_url = user
          res = await conn.fetchrow('select teacher, tasks from Classes where id = $1', class_id)
          if res:
            teacher, tasks = res
            tasks = json.loads(tasks)
            if us_id == teacher:
              path = self.root / str(class_id) / "tasks" / str(task_id) / file_name
              shutil.rmtree(path)
              return {"ok": True}
            return {"ok": False, "message": "Only the creator can"}
          return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    class AddMark(BaseModel):
      class_id: int
      stud_id: int
      task_id: list[int] = 0
      mark: int

    @rt.post('/class/add_mark')
    async def add_mark(request: Request, data: AddMark):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
        if user:
          async with self.app.state.db_checklabs.acquire() as conn:
            us_id, username, firstname, lastname, photo_url = user
            res = await conn.fetchrow('select teacher, students from Classes where id = $1', data.class_id)
            if res:
              teacher, students = res
              students = json.loads(students)
              if us_id == teacher:
                for st in students:
                  if st["id"] == data.stud_id:
                    st["marks"].append(data.mark)
                await conn.execute('update Classes set students = $1 where id = $2', json.dumps(students).decode(), data.class_id)
                return {"ok": True}
              return {"ok": False, "message": "Only the creator can"}
            return {"ok": False, "message": "No such class"}
        return {"ok": False, "message": "Authentication is needed"}
       
    class NeiroTh(BaseModel):
      class_id: int
      task_id: int
      stud_id: int
 
    @rt.post('/class/neiroth')
    async def neiro_th(request: Request, data: NeiroTh):
      async with self.app.state.db_core.acquire() as conn:
        user = await auth.check_auth(conn, request.cookies)
        if user:
          async with self.app.state.db_checklabs.acquire() as conn:
            us_id, username, firstname, lastname, photo_url = user
            res = await conn.fetchrow('select teacher from Classes where id = $1', data.class_id)
            if res:
              teacher = res[0]
              if us_id == teacher:
                tfiles = (self.root / str(data.class_id) / "tasks" / str(data.task_id)).glob('*')
                tfiles = list(map(lambda x: {'t': 0, 'cont': open(x, 'r').read()}, tfiles))
                sfiles = (self.root / str(data.class_id) / "students" / str(data.stud_id) / str(data.task_id)).glob('*')
                sfiles = list(map(lambda x: {'t': 1, 'cont': open(x, 'r').read()}, sfiles))
                response = await self.client.chat.completions.create(
                  model="deepseek-v3",
                  messages=[{"role": "system", "content": 'Ты - учитель, который проверяет работы учеников и ставит им оценки с комментариями, основываясь на файлах заданий и файлах, которые загрузил ученик. Внимательно проверяй орфографию, пунктуацию и другие нормы языков, если это задание на проверку грамотности. Если же это задание по счёту, то проверяй расчёты и ответ. Считай каждую ошибку и снижай балл за каждую ошибку на 1 балл. Пример посылки для проверки: [{"t":0, "cont": "..."}]. Когда t = 0 это файл задания, когда 1 файл ученика. Ты должен вернуть сообщение чёткой и строгой структуры json формата: [9, "молодец, всё правильно", "Ученик написал работу без ошибок"]. Заметь, первое это оценка, второе - комментарий ученику к отценке, третье - комментарий о работе учителю, оценка в 10-тибальной системе.'}, {"role": "user", "content": "%s" % (json.dumps(tfiles + sfiles).decode())}],
                  web_search=False,
                )
                return response.choices[0].message.content
                return {"ok": True}
              return {"ok": False, "message": "Only the creator can"}
            return {"ok": False, "message": "No such class"}
        return {"ok": False, "message": "Authentication is needed"}
        
