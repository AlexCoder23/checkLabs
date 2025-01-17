from fastapi import Request, File, UploadFile, Form, WebSocket, WebSocketDisconnect, Query
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, FileResponse
from pydantic import BaseModel, Field
from typing import Annotated
from requests import post
import glob, os, tools, sys, pickle, psycopg2, hashlib, random, shutil, json, time
from pathlib import Path
import auth


# from apscheduler.schedulers.background import BackgroundScheduler
# scheduler = BackgroundScheduler()
# scheduler.start()

# # Пример функции для удаления объекта из базы данных
# async def delete_object_from_db(object_id):
#     # Здесь должен быть код для удаления объекта из базы данных
#     print(f"Удален объект с ID {object_id} в {datetime.now()}")

# @app.route('/set_delete_time', methods=['POST'])
# async def set_delete_time():
#     data = await request.get_json()
#     object_id = data.get('object_id')
#     delete_time = data.get('delete_time')

#     # Преобразуем время удаления в объект datetime
#     delete_time = datetime.fromisoformat(delete_time)

#     # Планируем задачу на удаление объекта
#     scheduler.add_job(delete_object_from_db, 'date', run_date=delete_time, args=[object_id])

#     return jsonify({"status": "success", "message": f"Объект с ID {object_id} будет удален в {delete_time}"})


