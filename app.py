import os
# new
from flask import Flask, render_template, request, jsonify, session, redirect, url_for, flash
import psycopg2
from collections import defaultdict
import re
import secrets
from authlib.integrations.flask_client import OAuth
from datetime import datetime, timedelta, timezone
import logging
import sys
from logging import Formatter
import time 
from dotenv import load_dotenv 

# Here you need to change
load_dotenv()

app = Flask(__name__,static_folder='static')

app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'Secret_key')

# Database configuration
db_config = {
    'dbname': os.getenv('DBNAME'),
    'user': os.getenv("DBUSER"),
    'host': os.getenv("DBHOST"),
    'password': os.getenv("DBPWD"),
    'port': os.getenv("DBPORT")
}
# OAuth configuration
oauth = OAuth(app)
google = oauth.register(
    name='google',
    client_id=os.getenv('GOOGLE_CLIENT_ID'),
    client_secret=os.getenv('GOOGLE_CLIENT_SECRET'),
    authorize_url='https://accounts.google.com/o/oauth2/auth',
    authorize_params=None,
    access_token_url='https://oauth2.googleapis.com/token',
    access_token_params=None,
    refresh_token_url=None,
    refresh_token_params=None,
    redirect_uri=os.getenv('GOOGLE_REDIRECT_URI'),
    client_kwargs={'scope': 'openid email profile'},
    jwks_uri='https://www.googleapis.com/oauth2/v3/certs',
)

def get_db_connection():
    try:
        conn = psycopg2.connect(
            dbname=db_config['dbname'],
            user=db_config['user'],
            password=db_config['password'],
            host=db_config['host'],
            port=db_config['port']
        )
        print("Database connection established.")
        return conn
    except psycopg2.Error as e:
        app.logger.error(f"Database connection error: {str(e)}")
        return None

# Set up logging to stderr
def log_to_stderr(app):
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(Formatter(
        '%(asctime)s %(levelname)s: %(message)s '
        '[in %(pathname)s:%(lineno)d]'
    ))
    handler.setLevel(logging.WARNING)  # Set log level
    app.logger.addHandler(handler)

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

    # Here you need to change
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

    if user_info:
        email = user_info['email']
        name = user_info.get('name', 'User')
        session['user_info'] = {'email': email, 'name': name}

        if re.match(r'^su-.*@sitare\.org$', email):
            return redirect(url_for('dashboard'))
        elif re.match(r'^[a-zA-Z0-9._%+-]+@sitare\.org$', user_info['email']):
            return redirect(url_for('teacher_portal'))
        elif re.match(r'^admin@sitare\.org$', email):
            return redirect(url_for('admin_portal'))
        else:
            return render_template('unauthorized.html'), 400
    else:
    
        return "Authorization failed", 400

@app.route('/dashboard')
def dashboard():
    user_info = session.get('user_info')

    if not user_info:
        return redirect(url_for('login'))

    if re.match(r'^su-.*@sitare\.org$', user_info['email']):
        return render_template('redirect_page.html')
    elif re.match(r'^[a-zA-Z0-9._%+-]+@sitare\.org$', user_info['email']):
        return redirect(url_for('teacher_portal'))
    elif re.match(r'^admin@sitare\.org$', user_info['email']):
        return redirect(url_for('admin_portal'))
    else:
        # Redirect to error page for unexpected behavior or invalid roles
        return render_template('error.html'), 400

@app.route('/logout')
def logout():
    session.pop('user_info', None)
    session.pop('token', None)
    session.pop('nonce', None)
    print("User logged out. Session cleared.")
    return redirect(url_for('home'))

