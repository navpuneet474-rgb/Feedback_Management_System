import os
import re
import secrets
import logging
import sys
from logging import Formatter
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from functools import wraps

import psycopg2
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
from authlib.integrations.flask_client import OAuth
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__, static_folder='static')
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-me-in-production')

# Database Configuration
db_config = {
    'dbname':   os.getenv('DBNAME'),
    'user':     os.getenv('DBUSER'),
    'host':     os.getenv('DBHOST'),
    'password': os.getenv('DBPWD'),
    'port':     os.getenv('DBPORT'),
}

# App Configuration
ADMIN_EMAIL         = os.getenv('ADMIN_EMAIL', 'admin@sitare.org')
COURSE_MANAGER_EMAIL = os.getenv('COURSE_MANAGER_EMAIL', 'kushal@sitare.org')
WEEK_START_DATE     = os.getenv('WEEK_START_DATE', '2024-08-27')
FEEDBACK_DAYS       = {int(d) for d in os.getenv('FEEDBACK_DAYS', '4,5,6,0').split(',')}
# Weekday ints: 0=Mon,1=Tue,2=Wed,3=Thu,4=Fri,5=Sat,6=Sun

# OAuth Configuration 
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    access_token_url='https://oauth2.googleapis.com/token',
    redirect_uri=os.getenv('GOOGLE_REDIRECT_URI'),
    client_kwargs={'scope': 'openid email profile'},
    jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
)

# ─── Logging
def setup_logging(application):
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(Formatter(
        '%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]'
    ))
    handler.setLevel(logging.WARNING)
    application.logger.addHandler(handler)
    application.logger.setLevel(logging.INFO)

setup_logging(app)

# ─── Database
def get_db_connection():
    try:
        conn = psycopg2.connect(**db_config)
        return conn
    except psycopg2.Error as e:
        app.logger.error(f"Database connection error: {e}")
        return None

