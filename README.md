# Sitare University Feedback System
Developer :- Puneet,Ajay <br>
Instructor :- Dr.Kushal Shah

This is a Flask-based web application designed to manage student feedback for courses at Sitare University. The system allows students to submit feedback, instructors to view feedback for their courses, and administrators to over all feedback.

## Table of Contents
- [Features](#features)
- [Technologies Used](#technologies-used)
- [Setup and Installation](#setup-and-installation)
- [Database Schema](#database-schema)
- [Email Scheduler Setup](#email-scheduler-setup)
- [Usage](#usage)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

## Features

- **User Authentication**: Utilizes Google OAuth for secure login.
- **Role-Based Access**: Different portals for students, teachers, and administrators.
- **Feedback Submission**: Students can submit weekly feedback for their courses.
- ** One time Submission**: Student can only submit feedback once.
- ** View Previous Submissions**: Student can always view their previous submission."
- **Feedback Analysis**: Teachers can view aggregated feedback and statistics.
- **Admin Overview**: Administrators can see feedback across all courses and instructors.
- **Automated Reminders**: Scheduled email reminders for feedback submission.

## Technologies Used

- Python 3.x
- Flask
- PostgreSQL
- HTML/CSS/JavaScript
- Google OAuth
- SMTP for email notifications

## Setup and Installation

1. Clone the repository:
   ```
   git clone https://github.com/your-username/sitare-feedback-system.git
   cd sitare-feedback-system
   ```

2. Set up a virtual environment:
   ```
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   ```

3. Install dependencies:
   ```
   pip install -r requirements.txt
   ```

4. Set up environment variables:
   Create a `.env` file in the root directory and add the following:
   ```
   SECRET_KEY=your_secret_key
   dbName=your_database_name
   user=your_database_user
   host=your_database_host
   DBPWD=your_database_password
   Client_id=your_google_oauth_client_id
   Client_secret=your_google_oauth_client_secret
   ```

5. Set up the PostgreSQL database and run the initial setup:
   ```
   python app.py
   ```

6. Run the application:
   ```
   flask run
   ```

## Database Schema

The application uses PostgreSQL. Below is the schema for the main tables:

### Instructors Table

```sql
CREATE TABLE instructors (
    instructor_id SERIAL PRIMARY KEY,
    instructor_name VARCHAR(255) UNIQUE NOT NULL,
    instructor_email VARCHAR(255) NOT NULL
);
```

### Courses Table

```sql
CREATE TABLE courses (
    course_id SERIAL PRIMARY KEY,
    course_name VARCHAR(255),
    instructor_id INT,
    batch_pattern VARCHAR(10),
    UNIQUE (course_name, instructor_id, batch_pattern)
);
```

### Feedback Table

```sql
CREATE TABLE feedback (
    feedback_id SERIAL PRIMARY KEY,
    course_id INT REFERENCES courses(course_id),
    coursecode2 VARCHAR(50),
    studentemaiid VARCHAR(100),
    studentname VARCHAR(100),
    dateOfFeedback DATE,
    week INT,
    instructorEmailID VARCHAR(100),
    question1Rating INT,
    question2Rating INT,
    remarks TEXT
);
```

### Table Relationships

- The `courses` table has a foreign key relationship with the `instructors` table through the `instructor_id` field.
- The `feedback` table has a foreign key relationship with the `courses` table through the `course_id` field.

### Initial Data Setup

The system includes initial data setup for instructors and courses:

#### Instructors Data

```python
insert_instructors_query = """
INSERT INTO instructors (instructor_id, instructor_name, instructor_email)
VALUES
(3, 'Dr. Achal Agrawal', 'achal@sitare.org'),
(4, 'Ms. Preeti Shukla', 'preeti@sitare.org'),
...
ON CONFLICT (instructor_id) DO NOTHING;
"""
```

#### Courses Data

```python
insert_courses_query = """
INSERT INTO courses (course_name, instructor_id, batch_pattern)
VALUES
('Artificial Intelligence', 1, 'su-230'),
('DBMS', 1, 'su-230'),
...
ON CONFLICT (course_name, instructor_id, batch_pattern) DO NOTHING;
"""
```

Tables are created and initial data is inserted when the application starts via the `create_tables_if_not_exists()` function.

## Email Scheduler Setup

The application includes a feature to send automated email reminders. This is implemented in the `send_email()` function and scheduled to run every Saturday at 6:00 AM. To set this up:

1. Use an app-specific password for the sender email account. This is more secure than using your main account password.

2. To generate an app-specific password (for Gmail):
   - Go to your Google Account settings
   - Navigate to Security > App passwords
   - Select "Mail" and "Other (Custom name)"
   - Generate and copy the app password

3. Update the `smtp_password` in the `send_email()` function:

```python
def send_email():
    # ... other code ...
    smtp_password = "your_app_specific_password_here"  # Replace with your app-specific password
    # ... rest of the function ...
```

4. Ensure the `schedule` library is installed:

```
pip install schedule
```

5. The email scheduling is set up at the end of the script:

```python
schedule.every().saturday.at("06:00").do(send_email)

while True:
    schedule.run_pending()
    time.sleep(60)  # Wait a minute before checking again
```

Note: Make sure to keep your app-specific password confidential and not commit it to version control. Consider using environment variables or a secure configuration file to store sensitive information.

## Usage

- Students: Log in with your Sitare email (su-*.sitare.org) to access the student portal and submit weekly feedback.
- Teachers: Log in with your Sitare email to view feedback for your courses.
- Administrators: Log in with the admin email to access the admin portal and view all feedback.

## Contributing

Contributions to improve the Sitare University Feedback System are welcome. Please follow these steps:

1. Fork the repository
2. Create a new branch (`git checkout -b feature-branch`)
3. Make your changes and commit them (`git commit -am 'Add some feature'`)
4. Push to the branch (`git push origin feature-branch`)
5. Create a new Pull Request

## License

[MIT License](https://opensource.org/licenses/MIT)

## Contact

For any queries or support, please contact [su-23003@sitare.org](mailto:su-23003@sitare.org).