@app.route('/student_portal')
def student_portal():
    user_info = session.get('user_info')
    if not user_info or not re.match(r'^su-.*@sitare\.org$', user_info['email']):
        return redirect(url_for('login'))
    
    current_day = datetime.now(timezone.utc).weekday()
    is_feedback_allowed = (current_day == 6 or current_day == 5 or current_day == 4 or current_day ==0)  # 6 for sunday,5 for saturday,4 for friday 

    # code for submitting the data one time in a day
    student_email_id = user_info.get('email')
    current_datetime = datetime.now(timezone.utc)
    current_date = current_datetime.date()
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM feedback WHERE studentemailid = %s AND DateOfFeedback = %s", (student_email_id, current_date))
    feedback_submitted = cursor.fetchone()
    if feedback_submitted:
        return render_template('student_portal.html', user_info=user_info, feedback_submitted=True)
    
    # Extract batch pattern from the student's email
    batch_pattern = student_email_id.split('-')[1][:2]  # Extract '23' from 'su-23028'
    batch_pattern = f"su-{batch_pattern}"  # Format it back to 'su-23'

    conn = get_db_connection()
    if conn:
        try:
            with conn.cursor() as cursor:

                # Fetch active courses matching the batch pattern
                cursor.execute("""
                    SELECT courses.course_id, courses.course_name, instructors.instructor_name, instructors.instructor_email 
                    FROM courses
                    JOIN instructors ON courses.instructor_id = instructors.instructor_id
                    WHERE courses.batch_pattern = %s AND courses.active = TRUE
                """, (batch_pattern,))
                courses_data = cursor.fetchall()

                if not courses_data:
                    return "No active courses found for your batch", 404

                courses = []
                instructor_emails = {}

                for course_id, course_name, instructor_name, instructor_email in courses_data:
                    courses.append({"course_id": course_id, "course_name": f"{course_name}: {instructor_name}"})
                    instructor_emails[course_id] = instructor_email

                # Store instructor emails in the session for future use
                session['instructor_emails'] = instructor_emails

                return render_template(
                    'student_portal.html',
                    is_feedback_allowed=is_feedback_allowed,
                    user_info=user_info,
                    courses=courses
                )
        except psycopg2.Error as e:
            app.logger.error(f"Database error in student_portal: {str(e)}")
            return "An error occurred while fetching data", 500
        finally:
            conn.close()
    else:
        return "Database connection failed", 500

@app.route('/get_courses', methods=['GET'])
def get_courses():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Fetch course IDs from the courses table
    query = "SELECT course_id, course_name FROM courses"
    cursor.execute(query)
    courses = cursor.fetchall()
    
    cursor.close()
    conn.close()
    
    # Format response
    course_data = [{'course_id': course[0], 'course_name': course[1]} for course in courses]
    
    return jsonify({'courses': course_data})


@app.route('/previous_feedback', methods=['GET', 'POST'])
def previous_feedback():
    user_info = session.get('user_info')

    student_email = user_info.get('email')
    feedback_data = []  # Default to show no data

    if request.method == 'POST':
        num_weeks = request.form.get('num_feedback', '0')
        if num_weeks != '0':
            try:
                conn = get_db_connection()
                if conn:
                    with conn.cursor() as cursor:
                        query = """
                            SELECT 
                                c.course_name, 
                                f.DateOfFeedback, 
                                f.Week, 
                                f.Question1Rating, 
                                f.Question2Rating, 
                                f.Remarks
                            FROM 
                                feedback f
                            JOIN 
                                courses c ON f.coursecode2 = c.course_id::varchar
                            WHERE 
                                f.studentemailid = %s AND f.active = TRUE
                        """
                        params = [student_email]

                        if num_weeks != 'all':
                            if num_weeks.isdigit() and int(num_weeks) > 0:
                                start_date = datetime.now() - timedelta(days=datetime.now().weekday() + int(num_weeks) * 7)
                                query += " AND f.DateOfFeedback >= %s"
                                params.append(start_date)
                            else:
                                print(f"Invalid num_weeks value: {num_weeks}")
                                return render_template('saturday.html', user_info=user_info, feedback_data=[])

                        query += " ORDER BY f.DateOfFeedback DESC"
                        
                        print(f"Executing query: {query}")
                        print(f"With parameters: {params}")
                        
                        cursor.execute(query, tuple(params))
                        feedback_data = cursor.fetchall()
                        
                        print(f"Fetched {len(feedback_data)} rows of feedback data")
                        
                    print(f"Feedback data fetched for student: {student_email}")
                else:
                    print("Failed to establish database connection.")
            except psycopg2.Error as e:
                print(f"Database error while fetching feedback: {str(e)}")
                print(f"Query that caused the error: {query}")
                print(f"Parameters: {params}")
            finally:
                if conn:
                    conn.close()

    return render_template('previous_feedback.html', user_info=user_info, feedback_data=feedback_data)


