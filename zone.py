import sqlite3, re, hashlib, json, os, xlrd
from flask import Flask, request, session, g, redirect, url_for, \
	abort, render_template, flash
from contextlib import closing

import helpers

pwd = ""
# configuration info
DATABASE = pwd+'zone.db'
UPLOAD_FOLDER = pwd+'uploads/'
DEBUG = True
SECRET_KEY = 'I DONT KNOW WHAT IM DOING'
USERNAME = 'admin'
PASSWORD = 'default'

# out application
app = Flask(__name__)
app.config.from_object(__name__)

# database stuff
def connect_db():
	return sqlite3.connect(app.config['DATABASE'])

def init_db():
	with closing(connect_db()) as db:
		with app.open_resource('schema.sql', mode='r') as f:
			db.cursor().executescript(f.read())
		db.commit()

@app.before_request
def before_request():
	g.db = connect_db()

def teardown_request(exception):
	db = getattr(g, 'db', None)
	if db is not None:
		db.close()

# get user id
# get users ID
def getUserId():
	cur = g.db.execute('SELECT id FROM users WHERE email=?', [session.get('logged_in')])
	fetchd = cur.fetchone()
	return fetchd[0]

# our main views
def allowed_file(filename):
	ALLOWED_EXTENSIONS = set(['xls', 'xlsm', 'xlsx'])
	return '.' in filename and filename.rsplit('.', 1)[1] in ALLOWED_EXTENSIONS

def parseExits(fileName=None, gid=None, team=None):
	# open file
	workbook = xlrd.open_workbook(fileName)

	sheet = workbook.sheet_by_index(0)

	errors = False
	message = ""
	toInsert = []

	# go through each row
	for row in range(1,sheet.nrows):
		rowData = sheet.row_values(row)
		period = rowData[0]
		carry = rowData[2].upper()
		player = rowData[3]
		# parse all four colums

		# Check if player is a digit
		try:
			player = int(float(player))
		except: 
			errors = True
			message += "Row %s, invalid player, %s is not a digit.\n" % (row, str(player))

		# check carry
		if carry not in ['C', 'P', 'CH', 'FC', 'FP', 'CT', 'PT', 'X', 'I', 'T']:
			errors = True
			message += "Row %s: %s is not a valid carry.\n" % (row, carry)

		# check period
		if period == 'OT': period = 4
		if period not in [1,2,3,4]: 
			errors = True
			message += "Row %s, %s is not a valid period.\n" % (row, period)
		else:
			try: 
				period = int(period)
			except: 
				errors = True
				message += "Row %s, %s is not a valid period.\n" % (row, period)

		# time
		try:
			time = xlrd.xldate_as_tuple(rowData[1],0)
		except:
			if re.compile('^(\d)+:\d\d$').match(rowData[1]):
				time = rowData[1]
				if len(time) == 4: time = "0"+time
			else:
				errors = True
				message += "Time Remaining: %s in row %s is not a valid time." % (rowData[1], row)
				continue

		print time
		try:
			minute = int(time[3])
			second = int(time[4])
		except:
			errors = True
			message += "Time Remaining: %s:%s in row %s is not a valid time." % (time[3], str(time[4]).zfill(2), row)
		else:
			terrors = False
			if minute not in range(0,21):
				terrors = True
			if second not in range(0,61):
				terrors = True
			if terrors == True:
				errors = True
				message += "Time Remaining: %s:%s in row %s is not a valid time." % (time[3], str(time[4]).zfill(2), row)

		time = minute * 60 + second
		toInsert.append([period, time, carry, player])


	# are there error message?  Yes?  output them
	if errors == True:
		return (errors, message)

	# no?  ok, insert
	cur = g.db.execute('SELECT id FROM users WHERE email=?', [session.get('logged_in')])
	fetchd = cur.fetchone()
	if fetchd is None:
		return (True, 'Something has gone wrong - you don\'t exist')
	userid = fetchd[0]
	try:
		# delete all entries for this game for this user
		g.db.execute('DELETE FROM exits WHERE gameid = ? and tracker = ? and team = ?', [gid, userid, team])
		g.db.commit()
		# loop through entries again
		for ze in toInsert:
			# save each item
			g.db.execute('INSERT INTO exits (gameid, tracker, team, period, time, exittype, player,pressure,strength) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
							[gid, userid, team, ze[0], ze[1], ze[2], ze[3], -1, -1])
			g.db.commit()
	except Exception,e:
		return (True, 'Something went wrong with saving on the server side. %s  Please contact Josh.' % (str(e)))
	return (False, "All is good!")