# ─── Auth Decorators 
def login_required(f):
    """Redirect to login if no session exists."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('user_info'):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def student_required(f):
    """Only allow student emails (su-*@sitare.org)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = session.get('user_info')
        if not user_info or not re.match(r'^su-.*@sitare\.org$', user_info['email']):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def teacher_required(f):
    """Only allow teacher emails (@sitare.org, non-student, non-admin)."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = session.get('user_info')
        if not user_info or not re.match(r'^[a-zA-Z0-9._%+-]+@sitare\.org$', user_info['email']):
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

def admin_required(f):
    """Only allow the admin email."""
    @wraps(f)
    def decorated(*args, **kwargs):
        user_info = session.get('user_info')
        if not user_info or user_info['email'] != ADMIN_EMAIL:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated

# ─── Week Calculation 
def get_current_week_number():
    """Return the current academic week number based on WEEK_START_DATE."""
    initial_start = datetime.strptime(WEEK_START_DATE, "%Y-%m-%d")
    now = datetime.now(timezone.utc).replace(tzinfo=None)  # keep naive for comparison
    for i in range(60):
        week_start = initial_start + timedelta(weeks=i)
        week_end   = week_start + timedelta(days=6)
        if week_start <= now <= week_end:
            return i + 1
    return None

# ─── Helpers 
def is_student_email(email):
    return bool(re.match(r'^su-.*@sitare\.org$', email))

def is_teacher_email(email):
    return bool(re.match(r'^[a-zA-Z0-9._%+-]+@sitare\.org$', email))

def already_submitted_today(conn, student_email):
    """Return True if student already submitted feedback today (UTC)."""
    today = datetime.now(timezone.utc).date()
    with conn.cursor() as cur:
        cur.execute(
            "SELECT 1 FROM feedback WHERE studentemailid = %s AND DateOfFeedback = %s",
            (student_email, today)
        )
        return cur.fetchone() is not None

# ─── Routes: Public 
@app.route('/')
def home():
    return render_template('index.html')

@app.route('/about_us')
def about():
    return render_template('about_us.html')

@app.route('/login')
def login():
    session.pop('user_info', None)
    session.pop('token', None)
    session.pop('nonce', None)
    redirect_uri = url_for('authorize', _external=True)
    nonce = secrets.token_urlsafe(16)
    state = secrets.token_urlsafe(16)
    session['nonce'] = nonce
    session['state'] = state
    return google.authorize_redirect(redirect_uri, nonce=nonce, state=state)

@app.route('/authorize')
def authorize():
    nonce = session.pop('nonce', None)
    token = google.authorize_access_token(nonce=nonce)
    session['token'] = token
    user_info = google.parse_id_token(token, nonce=nonce)

    if not user_info:
        app.logger.warning("OAuth authorization failed — no user_info returned.")
        return render_template('error.html'), 400

    email = user_info['email']
    name  = user_info.get('name', 'User')
    session['user_info'] = {'email': email, 'name': name}

    if email == ADMIN_EMAIL:
        return redirect(url_for('admin_portal'))
    elif is_student_email(email):
        return redirect(url_for('dashboard'))
    elif is_teacher_email(email):
        return redirect(url_for('teacher_portal'))
    else:
        return render_template('unauthorized.html'), 403

@app.route('/logout')
def logout():
    session.clear()
    app.logger.info("User logged out.")
    return redirect(url_for('home'))

# ─── Routes: Dashboard / Redirect 
@app.route('/dashboard')
@login_required
def dashboard():
    email = session['user_info']['email']
    if email == ADMIN_EMAIL:
        return redirect(url_for('admin_portal'))
    elif is_student_email(email):
        return render_template('redirect_page.html')
    elif is_teacher_email(email):
        return redirect(url_for('teacher_portal'))
    return render_template('error.html'), 400

@app.route('/redirect_page')
@login_required
def redirect_page():
    student_email = session['user_info']['email']
    feedback_submitted = False
    conn = get_db_connection()
    if conn:
        try:
            # TESTING: Comment out to allow multiple submissions
            # feedback_submitted = already_submitted_today(conn, student_email)
            pass
        except psycopg2.Error as e:
            app.logger.error(f"DB error in redirect_page: {e}")
        finally:
            conn.close()
    return render_template('redirect_page.html', feedback_submitted=feedback_submitted)

# ─── Routes: Student 
@app.route('/student_portal')
@student_required
def student_portal():
    user_info     = session['user_info']
    student_email = user_info['email']
    today_weekday = datetime.now(timezone.utc).weekday()
    is_feedback_allowed = today_weekday in FEEDBACK_DAYS

    conn = get_db_connection()
    if not conn:
        return render_template('error.html'), 500

    try:
        # TESTING: Comment out to allow multiple submissions
        # Check duplicate submission in same connection
        # if already_submitted_today(conn, student_email):
        #     return render_template('student_portal.html', user_info=user_info, feedback_submitted=True)

        # Extract batch pattern: 'su-23028@...' → 'su-23'
        batch_pattern = 'su-' + student_email.split('-')[1][:2]

        with conn.cursor() as cur:
            cur.execute("""
                SELECT c.course_id, c.course_name, i.instructor_name, i.instructor_email
                FROM courses c
                JOIN instructors i ON c.instructor_id = i.instructor_id
                WHERE c.batch_pattern = %s AND c.active = TRUE
            """, (batch_pattern,))
            courses_data = cur.fetchall()

        if not courses_data:
            return render_template('error.html'), 404

        courses = []
        instructor_emails = {}
        for course_id, course_name, instructor_name, instructor_email in courses_data:
            courses.append({
                "course_id":   str(course_id),   # FIX: store as string to match form keys
                "course_name": f"{course_name}: {instructor_name}"
            })
            instructor_emails[str(course_id)] = instructor_email  # FIX: string key

        session['instructor_emails'] = instructor_emails

        return render_template(
            'student_portal.html',
            is_feedback_allowed=is_feedback_allowed,
            user_info=user_info,
            courses=courses
        )
    except psycopg2.Error as e:
        app.logger.error(f"DB error in student_portal: {e}")
        return render_template('error.html'), 500
    finally:
        conn.close()

@app.route('/submit_all_forms', methods=['POST'])
@student_required
def submit_all_forms():
    student_email    = session['user_info']['email']
    student_name     = session['user_info']['name']
    instructor_emails = session.get('instructor_emails', {})

    conn = get_db_connection()
    if not conn:
        return jsonify({"status": "error", "message": "Database connection failed."}), 500

    try:
        # TESTING: Comment out to allow multiple submissions
        # Guard: duplicate submission
        # if already_submitted_today(conn, student_email):
        #     return jsonify({"status": "already_submitted"})

        current_week = get_current_week_number()
        date_of_feedback = datetime.now(timezone.utc).date()
        data = request.form.to_dict(flat=False)

        # Parse form data
        feedback_entries = {}
        for key, values in data.items():
            match = re.match(r'course_(\d+)\[(\w+)\]', key)
            if not match:
                continue
            course_id = match.group(1)    # already a string from the form
            field     = match.group(2)
            if field not in ('understanding', 'revision', 'suggestion'):
                continue
            feedback_entries.setdefault(course_id, {'understanding': None, 'revision': None, 'suggestion': None})
            feedback_entries[course_id][field] = values[0]

        # Validate and prepare rows
        prepared = []
        for course_id, form_data in feedback_entries.items():
            understanding = form_data.get('understanding')
            revision      = form_data.get('revision')
            if not understanding or not revision:
                return jsonify({"status": "error", "message": "All questions must be rated."}), 400

            instructor = instructor_emails.get(course_id)   # FIX: string key matches
            if not instructor:
                app.logger.warning(f"No instructor found for course_id={course_id}")

            prepared.append((
                course_id, student_email, student_name,
                date_of_feedback, current_week,
                instructor,
                int(understanding), int(revision),
                form_data.get('suggestion') or 'None'
            ))

        with conn.cursor() as cur:
            cur.executemany("""
                INSERT INTO feedback
                    (coursecode2, studentemailid, StudentName, DateOfFeedback,
                     Week, instructorEmailID, Question1Rating, Question2Rating, Remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, prepared)
        conn.commit()
        app.logger.info(f"Feedback submitted by {student_email} for {len(prepared)} course(s).")
        return jsonify({"status": "success"})

    except psycopg2.Error as e:
        conn.rollback()
        app.logger.error(f"DB error in submit_all_forms: {e}")
        return jsonify({"status": "error", "message": "Database error occurred."}), 500
    except Exception as e:
        app.logger.error(f"Unexpected error in submit_all_forms: {e}")
        return jsonify({"status": "error", "message": "An unexpected error occurred."}), 500
    finally:
        conn.close()