def get_feedback_data(instructor_email):
    query = """
        SELECT f.coursecode2, f.DateOfFeedback, f.StudentName, f.Week, f.Question1Rating, f.Question2Rating, f.Remarks, f.studentemailid, c.course_name
        FROM feedback f
        JOIN courses c ON f.coursecode2 = CAST(c.course_id AS VARCHAR)
        WHERE f.instructorEmailID = %s AND f.DateOfFeedback >= (CURRENT_DATE - INTERVAL '2 weeks')
        ORDER BY f.coursecode2, f.Week, f.DateOfFeedback DESC
    """
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute(query, (instructor_email,))
    feedback_data = cursor.fetchall()
    cursor.close()
    conn.close()

    # Group remarks by course and week
    grouped_remarks = {}
    for row in feedback_data:
        course = row[0]
        week = row[3]
        remark = row[6]
        if course not in grouped_remarks:
            grouped_remarks[course] = {}
        if week not in grouped_remarks[course]:
            grouped_remarks[course][week] = []
        grouped_remarks[course][week].append(remark)

    return feedback_data, grouped_remarks



def calculate_average_ratings_by_week(feedback_data):
    weekly_ratings = defaultdict(lambda: {'q1_total': 0, 'q2_total': 0, 'count': 0})
    for row in feedback_data:
        week = row[3]  # Assuming Week is the third column
        q1_rating = row[4] if row[4] is not None else 0
        q2_rating = row[5] if row[5] is not None else 0
        weekly_ratings[week]['q1_total'] += q1_rating
        weekly_ratings[week]['q2_total'] += q2_rating
        weekly_ratings[week]['count'] += 1

    avg_ratings_by_week = {}
    for week, ratings in weekly_ratings.items():
        avg_q1 = ratings['q1_total'] / ratings['count']
        avg_q2 = ratings['q2_total'] / ratings['count']
        feedback_count = ratings['count']
        avg_ratings_by_week[week] = (avg_q1, avg_q2, feedback_count)

    return avg_ratings_by_week

def calculate_rating_distributions(feedback_data):
    rating_distribution_q1 = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    rating_distribution_q2 = {1: 0, 2: 0, 3: 0, 4: 0, 5: 0}
    for row in feedback_data:
        q1_rating = row[4] if row[4] is not None else 0
        q2_rating = row[5] if row[5] is not None else 0
        if q1_rating in rating_distribution_q1:
            rating_distribution_q1[q1_rating] += 1
        if q2_rating in rating_distribution_q2:
            rating_distribution_q2[q2_rating] += 1
    return rating_distribution_q1, rating_distribution_q2


get_db_connection()


@app.route('/teacher_portal')
def teacher_portal():
    user_info = session.get('user_info')
    if not user_info or not re.match(r'^[a-zA-Z0-9._%+-]+@sitare\.org$', user_info['email']):
        return redirect(url_for('login'))

    instructor_email = user_info['email']
    feedback_data, grouped_remarks = get_feedback_data(instructor_email)

    # for course and instructor mangement access button

    manage_courses = instructor_email =="kushal@sitare.org"

    # Group feedback data by course
    feedback_by_course = {}
    for row in feedback_data:
        course_id = row[0]  # CourseCode2 (course ID remains unchanged)
        course_name = row[8]  # Course name is now the last column
        if course_id not in feedback_by_course:
            feedback_by_course[course_id] = {
                'course_name': course_name,
                'data': []
            }
        feedback_by_course[course_id]['data'].append(row)

    course_summaries = {}
    for course_id, course_info in feedback_by_course.items():
        course_data = course_info['data']
        avg_ratings = calculate_average_ratings_by_week(course_data)
        dist_q1, dist_q2 = calculate_rating_distributions(course_data)
        latest_date = max(row[1] for row in course_data)  # DateOfFeedback remains at index 1
        course_summaries[course_id] = {
            'course_name': course_info['course_name'],  # Now we have the course name
            'avg_ratings': avg_ratings,
            'distribution_q1': dist_q1,
            'distribution_q2': dist_q2,
            'latest_date': latest_date
        }

    if request.args.get('data') == 'json':
        return jsonify(course_summaries)

    return render_template(
        'teacher_portal.html',
        user_info=user_info,
        feedback_data=feedback_data,
        grouped_remarks=grouped_remarks,
        manage_courses = manage_courses,
        course_summaries=course_summaries
    )


  
