from threading import Lock

with Lock():
	import psycopg2, os
	
	__conn = psycopg2.connect(
	  dbname='core',
	  user='alexcoder23',
	  password='qywter132',
	  host='localhost'
	)
	
	__token = 'opqwerty'
	
	def get_conn(token):
	  if token == __token: return __conn
	  else: return 'poshol nafig'
	
	def add(key, val, token):
	  if token == __token:
	    cursor = __conn.cursor()
	    cursor.execute('insert into Settings (key, value) values (%s, %s)', (key, val, ))
	  else: return 'poshol nafig'
	
	def get(key, token):
	  if token == __token:
	    cursor = __conn.cursor()
	    cursor.execute('select value from Settings where key = %s', (key, ))
	    res = cursor.fetchall()
	    if len(res) == 1: return res[0][0]
	    elif len(res) > 1: return list(map(lambda el: el[0], res))
	    else: return None
	  return 'poshol nafig'
	
	def set(key, val, token):
	  if token == __token:
	    cursor = __conn.cursor()
	    cursor.execute('update Settings set value = %s where key = %s', (val, key, ))
	  return 'poshol nafig'
	