@app.route('/previous_feedback', methods=['GET', 'POST'])
@student_required
def previous_feedback():
    user_info     = session['user_info']
    student_email = user_info['email']
    feedback_data = []

    if request.method == 'POST':
        num_weeks = request.form.get('num_feedback', '0')
        if num_weeks == '0':
            return render_template('previous_feedback.html', user_info=user_info, feedback_data=[])

        conn = get_db_connection()
        if not conn:
            flash('Database connection failed.', 'danger')
            return render_template('previous_feedback.html', user_info=user_info, feedback_data=[])

        try:
            query = """
                SELECT c.course_name, f.DateOfFeedback, f.Week,
                       f.Question1Rating, f.Question2Rating, f.Remarks
                FROM feedback f
                JOIN courses c ON f.coursecode2 = c.course_id::varchar
                WHERE f.studentemailid = %s AND f.active = TRUE
            """
            params = [student_email]

            if num_weeks != 'all':
                if num_weeks.isdigit() and int(num_weeks) > 0:
                    start_date = datetime.now(timezone.utc) - timedelta(
                        days=datetime.now(timezone.utc).weekday() + int(num_weeks) * 7
                    )
                    query  += " AND f.DateOfFeedback >= %s"
                    params.append(start_date)
                else:
                    app.logger.warning(f"Invalid num_weeks value: {num_weeks}")
                    return render_template('previous_feedback.html', user_info=user_info, feedback_data=[])

            query += " ORDER BY f.DateOfFeedback DESC"

            with conn.cursor() as cur:
                cur.execute(query, tuple(params))
                feedback_data = cur.fetchall()

            app.logger.info(f"Fetched {len(feedback_data)} feedback rows for {student_email}.")
        except psycopg2.Error as e:
            app.logger.error(f"DB error in previous_feedback: {e}")
            flash('Error fetching feedback data.', 'danger')
        finally:
            conn.close()

    return render_template('previous_feedback.html', user_info=user_info, feedback_data=feedback_data)

