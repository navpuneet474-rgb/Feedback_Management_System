-- =============================================================
--  Sitare University — Feedback Portal
--  Database Setup & Seed Data
--  Run once: psql -d your_db_name -f seed.sql
-- =============================================================

-- ─── Tables ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS instructors (
    instructor_id   SERIAL PRIMARY KEY,
    instructor_name  VARCHAR(255) UNIQUE NOT NULL,
    instructor_email VARCHAR(255) UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS courses (
    course_id     SERIAL PRIMARY KEY,
    course_name   VARCHAR(255),
    instructor_id INT REFERENCES instructors(instructor_id),
    semester      VARCHAR(50),
    active        BOOLEAN DEFAULT TRUE,
    batch_pattern VARCHAR(10),
    UNIQUE (course_name, instructor_id, batch_pattern, semester)
);

CREATE TABLE IF NOT EXISTS feedback (
    feedback_id       SERIAL PRIMARY KEY,
    course_id         INT REFERENCES courses(course_id),
    coursecode2       VARCHAR(50),
    studentemailid    VARCHAR(100),
    studentname       VARCHAR(100),
    dateOfFeedback    DATE,
    week              INT,
    instructorEmailID VARCHAR(100),
    question1Rating   INT,
    question2Rating   INT,
    remarks           TEXT,
    active            BOOLEAN DEFAULT TRUE
);

-- ─── Instructors ──────────────────────────────────────────────

INSERT INTO instructors (instructor_id, instructor_name, instructor_email) VALUES
(1,  'Dr. Pintu Lohar',         'pintu@sitare.org'),
(2,  'Dr. Prosenjit Gupta',     'prosenjit@sitare.org'),
(3,  'Dr. Achal Agrawal',       'achal@sitare.org'),
(4,  'Ms. Preeti Shukla',       'preeti@sitare.org'),
(5,  'Dr. Amit Singhal',        'amit@sitare.org'),
(6,  'Dr. Ambar Jain',          'ambar@sitare.org'),
(7,  'Mr. Jeet Mukherjee',      'jeet.mukherjee@sitare.org'),
(8,  'Dr. Mainak Chatterjee',   'mainakc@sitare.org'),
(9,  'Dr. Kushal Shah',         'kushal@sitare.org'),
(10, 'Ms. Geeta',               'geeta@sitare.org'),
(11, 'Dr. Anuja Agrawal',       'anuja@sitare.org'),
(12, 'Dr. Shankho Pal',         'shankho@sitare.org'),
(13, 'Mr. Saurabh Pandey',      'saurabh@sitare.org'),
(14, 'Ms. Riya Bangera',        'riya@sitare.org'),
(15, 'Dr. Abhinav Mishra',      'abhinav@sitare.org'),
(16, 'Dr. Ramesh Subramonian',  'ramesh.subramonian@sitare.org'),
(17, 'Dr. Aniket Prabhune',     'aniket.prabhune@sitare.org'),
(18, 'Dr. Sumeet Agrawal',      'sumeet@sitare.org')
ON CONFLICT (instructor_id) DO NOTHING;

-- ─── Courses ──────────────────────────────────────────────────

INSERT INTO courses (course_name, instructor_id, batch_pattern, semester) VALUES
-- Batch su-23
('Search Engine and Information Retrieval', 1,  'su-23', 'Spring 2025'),
('Mining Massive DataSets',                 2,  'su-23', 'Spring 2025'),
('Computer Organisation & Systems',         9,  'su-23', 'Spring 2025'),
('Advanced Object Oriented Programming',    13, 'su-23', 'Spring 2025'),
('Book Club (SEM 4)',                        4,  'su-23', 'Spring 2025'),
('Machine Learning',                        9,  'su-23', 'Spring 2025'),
-- Batch su-22
('Computer Networks',                       16, 'su-22', 'Spring 2025'),
('Economics for CS',                        5,  'su-22', 'Spring 2025'),
('Human Computer Interaction',              6,  'su-22', 'Spring 2025'),
-- Batch su-24
('Communication and Ethics (SEM 2)',        4,  'su-24', 'Spring 2025'),
('Mathematical Foundation of Computing',    9,  'su-24', 'Spring 2025'),
('Data Handling in Python (DHP)',           3,  'su-24', 'Spring 2025'),
('Data Structures & Algorithms',            13, 'su-24', 'Spring 2025'),
('Calculus',                                15, 'su-24', 'Spring 2025'),
('Book Club & SEI (SEM 2)',                 4,  'su-24', 'Spring 2025')
ON CONFLICT (course_name, instructor_id, batch_pattern, semester) DO NOTHING;