@app.route('/admin_portal')
def admin_portal():
    user_info = session.get('user_info')
    if not user_info or not re.match(r'^admin@sitare\.org$', email):
        return redirect(url_for('login'))
    
    feedback_data_by_email = {}
    
    instructor_names = {
        'kushal@sitare.org': 'Dr. Kushal Shah',
        'sonika@sitare.org': 'Dr.Sonika Thakral',
        'achal@sitare.org': 'Dr.Achal Agrawal',
        'preet@sitare.org': 'Ms.Preet Shukla',
        'amit@sitare.org': 'Dr.Amit Singhal'
    }
    email_ids = list(instructor_names.keys())  # Fetch email_ids from instructor_names

    
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            query = """
                SELECT instructorEmailID, CourseCode2, DateOfFeedback, Week, Question1Rating, Question2Rating, Remarks 
                FROM feedback 
                WHERE instructorEmailID IN %s AND DateOfFeedback >= (CURRENT_DATE - INTERVAL '2 weeks')
            """
            cursor.execute(query, (tuple(email_ids),))
            feedback_data = cursor.fetchall()
            cursor.close()
            conn.close()
            
            # Group feedback data by instructor email ID
            for row in feedback_data:
                email = row[0]
                if email not in feedback_data_by_email:
                    feedback_data_by_email[email] = []
                feedback_data_by_email[email].append(row[1:])  # Exclude the email from row data
            
    except psycopg2.Error as e:
        print(f"Database error: {str(e)}")
    
    # Calculate average ratings for each instructor
    avg_ratings_by_email = {}
    for email, data in feedback_data_by_email.items():
        total_question1_rating = sum(row[3] for row in data if row[3] is not None)
        total_question2_rating = sum(row[4] for row in data if row[4] is not None)
        num_feedbacks = len(data)
        avg_question1_rating = total_question1_rating / num_feedbacks if num_feedbacks > 0 else 0
        avg_question2_rating = total_question2_rating / num_feedbacks if num_feedbacks > 0 else 0
        avg_ratings_by_email[email] = (avg_question1_rating, avg_question2_rating)
        print(feedback_data_by_email)
    
    return render_template('admin_portal.html', user_info=user_info, feedback_data_by_email=feedback_data_by_email, avg_ratings_by_email=avg_ratings_by_email, instructor_names=instructor_names)


@app.route('/add_instructor', methods=['GET', 'POST'])
def add_instructor():
    conn = get_db_connection()
    if request.method == 'POST':
        instructor_name = request.form.get('instructor_name')
        instructor_email = request.form.get('instructor_email')

        if not instructor_name or not instructor_email:
            flash('Please fill in all required fields.')
        else:
            try:
                with conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO instructors (instructor_id, instructor_name, instructor_email)
                        VALUES ((SELECT COALESCE(MAX(instructor_id), 0) + 1 FROM instructors), %s, %s)
                        ON CONFLICT (instructor_email) DO NOTHING
                    """, (instructor_name, instructor_email))
                    conn.commit()
                    flash('Instructor added successfully!', 'success')
                    
                    # Redirect to the same page with a success message
                    return redirect(url_for("course_manager", success="instructor"))
            except psycopg2.Error as e:
                app.logger.error(f"Database error: {str(e)}")
                flash('Failed to add instructor. Please try again.', 'danger')
            finally:
                conn.close()

    return redirect(url_for("course_manager"))


@app.route('/course_manager', methods=['GET', 'POST'])
def course_manager():
    conn = get_db_connection()
    try:
        if request.method == 'POST':
            course_name = request.form['course_name']
            instructor_name = request.form['instructor_name']
            batch_pattern = request.form['batch_pattern']
            semester = request.form['semester']
            active = True if 'active' in request.form else False
            
            with conn.cursor() as cursor:
                # Check if instructor already exists
                cursor.execute("SELECT instructor_id FROM instructors WHERE instructor_name = %s", (instructor_name,))
                instructor = cursor.fetchone()
                instructor_id = instructor[0] if instructor else None


                 # Mark all courses as inactive for previous semesters
                cursor.execute("""
                    UPDATE courses
                    SET active = FALSE
                    WHERE semester != %s
                """, (semester,))
                    
                # Insert or update the course
                cursor.execute("""
                    INSERT INTO courses (course_name, instructor_id, semester, active, batch_pattern)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (course_name, instructor_id, batch_pattern, semester) 
                    DO UPDATE SET 
                        active = EXCLUDED.active
                """, (course_name, instructor_id, semester, active, batch_pattern))
                conn.commit()
                flash('Course details updated successfully', 'success')

                return redirect(url_for("course_manager",success="course"))
            
        # Fetch all instructors for the dropdown
        with conn.cursor() as cursor:
            cursor.execute("SELECT * FROM instructors")
            instructors = cursor.fetchall()

        
        # Fetch all courses with their instructors
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT courses.course_name, instructors.instructor_name 
                FROM courses 
                JOIN instructors ON courses.instructor_id = instructors.instructor_id
            """)
            courses_with_instructors = cursor.fetchall()
    except psycopg2.Error as e:
        app.logger.error(f"Database error: {str(e)}")
        flash('An error occurred while processing the request.', 'danger')
        instructors = []
        courses_with_instructors = []
    finally:
        conn.close()

    return render_template('course_management.html', instructors=instructors, courses_with_instructors=courses_with_instructors)