@app.route('/', methods=['GET', 'POST'])
def index():
	if request.method == 'POST':
		file = request.files['file']
		data = request.form['data']
		year = request.form['year']
		gameid = request.form['gameid']
		team = request.form['team']
		if data not in ['1', '2']:
			message = "Not a valid entry type"
		elif year not in [str(x)+str(x+1) for x in range(2013, 2014)]:
			message = "Not a valid year"
		elif len(gameid) not in [5] or not gameid.isdigit():
			message = "game id is not valid."
		elif int(gameid) < 20000 or int(gameid) >= 40000:
			message = "Game id is not in the valid range"
		elif team not in ['1', '2']:
			message = "Not a valid team"
		elif file and allowed_file(file.filename):
			gid = str(year) + gameid
			from werkzeug import secure_filename
			filename = secure_filename(file.filename)
			fullpath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
			file.save(fullpath)
			# parse it here
			# delete old from exits for this game + user
			message = parseExits(fullpath, gid, team)[1]
			os.remove(fullpath)
		else:
			message = "Not a valid excel file"
		flash(message)
		return redirect(url_for('index'))
	return render_template('index.html')

from views.db import db
db.register(app)

from views.admin import admin
admin.register(app)

@app.route('/about')
def about():
	return render_template('about.html')

# zone entries
@app.route('/addzen')
@helpers.login_required
def addzen():
	return render_template('add-zen.html')

@app.route('/myze')
@helpers.login_required
def myze():
	# get users ID
	userid = getUserId()
	# get all users games
	cur = g.db.execute('SELECT gameid FROM exits WHERE tracker = ? GROUP BY gameid ORDER BY gameid DESC', [userid])
	bigdata = [list(row) for row in cur.fetchall()]
	#return render_template('allgames.html', alldata=bigdata)
	return render_template('my-ze.html', alldata=bigdata)

# main page for adding zone entries
@app.route('/addze')
@app.route('/addze/<int:gid>')	
@helpers.login_required
def addze(gid=None):
	# deal with editting
	# if gid not None, then load all data into an object and pass it
	bigdata = None
	if gid is not None:
		gidyear = str(gid)[:8]
		gameid = str(gid)[8:]
		cur = g.db.execute('SELECT * FROM exits WHERE tracker = ? and gameid = ? ORDER BY id', [getUserId(), gid])
		bigdata = [list(row) for row in cur.fetchall()]
	return render_template('add-ze.html', data=bigdata)