# ─── Routes: Teacher 
def get_feedback_data(instructor_email):
    conn = get_db_connection()
    if not conn:
        return [], {}
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT f.coursecode2, f.DateOfFeedback, f.StudentName, f.Week,
                       f.Question1Rating, f.Question2Rating, f.Remarks,
                       f.studentemailid, c.course_name
                FROM feedback f
                JOIN courses c ON f.coursecode2 = CAST(c.course_id AS VARCHAR)
                WHERE f.instructorEmailID = %s
                  AND f.DateOfFeedback >= (CURRENT_DATE - INTERVAL '2 weeks')
                ORDER BY f.coursecode2, f.Week, f.DateOfFeedback DESC
            """, (instructor_email,))
            feedback_data = cur.fetchall()
    except psycopg2.Error as e:
        app.logger.error(f"DB error in get_feedback_data: {e}")
        return [], {}
    finally:
        conn.close()

    grouped_remarks = {}
    for row in feedback_data:
        course, week, remark = row[0], row[3], row[6]
        grouped_remarks.setdefault(course, {}).setdefault(week, []).append(remark)

    return feedback_data, grouped_remarks

def calculate_average_ratings_by_week(feedback_data):
    weekly = defaultdict(lambda: {'q1': 0, 'q2': 0, 'count': 0})
    for row in feedback_data:
        week = row[3]
        weekly[week]['q1']    += row[4] or 0
        weekly[week]['q2']    += row[5] or 0
        weekly[week]['count'] += 1
    return {
        week: (v['q1'] / v['count'], v['q2'] / v['count'], v['count'])
        for week, v in weekly.items()
    }

def calculate_rating_distributions(feedback_data):
    dist_q1 = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    dist_q2 = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for row in feedback_data:
        q1, q2 = row[4] or 0, row[5] or 0
        if q1 in dist_q1: dist_q1[q1] += 1
        if q2 in dist_q2: dist_q2[q2] += 1
    return dist_q1, dist_q2

@app.route('/teacher_portal')
@teacher_required
def teacher_portal():
    user_info        = session['user_info']
    instructor_email = user_info['email']
    feedback_data, grouped_remarks = get_feedback_data(instructor_email)

    manage_courses = (instructor_email == COURSE_MANAGER_EMAIL)  # FIX: no hardcoding

    feedback_by_course = {}
    for row in feedback_data:
        course_id, course_name = row[0], row[8]
        feedback_by_course.setdefault(course_id, {'course_name': course_name, 'data': []})
        feedback_by_course[course_id]['data'].append(row)

    course_summaries = {}
    for course_id, info in feedback_by_course.items():
        data = info['data']
        course_summaries[course_id] = {
            'course_name':    info['course_name'],
            'avg_ratings':    calculate_average_ratings_by_week(data),
            'distribution_q1': calculate_rating_distributions(data)[0],
            'distribution_q2': calculate_rating_distributions(data)[1],
            'latest_date':    max(row[1] for row in data),
        }

    if request.args.get('data') == 'json':
        return jsonify(course_summaries)

    return render_template(
        'teacher_portal.html',
        user_info=user_info,
        feedback_data=feedback_data,
        grouped_remarks=grouped_remarks,
        manage_courses=manage_courses,
        course_summaries=course_summaries,
    )

# ─── Routes: Admin 
@app.route('/admin_portal')
@admin_required   # FIX: was crashing with NameError 'email'
def admin_portal():
    user_info = session['user_info']

    # FIX: instructor list now fetched from DB, not hardcoded
    conn = get_db_connection()
    if not conn:
        return render_template('error.html'), 500

    instructor_names      = {}
    feedback_data_by_email = {}
    avg_ratings_by_email  = {}

    try:
        with conn.cursor() as cur:
            cur.execute("SELECT instructor_email, instructor_name FROM instructors")
            instructor_names = {row[0]: row[1] for row in cur.fetchall()}

        email_ids = list(instructor_names.keys())
        if email_ids:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT instructorEmailID, CourseCode2, DateOfFeedback,
                           Week, Question1Rating, Question2Rating, Remarks
                    FROM feedback
                    WHERE instructorEmailID = ANY(%s)
                      AND DateOfFeedback >= (CURRENT_DATE - INTERVAL '2 weeks')
                """, (email_ids,))
                rows = cur.fetchall()

            for row in rows:
                email = row[0]
                feedback_data_by_email.setdefault(email, []).append(row[1:])

            for email, data in feedback_data_by_email.items():
                count  = len(data)
                avg_q1 = sum(r[3] for r in data if r[3]) / count if count else 0
                avg_q2 = sum(r[4] for r in data if r[4]) / count if count else 0
                avg_ratings_by_email[email] = (avg_q1, avg_q2)

    except psycopg2.Error as e:
        app.logger.error(f"DB error in admin_portal: {e}")
        flash('Error loading admin data.', 'danger')
    finally:
        conn.close()

    return render_template(
        'admin_portal.html',
        user_info=user_info,
        feedback_data_by_email=feedback_data_by_email,
        avg_ratings_by_email=avg_ratings_by_email,
        instructor_names=instructor_names,
    )