@app.route('/update_course', methods=['POST'])
def update_course():
    course_id = request.form.get('course_id')
    course_name = request.form.get('course_name')
    instructor_name = request.form.get('instructor_name')
    instructor_email = request.form.get('instructor_email')
    semester = request.form.get('semester')
    active = True if request.form.get('active') else False

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Check if instructor already exists
            cursor.execute("SELECT instructor_id FROM instructors WHERE instructor_email = %s", (instructor_email,))
            instructor = cursor.fetchone()
            
            if instructor:
                instructor_id = instructor[0]
            else:
                # Insert new instructor if not exists
                cursor.execute("INSERT INTO instructors (instructor_name, instructor_email) VALUES (%s, %s) RETURNING instructor_id",
                               (instructor_name, instructor_email))
                instructor_id = cursor.fetchone()[0]

            # Update or insert the course
            cursor.execute("""
                INSERT INTO courses (course_id, course_name, instructor_id, semester, active)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (course_id) 
                DO UPDATE SET 
                    course_name = EXCLUDED.course_name,
                    instructor_id = EXCLUDED.instructor_id,
                    semester = EXCLUDED.semester,
                    active = EXCLUDED.active
            """, (course_id, course_name, instructor_id, semester, active))

        conn.commit()
    except psycopg2.Error as e:
        app.logger.error(f"Database error: {str(e)}")
    finally:
        conn.close()

    return redirect(url_for('admin_portal'))




@app.route('/get_form/<course_id>')
def get_form(course_id):
    print(f"Rendering form for course ID: {course_id}")
    return render_template('course_form.html', course_id=course_id)