# save data
@app.route('/saveze', methods=['POST'])
def saveze():
	response = {}
	response['success'] = False
	response['message'] = None
	response['row'] = -1
	# check if logged in
	if not session.get('logged_in'):
		response['message'] = "Please login."
		return json.dumps(response)
	gameidyear = request.form['gameidyear']
	gameid = request.form['gameid']
	gid = gameidyear + gameid
	team = request.form['team']
	zentries = request.form['table']
	# check if gameidyear is 8 digit number
	if len(gameidyear) != 8 and not gameidyear.isdigit():
		response['message'] = "Game ID Year is not valid."
		return json.dumps(response)
	# check if gameid is a 5 digit number
	elif len(gameid) != 5 and not gameid.isdigit():
		response['message'] = "Game ID is not valid"
		return json.dumps(response)
	# check if team in H or A
	elif team not in ['H', 'A']:
		response['message'] = "Team is not valid"
		return json.dumps(response)

	# try and decode json
	zentries = json.loads(zentries)
	loop = 1

	# loop through
	for ze in zentries:
		response['row'] = loop
		# check if period in 1, 2, 3
		if ze['period'] not in ['1','2','3']:
			response['message'] = 'ZE %s does not have a valid period' % (loop)
			return json.dumps(response)
		# check if time is in dd:dd
		elif len(ze['time']) not in [4,5] or ':' not in ze['time']:
			response['message'] = 'ZE %s does not have a valid time' % (loop)
			return json.dumps(response)
		# check if exit 1 of 10
		elif ze['exit'] not in ['C', 'P', 'CH', 'I', 'FP', 'PT', 'FC', 'CT', 'T', 'X']: 
			response['message'] = 'ZE %s does not have a valid exit type' % (loop)
			return json.dumps(response)
		# check if player is d or OPP
		elif not ze['player'].isdigit() and ze['player'] != "OPP":
			response['message'] = 'ZE %s does not have a valid Player' % (loop)
			return json.dumps(response)
		# check if stength is dvd
		loop += 1
	# get user id from session
	cur = g.db.execute('SELECT id FROM users WHERE email=?', [session.get('logged_in')])
	fetchd = cur.fetchone()
	if fetchd is None:
		response['message'] = 'Something has gone wrong - you don\'t exist'
		return json.dumps(response)
	userid = fetchd[0]
	try:
		# delete all entries for this game for this user
		g.db.execute('DELETE FROM exits WHERE gameid = ? and tracker = ?', [gid, userid])
		g.db.commit()
		# loop through entries again
		for ze in zentries:
			l = ze['time'].split(":")
			ze['time'] = int(l[0])*60 + int(l[1])
			# save each item
			g.db.execute('INSERT INTO exits (gameid, tracker, team, period, time, exittype, player, strength, pressure) VALUES (?, ?, ?, ?, ?, ?, ?,?,?)',
							[gid, userid, team, ze['period'], ze['time'], ze['exit'], ze['player'], -1, -1])
			g.db.commit()
	except Exception as e:
		response['message'] = 'Something went wrong with saving on the server side.  Please contact Josh. '+str(e)
		return json.dumps(response)
	# response
	response['success'] = True
	response['message'] = 'Successfully saved.'
	return json.dumps(response)

# sign up users
@app.route('/register', methods=['GET', 'POST'])
def register():
	error = None
	if request.method == 'POST':
		# count rows
		cur = g.db.execute('SELECT * FROM users WHERE email=?', [request.form['email']])
		if not re.match(r'[^@]+@[^@]+\.[^@]+', request.form['email']):
			error = 'This is not a valid email.'
		elif cur.fetchone() is not None:
			error = 'This email is already in use.'
		elif len(request.form['password']) < 8:
			error = 'The password must be a minimum of 8 characters.'
		else:
			password = hashlib.sha224(request.form['password']).hexdigest()
			g.db.execute('INSERT INTO users (email, password) VALUES (?,?)',
				[request.form['email'], password])
			g.db.commit()
			session['logged_in'] = request.form['email']
			flash('You\'ve successfully registered!')
			return redirect(url_for('index'))
	return render_template('register.html', error=error)

# login
@app.route('/login', methods=['GET', 'POST'])
def login():
	error = None
	if request.method == 'POST':
		username = request.form['username']
		password = password = hashlib.sha224(request.form['password']).hexdigest()
		cur = g.db.execute('SELECT * FROM users WHERE email=? AND password=?', [username, password])
		fetchd = cur.fetchone()
		if fetchd is None:
			error = 'Invalid login credentials.'
		else:
			session['logged_in'] = username
			flash('You were logged in')
			return redirect(url_for('index'))
	return render_template('login.html', error=error)

#logout
@app.route('/logout')
def logout():
	session.pop('logged_in', None)
	flash('You were logged out')
	return redirect(url_for('index'))

# run the app
if __name__ == '__main__':
	app.run()