# Routes: Course Management 
@app.route('/get_courses', methods=['GET'])
@login_required
def get_courses():
    conn = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 500
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT course_id, course_name FROM courses")
            courses = cur.fetchall()
        return jsonify({'courses': [{'course_id': c[0], 'course_name': c[1]} for c in courses]})
    except psycopg2.Error as e:
        app.logger.error(f"DB error in get_courses: {e}")
        return jsonify({'error': 'Failed to fetch courses'}), 500
    finally:
        conn.close()

@app.route('/get_form/<int:course_id>')
@login_required
def get_form(course_id):
    conn = get_db_connection()
    if not conn:
        return render_template('error.html'), 500
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT course_id FROM courses WHERE course_id = %s", (course_id,))
            if not cur.fetchone():
                return render_template('error.html'), 404
        return render_template('course_form.html', course_id=course_id)
    except psycopg2.Error as e:
        app.logger.error(f"DB error in get_form: {e}")
        return render_template('error.html'), 500
    finally:
        conn.close()

@app.route('/add_instructor', methods=['POST'])
@teacher_required
def add_instructor():
    instructor_name  = request.form.get('instructor_name', '').strip()
    instructor_email = request.form.get('instructor_email', '').strip()

    if not instructor_name or not instructor_email:
        flash('Please fill in all required fields.', 'warning')
        return redirect(url_for('course_manager'))

    if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', instructor_email):
        flash('Invalid email address.', 'danger')
        return redirect(url_for('course_manager'))

    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'danger')
        return redirect(url_for('course_manager'))
    try:
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO instructors (instructor_name, instructor_email)
                VALUES (%s, %s)
                ON CONFLICT (instructor_email) DO NOTHING
            """, (instructor_name, instructor_email))
        conn.commit()
        flash('Instructor added successfully!', 'success')
    except psycopg2.Error as e:
        conn.rollback()
        app.logger.error(f"DB error in add_instructor: {e}")
        flash('Failed to add instructor. Please try again.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('course_manager', success='instructor'))

@app.route('/course_manager', methods=['GET', 'POST'])
@teacher_required
def course_manager():
    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'danger')
        return render_template('course_management.html', instructors=[], courses_with_instructors=[])

    instructors             = []
    courses_with_instructors = []

    try:
        if request.method == 'POST':
            course_name   = request.form['course_name'].strip()
            instructor_name = request.form['instructor_name'].strip()
            batch_pattern = request.form['batch_pattern'].strip()
            semester      = request.form['semester'].strip()
            active        = 'active' in request.form

            with conn.cursor() as cur:
                cur.execute(
                    "SELECT instructor_id FROM instructors WHERE instructor_name = %s",
                    (instructor_name,)
                )
                instructor = cur.fetchone()
                if not instructor:
                    flash(f'Instructor "{instructor_name}" not found. Please add them first.', 'warning')
                    return redirect(url_for('course_manager'))
                instructor_id = instructor[0]

                cur.execute(
                    "UPDATE courses SET active = FALSE WHERE semester != %s",
                    (semester,)
                )
                cur.execute("""
                    INSERT INTO courses (course_name, instructor_id, semester, active, batch_pattern)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (course_name, instructor_id, batch_pattern, semester)
                    DO UPDATE SET active = EXCLUDED.active
                """, (course_name, instructor_id, semester, active, batch_pattern))
            conn.commit()
            flash('Course updated successfully.', 'success')
            return redirect(url_for('course_manager', success='course'))

        with conn.cursor() as cur:
            cur.execute("SELECT * FROM instructors ORDER BY instructor_name")
            instructors = cur.fetchall()
            cur.execute("""
                SELECT c.course_name, i.instructor_name
                FROM courses c
                JOIN instructors i ON c.instructor_id = i.instructor_id
                ORDER BY c.course_name
            """)
            courses_with_instructors = cur.fetchall()

    except psycopg2.Error as e:
        conn.rollback()
        app.logger.error(f"DB error in course_manager: {e}")
        flash('An error occurred.', 'danger')
    finally:
        conn.close()

    return render_template(
        'course_management.html',
        instructors=instructors,
        courses_with_instructors=courses_with_instructors,
    )

@app.route('/update_course', methods=['POST'])
@admin_required
def update_course():
    course_id        = request.form.get('course_id')
    course_name      = request.form.get('course_name', '').strip()
    instructor_name  = request.form.get('instructor_name', '').strip()
    instructor_email = request.form.get('instructor_email', '').strip()
    semester         = request.form.get('semester', '').strip()
    active           = bool(request.form.get('active'))

    if not course_id or not course_id.isdigit():
        flash('Invalid course ID.', 'danger')
        return redirect(url_for('admin_portal'))

    conn = get_db_connection()
    if not conn:
        flash('Database connection failed.', 'danger')
        return redirect(url_for('admin_portal'))
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT instructor_id FROM instructors WHERE instructor_email = %s",
                (instructor_email,)
            )
            instructor = cur.fetchone()
            if instructor:
                instructor_id = instructor[0]
            else:
                cur.execute(
                    "INSERT INTO instructors (instructor_name, instructor_email) VALUES (%s, %s) RETURNING instructor_id",
                    (instructor_name, instructor_email)
                )
                instructor_id = cur.fetchone()[0]

            cur.execute("""
                INSERT INTO courses (course_id, course_name, instructor_id, semester, active)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (course_id)
                DO UPDATE SET
                    course_name   = EXCLUDED.course_name,
                    instructor_id = EXCLUDED.instructor_id,
                    semester      = EXCLUDED.semester,
                    active        = EXCLUDED.active
            """, (int(course_id), course_name, instructor_id, semester, active))
        conn.commit()
        flash('Course updated.', 'success')
    except psycopg2.Error as e:
        conn.rollback()
        app.logger.error(f"DB error in update_course: {e}")
        flash('Failed to update course.', 'danger')
    finally:
        conn.close()

    return redirect(url_for('admin_portal'))

# ─── Database Setup
def verify_db_tables():
    """
    Check required tables exist at startup.
    Schema + seed data are managed via seed.sql — run once before starting:
        psql -d your_db_name -f seed.sql
    """
    REQUIRED_TABLES = ('instructors', 'courses', 'feedback')
    conn = get_db_connection()
    if not conn:
        app.logger.error("Startup DB check failed: could not connect.")
        return
    try:
        with conn.cursor() as cur:
            for table in REQUIRED_TABLES:
                cur.execute("""
                    SELECT EXISTS (
                        SELECT 1 FROM information_schema.tables
                        WHERE table_schema = 'public' AND table_name = %s
                    )
                """, (table,))
                if not cur.fetchone()[0]:
                    app.logger.error(f"Table '{table}' missing. Run: psql -d your_db_name -f seed.sql")
                else:
                    app.logger.info(f"Table '{table}' OK.")
    except psycopg2.Error as e:
        app.logger.error(f"DB verification error: {e}")
    finally:
        conn.close()


# ─── Error Handlers 
@app.errorhandler(404)
def not_found(e):
    return render_template('error.html'), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('unauthorized.html'), 403

@app.errorhandler(Exception)
def handle_exception(e):
    app.logger.error(f"Unhandled exception: {e}", exc_info=True)
    return render_template('error.html'), 500

# ─── Startup 
verify_db_tables()   # only checks tables exist — data comes from seed.sql

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)