def create_tables_if_not_exists():
    """Create tables if they do not already exist and insert initial data."""
    create_tables_queries = [
        """
        CREATE TABLE IF NOT EXISTS instructors (
            instructor_id SERIAL PRIMARY KEY,
            instructor_name VARCHAR(255)  UNIQUE NOT NULL,
            instructor_email VARCHAR(255) UNIQUE NOT NULL
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS courses (
            course_id SERIAL PRIMARY KEY,
            course_name VARCHAR(255),
            instructor_id INT REFERENCES instructors(instructor_id),
            semester VARCHAR(50),
            active BOOLEAN DEFAULT TRUE,
            batch_pattern VARCHAR(10),
            UNIQUE (course_name, instructor_id, batch_pattern, semester)
        );
        """,
        """
        CREATE TABLE IF NOT EXISTS feedback (
            feedback_id SERIAL PRIMARY KEY,
            course_id INT REFERENCES courses(course_id),
            coursecode2 VARCHAR(50),
            studentemailid VARCHAR(100),
            studentname VARCHAR(100),
            dateOfFeedback DATE,
            week INT,
            instructorEmailID VARCHAR(100),
            question1Rating INT,
            question2Rating INT,
            remarks TEXT,
            active BOOLEAN DEFAULT TRUE
        );
        """
    ]

    # Insert data into instructors table
    insert_instructors_query = """
    INSERT INTO instructors (instructor_id, instructor_name, instructor_email)
    VALUES
    (3, 'Dr. Achal Agrawal', 'achal@sitare.org'),
    (4, 'Ms. Preeti Shukla', 'preeti@sitare.org'),
    (5, 'Dr. Amit Singhal', 'amit@sitare.org'),
    (1, 'Dr. Pintu Lohar', 'pintu@sitare.org'),
    (2, 'Dr. Prosenjit Gupta', 'prosenjit@sitare.org'),
    (9, 'Dr. Kushal Shah', 'kushal@sitare.org'),
    (14, 'Ms. Riya Bangera', 'riya@sitare.org'),
    (13, 'Mr. Saurabh Pandey', 'saurabh@sitare.org'),
    (11, 'Dr. Anuja Agrawal', 'anuja@sitare.org'),
    (10, 'Ms. Geeta', 'geeta@sitare.org'),
    (8, 'Dr. Mainak', 'mainakc@sitare.org'),
    (7, 'Jeet Sir', 'jeet.mukherjee@sitare.org'),
    (6, 'Dr. Ambar Jain', 'ambar@sitare.org'),
    (12, 'Dr. Shankho Pal', 'shankho@sitare.org'),
    (15, 'Dr. Abhinav Mishra', 'abhinav@sitare.org'),
    (16, 'Dr. Ramesh Subramonian', 'ramesh.subramonian@sitare.org'),
    (17, 'Dr. Aniket Prabhune', 'aniket.prabhune@sitare.org'),
    (18, 'Dr. Sumeet Agrawal', 'sumeet@sitare.org')
    ON CONFLICT (instructor_id) DO NOTHING;
    """

    # Insert data into courses table
    insert_courses_query = """
    INSERT INTO courses (course_name, instructor_id, batch_pattern, semester)
    VALUES
        ('Search Engine and Information Retrieval', 1, 'su-23', 'Spring 2025'),
        ('Mining Massive DataSets', 2, 'su-23', 'Spring 2025'),
        ('Computer Organisation & Systems', 9, 'su-23', 'Spring 2025'),
        ('Advanced Object Oriented Programming', 13, 'su-23', 'Spring 2025'),
        ('Book Club (SEM 4)', 4, 'su-23', 'Spring 2025'),
        ('Machine Learning', 9, 'su-23', 'Spring 2025'),
        ('Computer Networks', 16, 'su-22', 'Spring 2025'),
        ('Economics for CS', 5, 'su-22', 'Spring 2025'),
        ('Human Computer Interaction', 6, 'su-22', 'Spring 2025'),
        ('Communication and Ethics (SEM 2)', 4, 'su-24', 'Spring 2025'),
        ('Mathematical Foundation of Computing (MFC)', 9, 'su-24', 'Spring 2025'),
        ('Data Handling in Python (DHP)', 3, 'su-24', 'Spring 2025'),
        ('Data Structures & Algorithms', 13, 'su-24', 'Spring 2025'),
        ('Calculus', 15, 'su-24', 'Spring 2025'),
        ('Book Club & SEI (SEM 2)', 4, 'su-24', 'Spring 2025')
    ON CONFLICT (course_name, instructor_id, batch_pattern, semester) DO NOTHING;
    """

    conn = get_db_connection()
    if conn is None:
        print("Error: Database connection not established.")
        return

    try:
        with conn.cursor() as cursor:
            # Execute table creation queries
            for query in create_tables_queries:
                cursor.execute(query)

            # Insert initial data
            cursor.execute(insert_instructors_query)
            cursor.execute(insert_courses_query)

            conn.commit()
            print("Tables and initial data created successfully.")
    except psycopg2.Error as e:
        print("Error executing SQL commands:", str(e))
        conn.rollback()
    finally:
        conn.close()

# Call create_tables_if_not_exists() to set up the database
create_tables_if_not_exists()