class Blueprint:
  def __init__(self, rt, tmpl):
    self.rt = rt
    self.tmpl = tmpl
    
    self.root = Path('conteiner/checklabs')
    
    self.conn = psycopg2.connect(
      dbname='checklabs',
      user='alexcoder23', 
      password='qywter132',
      host='0.0.0.0'
    )
  
    cur = self.conn.cursor()
    cur.execute('create table IF NOT EXISTS Teachers(id bigint, firstname varchar(64), lastname varchar(64), otch varchar(64), classes int[])')
    cur.execute('create table IF NOT EXISTS Classes(id int, name varchar(64), description varchar(256), students json, teacher bigint, tasks json)')
    cur.execute('create table IF NOT EXISTS Students(id bigint, classes int[], applications int[])')
    cur.execute('create table IF NOT EXISTS Applications(id int, class_id int, student bigint, name varchar(64), surname varchar(64), otch varchar(64))')
    self.conn.commit()
    cur.close()
    
    
    @rt.get('/teacher')
    async def tindex(request: Request):
      return tmpl('tindex.html', context={"request": request})
    
    
    @rt.get('/')
    async def sindex(request: Request):
      return tmpl('sindex.html', context={"request": request})
    
    
    @rt.get('/get-teacher')
    async def get_teacher(request: Request):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select firstname, lastname, otch, classes from Teachers where id = %s', (us_id, ))
        res = cur.fetchall()
        if res:
          firstname, lastname, otch, clases = res[0]
          return {"ok": True, "teacher": {"id": us_id, "firstname": firstname, "lastname": lastname, "otch": otch, "clases": clases}}
        else:
          cur.execute('insert into Teachers (id, firstname, lastname, otch, classes) values (%s, %s, %s, %s, %s)', (us_id, firstname, lastname or '', '', []))
          self.conn.commit()
          return {"ok": True, "teacher": {"id": us_id, "username": username, "firstname": firstname, "lastname": lastname, "otch": '', "clases": []}}
      return {"ok": False, "message": "No authecation"}
    
    
    @rt.get('/get-me')
    async def get_me(request: Request):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select classes, applications from Students where id = %s', (us_id, ))
        res = cur.fetchall()
        if res:
          classes, applications = res[0]
          return {"ok": True, "data": {"id": us_id, "classes": classes, "applications": applications}}
        else:
          cur.execute('insert into Students (id, classes, applications) values (%s, %s, %s)', (us_id, [], []))
          self.conn.commit()
          return {"ok": True, "data": {"id": us_id, "classes": [], "applications": []}}
      return {"ok": False, "message": "No authecation"}
    
    
    class EditTeacher(BaseModel):
      firstname: str
      lastname: str
      otch: str

    @rt.post('/edit-teacher')
    async def edit_teacher(request: Request, data: EditTeacher):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur = self.conn.cursor()
        try:
          cur.execute('update Teachers set firstname = %s, lastname = %s, otch = %s where id = %s', (data.firstname, data.lastname, data.otch, us_id, ))
          self.conn.commit()
          return {"ok": True}
        except:
          self.conn.rollback()
      return {"ok": False, "message": "No authecation or no teacher"}
    
    
    class CreateClass(BaseModel):
      name: str = Field(..., max_length=64)
      description: str = Field(..., max_length=64)

    @rt.post('/create-class')
    async def create_class(request: Request, data: CreateClass):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select classes from Teachers where id = %s', (us_id, ))
        res = cur.fetchall()
        if res:
          classes = res[0][0]
          cur.execute('select id from Classes')
          res = list(map(lambda x: x[0], cur.fetchall()))
          new_id = 1
          while new_id in res: new_id+=1
          cur.execute('insert into Classes (id, name, description, students, teacher, tasks) values (%s, %s, %s, %s, %s, %s)', (new_id, data.name, data.description, '[]', us_id, '[]', ))
          classes.append(new_id)
          cl_root = self.root / str(new_id)
          cl_root.mkdir()
          (cl_root / 'tasks').mkdir()
          (cl_root / 'students').mkdir()
          cur.execute('update Teachers set classes = %s where id = %s', (classes, us_id, ))
          self.conn.commit()
          return {"ok": True, "class_id": new_id}
      return {"ok": False, "message": "No authentication or teacher not found"}
    
    
    class GetClasses(BaseModel):
      id: list[int]

    @rt.post('/get-classes')
    async def get_classes(request: Request, data: GetClasses):
      user = await auth.check_auth(request.cookies)
      cur = self.conn.cursor()
      cur.execute('select id, name, description, students, teacher, tasks from Classes where id = any(%s)', (data.id, ))
      classes = []
      res = cur.fetchall()
      if user:
        us_id, username, firstname, lastname, photo_url = user
        for class_id, name, description, students, teacher, tasks in res:
          if us_id == teacher:
            classes.append({"id": class_id, "name": name, "description": description, "students": students, "tasks": tasks})
          elif us_id in list(map(lambda st: st["id"], students)):
            cur.execute('select firstname, lastname from Teachers where id = %s', (teacher, ))
            firstname, lastname = cur.fetchall()[0]
            classes.append({"id": class_id, "name": name, "description": description, "tasks": tasks, "teacher": {"firstname": firstname, "lastname": lastname}})
        return {"ok": True, "classes": classes}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    class GetClass(BaseModel):
      id: int

    @rt.post('/get-class')
    async def get_class(request: Request, data: GetClass):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select name, description, students, teacher, tasks from Classes where id = %s', (data.id, ))
        res = cur.fetchall()
        if res:
          name, description, students, teacher, tasks = res[0]
          if us_id == teacher:
            return {"ok": True, "class": {"id": data.id, "name": name, "description": description, "students": students, "tasks": tasks}}
          elif us_id in list(map(lambda st: st["id"], students)):
            cur.execute('select firstname, lastname from Teachers where id = %s', (teacher, ))
            firstname, lastname = cur.fetchall()[0]
            wtasks = list(map(lambda x: int(x.name), (self.root / str(data.id) / 'students' / str(us_id)).glob('*')))
            for task in tasks:
              if task['id'] in wtasks and task['access'] == 1:
                task['my_files'] = list(map(lambda x: x.name, (self.root / str(data.id) / 'students' / str(us_id) / str(task['id'])).glob('*')))
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
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, students from Classes where id = %s', (data.id, ))
        res = cur.fetchall()
        if res:
          teacher, students = res[0]
          if us_id == teacher:
            cur.execute('delete from Classes where id = %s', (data.id, ))
            cur.execute('select id, classes from Students where id = any(%s)', (list(map(lambda st: st["id"], students)), ))
            res = cur.fetchall()
            for st_id, classes in res:
              classes.remove(data.id)
              cur.execute('update Students set classes = %s where id = %s', (classes, st_id, ))
            cur.execute('select classes from Teachers where id = %s', (teacher, ))
            classes = cur.fetchall()[0][0]
            classes.remove(data.id)
            cur.execute('update Teachers set classes = %s where id = %s', (classes, teacher, ))
            self.conn.commit()
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
      user = await auth.check_auth(request.cookies)
      cur = self.conn.cursor()
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur.execute('select id from Applications where class_id = %s and student = %s', (data.class_id, us_id, ))
        res = cur.fetchall()
        if res: return {"ok": False, "message": "You already apply in this class"}
        cur.execute('select students, teacher from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          students, teacher = res[0]
          if us_id in list(map(lambda st: st["id"], students)): return {"ok": False, "message": "You already in this class"}
          elif us_id == teacher: return {"ok": False, "message": "You are teacher in this class"}
        else: return {"ok": False, "message": "No such class"}
        cur.execute('select id from Applications')
        ids = list(map(lambda x: x[0], cur.fetchall()))
        new_id = 1
        while new_id in ids: new_id+=1
        cur.execute('select applications from Students where id = %s', (us_id, ))
        res = cur.fetchall()
        if not res: return {"ok": False, "message": "You not rigistered on <a href='https://alexcoder23.ru/checkLabs'>/checkLabs</a>"}
        applications = res[0][0]+[new_id]
        cur.execute('update Students set applications = %s where id = %s', (applications, us_id, ))
        cur.execute('insert into Applications (id, class_id, student, name, surname, otch) values (%s, %s, %s, %s, %s, %s)', (new_id, data.class_id, us_id, data.name, data.surname, data.otch, ))
        self.conn.commit()
        return {"ok": True, "application": {"id": new_id, "student": us_id, "class_id": data.class_id, "name": data.name, "surname": data.surname, "otch": data.otch}}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    class GetApplications(BaseModel):
      id: int

    @rt.post('/get-applications')
    async def get_applications(request: Request, data: GetApplications):
      user = await auth.check_auth(request.cookies)
      cur = self.conn.cursor()
      if user:
        us_id, username, firstname, lastname, photo_url = user
        if isinstance(data.id, int):
          cur.execute('select class_id, student, name, surname, otch from Applications where id = %s', (data.id, ))
          res = cur.fetchall()
          if res:
            class_id, student, name, surname, otch = res[0]
            if student == us_id:
              return {"ok": True, "application": {"class_id": class_id, "name": name, "surname": surname, "otch": otch}}
            return {"ok": False, "message": "You didn't submit this application"}
          return {"ok": False, "message": "No such application"}
        if isinstance(data.id, list):
          cur.execute('select id, class_id, student, name, surname, otch from Applications where id = any(%s)', (data.id, ))
          res = cur.fetchall()
          applications = []
          for appl_id, class_id, student, name, surname, otch in res:
            if student == us_id:
              applications.append({"id": appl_id, "class_id": class_id, "name": name, "surname": surname, "otch": otch})
          return {"ok": True, "applications": applications}
        return {"ok": False, "message": "Id must be number or list"}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    class GetClassApplications(BaseModel):
      class_id: int

    @rt.post('/class/get-applications')
    async def get_class_applications(request: Request, data: GetClassApplications):
      user = await auth.check_auth(request.cookies)
      cur = self.conn.cursor()
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur.execute('select teacher from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          teacher = res[0][0]
          if us_id == teacher:
            cur.execute('select id, student, name, surname, otch from Applications where class_id = %s', (data.class_id, ))
            res = cur.fetchall()
            applications = []
            for appl_id, student, name, surname, otch in res:
              applications.append({"id": appl_id, "student": student, "name": name, "surname": surname, "otch": otch})
            return {"ok": True, "applications": applications}
          return {"ok": False, "message": "Only the teacher can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    class CancelApplication(BaseModel):
      id: int

    @rt.delete('/cancel-application')
    async def cancel_application(request: Request, data: CancelApplication):
      user = await auth.check_auth(request.cookies)
      cur = self.conn.cursor()
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur.execute('select applications from Students where id = %s', (us_id, ))
        res = cur.fetchall()
        if res:
          applications = res[0][0]
          if data.id in applications:
            applications.remove(data.id)
            cur.execute('update Students set applications = %s where id = %s', (applications, us_id, ))
            cur.execute('delete from Applications where id = %s', (data.id, ))
            self.conn.commit()
            return {"ok": True}
          return {"ok": False, "message": "Only the person who submitted this application can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    class RejectApplication(BaseModel):
      id: int

    @rt.post('/class/reject-application')
    async def reject_application(request: Request, data: RejectApplication):
      user = await auth.check_auth(request.cookies)
      cur = self.conn.cursor()
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur.execute('select student, class_id from Applications where id = %s', (data.id, ))
        res = cur.fetchall()
        if res:
          student, class_id = res[0]
          cur.execute('select teacher from Classes where id = %s', (class_id, ))
          res = cur.fetchall()
          if res and res[0][0] == us_id:
            cur.execute('select applications from Students where id = %s', (student, ))
            applications = cur.fetchall()[0][0]
            applications.remove(data.id)
            cur.execute('update Students set applications = %s where id = %s', (applications, student, ))
            cur.execute('delete from Applications where id = %s', (data.id, ))
            self.conn.commit()
            return {"ok": True}
          return {"ok": False, "message": "Only teacher can"}
        return {"ok": False, "message": "No such application"}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    class AcceptApplication(BaseModel):
      id: int

    @rt.post('/class/accept-application')
    async def accept_application(request: Request, data: AcceptApplication):
      user = await auth.check_auth(request.cookies)
      cur = self.conn.cursor()
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur.execute('select student, class_id, name, surname, otch from Applications where id = %s', (data.id, ))
        res = cur.fetchall()
        if res:
          student, class_id, name, surname, otch = res[0]
          cur.execute('select teacher, students, tasks from Classes where id = %s', (class_id, ))
          res = cur.fetchall()
          if res:
            teacher, students, tasks = res[0]
            if us_id == teacher:
              cur.execute('delete from Applications where id = %s', (data.id, ))
              cur.execute('select applications, classes from Students where id = %s', (student, ))
              applications, classes = cur.fetchall()[0]
              applications.remove(data.id)
              classes.append(class_id)
              cur.execute('update Students set applications = %s, classes = %s where id = %s', (applications, classes, student, ))
              students.append({"id": student, "name": name, "surname": surname, "otch": otch, "marks": []})
              cur.execute('update Classes set students = %s where id = %s', (json.dumps(students, ensure_ascii=False), class_id, ))
              self.conn.commit()
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
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, firstname, lastname, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select students, teacher from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          students, teacher = res[0]
          if us_id == teacher:
            ok = False
            for i in range(len(students)):
              if data.stud_id == students[i]["id"]:
                del students[i]
                cur.execute('select classes from Students where id = %s', (data.stud_id, ))
                classes = cur.fetchall()[0][0]
                classes.remove(data.class_id)
                cur.execute('update Students set classes = %s where id = %s', (classes, data.stud_id, ))
                ok = True
            if ok:
              cur.execute('update Classes set students = %s where id = %s', (json.dumps(students, ensure_ascii=False), data.class_id, ))
              self.conn.commit()
              return {"ok": True}
            return {"ok": False, "message": "No such student in this class"}
          return {"ok": False, "message": "Only the creator can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    @rt.get('/class/{class_id}')
    async def open_class(request: Request, class_id: int):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, students from Classes where id = %s', (class_id, ))
        res = cur.fetchall()
        if res:
          teacher, students = res[0]
          if us_id == teacher:
            return tmpl('tclass.html', context={"request": request, "class_id": class_id})
          elif us_id in list(map(lambda st: st["id"], students)):
            return tmpl('sclass.html', context={"request": request, "class_id": class_id})
          return 'You aren`t student or teacher'
        return 'No such class'
      return 'Authentication is needed'
    
    
    class AddTask(BaseModel):
      class_id: int
      name: str

    @rt.post('/class/add_task')
    async def add_task(request: Request, data: AddTask):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, tasks from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          teacher, tasks = res[0]
          if us_id == teacher:
            ids = list(map(lambda ts: ts["id"], tasks))
            new_id = 0
            while new_id in ids: new_id += 1
            task = {"id": new_id, "name": data.name, "files": [], "lastm": time.time(), "access": 0, "acct": 0}
            tasks.append(task)
            cur.execute('update Classes set tasks = %s where id = %s', (json.dumps(tasks, ensure_ascii=False), data.class_id, ))
            self.conn.commit()
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
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, tasks from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          teacher, tasks = res[0]
          if us_id == teacher:
            i = 0
            while i < len(tasks):
              if tasks[i]['id'] == data.task_id: del tasks[i]
              else: i += 1
            cur.execute('update Classes set tasks = %s where id = %s', (json.dumps(tasks, ensure_ascii=False), data.class_id, ))
            self.conn.commit()
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
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, tasks from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          teacher, tasks = res[0]
          if us_id == teacher:
            for i in range(len(tasks)):
              if tasks[i]['id'] == data.task_id:
                tasks[i]['access'] = data.access
                tasks[i]['acct'] = data.acct
            cur.execute('update Classes set tasks = %s where id = %s', (json.dumps(tasks, ensure_ascii=False), data.class_id, ))
            self.conn.commit()
            return {"ok": True}
          return {"ok": False, "message": "Only the creator can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
    
    @rt.post('/class/upload_task')
    async def upload_task(
      request: Request, 
      class_id: str = Form(...),
      task_id: int = Form(...),
      file: UploadFile = File(...),
      name: str = Form(..., max_length=32),
      dzchunkbyteoffset: int = Form(...),
      dzchunkindex: int = Form(...),
      dztotalchunkcount: int = Form(...),
    ):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, tasks, students from Classes where id = %s', (class_id, ))
        res = cur.fetchall()
        if res:
          teacher, tasks, students = res[0]
          if us_id == teacher:
            path = self.root / str(class_id) / "tasks" / str(task_id) / name
            try:
              with open(path, 'ab') as f:
                f.seek(dzchunkbyteoffset)
                f.write(await file.read())
                f.close()
                if dztotalchunkcount - dzchunkindex == 1:
                  tasks[task_id]['files'].append(name)
                  cur.execute('update Classes set tasks = %s where id = %s', (json.dumps(tasks, ensure_ascii=False), class_id, ))
                  self.conn.commit()
              return {"ok": True}
            except OSError: return {"ok": False, "message": "Couldn't write the file to disk"}
          elif us_id in list(map(lambda st: st["id"], students)):
            if tasks[task_id]['access'] != 1: return {"ok": False, "message": "Task not accessible"}
            path = self.root / str(class_id) / "students" / str(us_id) / str(task_id) / name
            try:
              with open(path, 'ab') as f:
                f.seek(dzchunkbyteoffset)
                f.write(await file.read())
                f.close()
              return {"ok": True}
            except OSError: return {"ok": False, "message": "Couldn't write the file to disk"}
          return {"ok": False, "message": "Only the creator can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
  
  
    class StartTask(BaseModel):
      class_id: str
      task_id: int

    @rt.post('/class/start_task')
    async def start_task(request: Request, data: StartTask):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select tasks, students from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          tasks, students = res[0]
          if us_id in list(map(lambda st: st["id"], students)):
            if tasks[data.task_id]['access'] != 1: return {"ok": False, "message": "Task not accessible"}
            path = self.root / str(data.class_id) / "students" / str(us_id) / str(data.task_id)
            path.mkdir()
            return {"ok": True}
          return {"ok": False, "message": "Only the teacher or student of this class can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
      
  
    class EditFile(BaseModel):
      class_id: str = Form(...)
      task_id: int = Form(...)
      file: str
      name: str

    @rt.post('/class/edit_file')
    async def editfile(request: Request, data: EditFile):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, tasks, students from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          teacher, tasks, students = res[0]
          if us_id == teacher:
            path = self.root / str(data.class_id) / "tasks" / str(data.task_id) / data.name
            try:
              file = open(path, 'wb')
              file.write(data.file.encode())
              file.close()
              return {"ok": True}
            except OSError: return {"ok": False, "message": "Couldn't write the file to disk"}
          elif us_id in list(map(lambda st: st["id"], students)):
            if tasks[data.task_id]['access'] != 1: return {"ok": False, "message": "Task not accessible"}
            path = self.root / str(data.class_id) / "students" / str(us_id) / str(data.task_id) / data.name
            try:
              file = open(path, 'wb')
              file.write(data.file.encode())
              file.close()
              return {"ok": True}
            except OSError: return {"ok": False, "message": "Couldn't write the file to disk"}
          return {"ok": False, "message": "Only the teacher or student of this class can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
      
      
    class GetTaskFiles(BaseModel):
      class_id: int
      stud_id: int
      task_id: list[int]

    @rt.post('/class/get_studs_tasks_files')
    async def get_task_file(request: Request, data: GetTaskFiles):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher from Classes where id = %s', (data.class_id, ))
        res = cur.fetchall()
        if res:
          teacher = res[0][0]
          if us_id == teacher:
            ans = {}
            wtasks = list(map(lambda x: int(x.name), (self.root / str(data.class_id) / 'students' / str(data.stud_id)).glob('*')))
            for task_id in data.task_id:
              if task_id in wtasks:
                ans[task_id] = {'started': True, "files": list(map(lambda x: x.name, (self.root / str(data.class_id) / 'students' / str(data.stud_id) / str(task_id)).glob('*')))}
              else:
                ans[task_id] = {'started': False}
            return {'ok': True, 'tasks': ans}
          return {"ok": False, "message": "Only the creator can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    
  
    class GetTask(BaseModel):
      class_id: int = Query(..., description="Class ID")
      task_id: int = Query(..., description="Task ID")
      file_name: str = Query(..., description="File name")

    @rt.get('/class/get_task_file/{class_id}/{task_id}/{file_name}')
    async def get_task_file(request: Request, class_id: int, task_id: int, file_name: str):
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, students, tasks from Classes where id = %s', (class_id, ))
        res = cur.fetchall()
        if res:
          teacher, students, tasks = res[0]
          if us_id == teacher:
            if file_name.startswith('stud$'):
              file_args = file_name.split("$")
              path = self.root / str(class_id) / "students" / str(file_args[1]) / str(task_id) / str(file_args[2])
              return FileResponse(path)
            else:
              path = self.root / str(class_id) / "tasks" / str(task_id) / file_name
              return FileResponse(path)
          elif us_id in list(map(lambda st: st["id"], students)):
            if tasks[task_id]['access'] != 1: return 'Задание недоступно'
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
      user = await auth.check_auth(request.cookies)
      if user:
        us_id, username, first_name, last_name, photo_url = user
        cur = self.conn.cursor()
        cur.execute('select teacher, tasks from Classes where id = %s', (class_id, ))
        res = cur.fetchall()
        if res:
          teacher, tasks = res[0]
          if us_id == teacher:
            path = self.root / str(class_id) / "tasks" / task_name / file_name
            shutil.rmtree(path)
            return {"ok": True}
          return {"ok": False, "message": "Only the creator can"}
        return {"ok": False, "message": "No such class"}
      return {"ok": False, "message": "Authentication is needed"}
    