@app.route('/submit_all_forms', methods=['POST'])
def submit_all_forms():
    # again checking the student has already submitted feedback for today
    conn = get_db_connection()
    cur = conn.cursor()
    current_datetime = datetime.now(timezone.utc)
    current_date = current_datetime.date()


    student_email_id = session.get('user_info', {}).get('email')
    cur.execute("SELECT * FROM feedback WHERE studentemailid = %s AND DateOfFeedback = %s", (student_email_id, current_date))
    feedback_submitted = cur.fetchone()
    
    if feedback_submitted:
        return jsonify({"status": "already_submitted"})

    instructor_emails = session.get('instructor_emails', {})
    data = request.form.to_dict(flat=False)
    print("Received form data:", data)  # Debugging line

    feedback_entries = {}
    date_of_feedback = datetime.now().date()
    student_email_id = session.get('user_info', {}).get('email')

    # Define the start date for the first week
    initial_start_date = datetime.strptime("2024-08-27", "%Y-%m-%d")

    # Create the week table
    week_table = [
        {
            "week_no": i + 1,
            "start_date": initial_start_date + timedelta(weeks=i),
            "end_date": (initial_start_date + timedelta(weeks=i)) + timedelta(days=6)
        }
        for i in range(60)
    ]

    # Get the current date
    current_date = datetime.now()

    # Determine the current week
    current_week_no = next(
        (week["week_no"] for week in week_table if week["start_date"] <= current_date <= week["end_date"]),
        None
    )

    for key, values in data.items():
        match = re.match(r'course_(\d+)\[(\w+)\]', key)
        if not match:
            print(f"Key '{key}' does not match expected format.")
            continue
        
        course_id = match.group(1)
        field = match.group(2)
        if field not in ['understanding', 'revision', 'suggestion']:
            print(f"Field '{field}' is not a recognized feedback field.")
            continue
        
        if course_id not in feedback_entries:
            feedback_entries[course_id] = {'understanding': None, 'revision': None, 'suggestion': None}

        feedback_entries[course_id][field] = values[0]
    
    print("Processed feedback entries:", feedback_entries)  # Debugging line
    
    prepared_feedback_entries = []
    for course_id, form_data in feedback_entries.items():
        understanding_rating = form_data.get('understanding')
        revision_rating = form_data.get('revision')
        # suggestion = form_data.get('suggestion')
        instructor = instructor_emails.get(course_id)
        StudentName = session.get('user_info', {}).get('name')  # Retrieve user's name
        print(f"Processing feedback for course {course_id}: {form_data}")

        if not understanding_rating or not revision_rating:
            print("Missing ratings. Returning error.")
            return jsonify({"status": "error", "message": "All questions must be rated."}), 400
        
        prepared_feedback_entries.append(
            (course_id, student_email_id, StudentName, date_of_feedback, current_week_no, instructor, understanding_rating, revision_rating, form_data.get('suggestion', 'None')  # Default to 'None' if empty
)
        )
    
    create_tables_if_not_exists()
    
    try:
        conn = get_db_connection()
        if conn:
            cursor = conn.cursor()
            insert_query = """
                INSERT INTO feedback (coursecode2, studentemailid, StudentName, DateOfFeedback, Week, instructorEmailID, Question1Rating, Question2Rating, Remarks)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.executemany(insert_query, prepared_feedback_entries)
            conn.commit()
            cursor.close()
            conn.close()
            print("Feedback data successfully inserted.")
            return jsonify({"status": "success"})
        else:
            print("Failed to insert feedback due to connection issue.")
            return jsonify({"status": "error", "message": "Database connection failed."}), 500
    except psycopg2.Error as e:
        error_details = f"Database error: {str(e)}"
        print(error_details)  # Debugging line
        return jsonify({"status": "error", "message": error_details}), 500
    except Exception as e:
        error_details = f"Error: {str(e)}"
        print(error_details)  # Debugging line
        return jsonify({"status": "error", "message": error_details}), 500

@app.route('/redirect_page')
def redirect_page():
    user_info = session.get('user_info')
    if not user_info:
        return redirect(url_for('login'))
    
    # Check if feedback has been submitted today
    student_email_id = user_info.get('email')
    current_date = datetime.now(timezone.utc).date()
    
    conn = get_db_connection()
    feedback_submitted = False
    
    if conn:
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM feedback WHERE studentemailid = %s AND DateOfFeedback = %s", (student_email_id, current_date))
            feedback_submitted = cursor.fetchone() is not None
            cursor.close()
        except psycopg2.Error as e:
            app.logger.error(f"Database error in redirect_page: {str(e)}")
        finally:
            conn.close()
    
    return render_template('redirect_page.html', feedback_submitted=feedback_submitted)
    
@app.errorhandler(Exception)
def handle_exception(e):
    # Log the error
    app.logger.error(f"Unhandled exception: {str(e)}")
    # Return a custom error page
    return render_template('error.html')

if __name__ == '__main__':
    get_db_connection()
    create_tables_if_not_exists()
    
    # Use the PORT from the environment or default to 5000
    port = int(os.environ.get('PORT', 5000))
    log_to_stderr(app)
    
    # Start the Flask application
    app.run(host='0.0.0.0', port=port)




