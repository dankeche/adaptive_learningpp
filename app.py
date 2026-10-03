import os
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-secret-key")

# ========== DATABASE ==========
DATABASE_URL = os.environ.get("DATABASE_URL")

def get_db_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL is not configured.")
    return psycopg2.connect(DATABASE_URL)

def create_tables():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Users table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id SERIAL PRIMARY KEY,
                    fullname VARCHAR(100) NOT NULL,
                    email VARCHAR(100) UNIQUE NOT NULL,
                    password VARCHAR(255) NOT NULL,
                    role VARCHAR(20) DEFAULT 'student',
                    current_class INT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Questions table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS questions (
                    question_id SERIAL PRIMARY KEY,
                    question_text TEXT NOT NULL,
                    option_a VARCHAR(255) NOT NULL,
                    option_b VARCHAR(255) NOT NULL,
                    option_c VARCHAR(255) NOT NULL,
                    option_d VARCHAR(255) NOT NULL,
                    correct_answer CHAR(1) NOT NULL,
                    topic VARCHAR(100),
                    class_level INT NOT NULL
                )
            ''')

            # Results table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS results (
                    result_id SERIAL PRIMARY KEY,
                    user_id INT REFERENCES users(user_id),
                    score DECIMAL(5,2),
                    total_questions INT,
                    level_assigned VARCHAR(50),
                    taken_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')

            # Feedback table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS feedback (
                    feedback_id SERIAL PRIMARY KEY,
                    result_id INT REFERENCES results(result_id),
                    message TEXT
                )
            ''')

        conn.commit()
        print("✅ Tables created successfully!")
    except Exception as e:
        conn.rollback()
        print("❌ Error creating tables:", e)
    finally:
        conn.close()

# ========== RULE-BASED AI FUNCTION (85% THRESHOLD) ==========
def evaluate_performance(score):
    if score >= 85:
        level = "Passed"
        feedback = "Excellent! You scored 85% or above. You have passed this class."
        passed = True
    else:
        level = "Not Passed"
        feedback = "You scored below 85%. Please revise and try this class again."
        passed = False
    return level, feedback, passed

# ========== HOME ==========
@app.route("/")
def index():
    return redirect(url_for("login"))

# ========== LOGIN ==========
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        conn = get_db_connection()
        try:
            with conn.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
                user = cursor.fetchone()
        finally:
            conn.close()

        if user and check_password_hash(user["password"], password):
            session["user_id"] = user["user_id"]
            session["fullname"] = user["fullname"]
            session["role"] = user["role"]
            flash(f"Welcome back, {user['fullname']}!", "success")
            if user["role"] == "admin":
                return redirect(url_for("admin_panel"))
            return redirect(url_for("dashboard"))
        flash("Invalid email or password", "danger")
    return render_template("login.html")

# ========== REGISTER ==========
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        fullname = request.form["fullname"]
        email = request.form["email"]
        password = request.form["password"]
        confirm = request.form["confirm_password"]

        if password != confirm:
            flash("Passwords do not match", "danger")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO users (fullname, email, password)
                    VALUES (%s, %s, %s)
                    """,
                    (fullname, email, hashed_password),
                )
            conn.commit()
            flash("Registration successful! Please login.", "success")
            return redirect(url_for("login"))
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            flash("Email already exists.", "danger")
        except Exception:
            conn.rollback()
            flash("An error occurred during registration.", "danger")
        finally:
            conn.close()
    return render_template("register.html")

# ========== STUDENT DASHBOARD ==========
@app.route("/dashboard")
def dashboard():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT current_class FROM users WHERE user_id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
            current_class = user["current_class"] if user else 1

            cursor.execute(
                """
                SELECT * FROM results
                WHERE user_id = %s
                ORDER BY taken_at DESC
                LIMIT 10
                """,
                (session["user_id"],),
            )
            results = cursor.fetchall()

            cursor.execute(
                """
                SELECT COUNT(*) AS total_quizzes,
                       AVG(score) AS average_score
                FROM results
                WHERE user_id = %s
                """,
                (session["user_id"],),
            )
            stats = cursor.fetchone()
    finally:
        conn.close()

    total_quizzes = int(stats["total_quizzes"] or 0)
    average_score = round(float(stats["average_score"]), 1) if stats["average_score"] is not None else 0
    latest_level = results[0]["level_assigned"] if results else "Not yet assessed"

    return render_template(
        "dashboard.html",
        fullname=session["fullname"],
        results=results,
        role=session.get("role"),
        total_quizzes=total_quizzes,
        average_score=average_score,
        latest_level=latest_level,
        current_class=current_class,
    )

# ========== TAKE QUIZ ==========
@app.route("/quiz")
def quiz():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT current_class FROM users WHERE user_id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
            current_class = user["current_class"] if user else 1

            cursor.execute(
                """
                SELECT * FROM questions
                WHERE class_level = %s
                ORDER BY RANDOM()
                LIMIT 20
                """,
                (current_class,),
            )
            questions = cursor.fetchall()
    finally:
        conn.close()

    if not questions:
        flash(
            f"No questions available for Class {current_class} yet. Please contact admin.",
            "danger",
        )
        return redirect(url_for("dashboard"))

    return render_template(
        "quiz.html", questions=questions, current_class=current_class
    )

# ========== SUBMIT QUIZ + RULE-BASED EVALUATION ==========
@app.route("/submit_quiz", methods=["POST"])
def submit_quiz():
    if "user_id" not in session:
        return redirect(url_for("login"))

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT current_class FROM users WHERE user_id = %s",
                (session["user_id"],),
            )
            user = cursor.fetchone()
            current_class = user["current_class"] if user else 1

            answered_ids = [
                key[1:] for key in request.form if key.startswith("q")
            ]
            if not answered_ids:
                flash("No answers submitted", "danger")
                return redirect(url_for("quiz"))

            question_ids = [int(qid) for qid in answered_ids]
            cursor.execute(
                """
                SELECT * FROM questions
                WHERE question_id = ANY(%s)
                """,
                (question_ids,),
            )
            questions = cursor.fetchall()

            score = 0
            total = len(questions)
            detailed_results = []

            for q in questions:
                qid = str(q["question_id"])
                user_answer = request.form.get(f"q{qid}", "").upper()
                correct_answer = q["correct_answer"].upper()
                is_correct = user_answer == correct_answer
                if is_correct:
                    score += 1

                detailed_results.append(
                    {
                        "question_text": q["question_text"],
                        "user_answer": user_answer,
                        "correct_answer": correct_answer,
                        "option_a": q["option_a"],
                        "option_b": q["option_b"],
                        "option_c": q["option_c"],
                        "option_d": q["option_d"],
                        "is_correct": is_correct,
                    }
                )

            percentage = round((score / total * 100), 2) if total > 0 else 0
            level, feedback_msg, passed = evaluate_performance(percentage)

            new_class = current_class
            if passed and current_class < 3:
                new_class = current_class + 1
                cursor.execute(
                    """
                    UPDATE users
                    SET current_class = %s
                    WHERE user_id = %s
                    """,
                    (new_class, session["user_id"]),
                )
                feedback_msg += f" Class {new_class} is now unlocked!"
            elif passed and current_class == 3:
                feedback_msg += " Congratulations! You have completed all classes."

            cursor.execute(
                """
                INSERT INTO results
                    (user_id, score, total_questions, level_assigned)
                VALUES (%s, %s, %s, %s)
                RETURNING result_id
                """,
                (
                    session["user_id"],
                    percentage,
                    total,
                    f"Class {current_class} - {level}",
                ),
            )
            result_id = cursor.fetchone()["result_id"]

            cursor.execute(
                """
                INSERT INTO feedback (result_id, message)
                VALUES (%s, %s)
                """,
                (result_id, feedback_msg),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    return render_template(
        "feedback.html",
        score=percentage,
        level=level,
        feedback=feedback_msg,
        correct=score,
        total=total,
        detailed_results=detailed_results,
        current_class=current_class,
        new_class=new_class,
        passed=passed,
    )

# ========== ADMIN: ADD QUESTION ==========
@app.route("/admin/add_question", methods=["GET", "POST"])
def add_question():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Admin access required", "danger")
        return redirect(url_for("login"))

    if request.method == "POST":
        conn = get_db_connection()
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO questions
                        (question_text, option_a, option_b, option_c, option_d,
                         correct_answer, topic, class_level)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        request.form["question_text"],
                        request.form["option_a"],
                        request.form["option_b"],
                        request.form["option_c"],
                        request.form["option_d"],
                        request.form["correct_answer"].upper(),
                        request.form["topic"],
                        int(request.form["class_level"]),
                    ),
                )
            conn.commit()
            flash("Question added successfully!", "success")
            return redirect(url_for("add_question"))
        except Exception:
            conn.rollback()
            flash("Unable to add question.", "danger")
        finally:
            conn.close()
    return render_template("add_question.html")

# ========== ADMIN PANEL ==========
@app.route("/admin")
def admin_panel():
    if "user_id" not in session or session.get("role") != "admin":
        flash("Admin access required", "danger")
        return redirect(url_for("login"))

    conn = get_db_connection()
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS total FROM users WHERE role = 'student'"
            )
            total_students = int(cursor.fetchone()["total"])

            cursor.execute("SELECT COUNT(*) AS total FROM questions")
            total_questions = int(cursor.fetchone()["total"])

            cursor.execute("SELECT COUNT(*) AS total FROM results")
            total_quizzes = int(cursor.fetchone()["total"])

            cursor.execute(
                """
                SELECT * FROM questions
                ORDER BY class_level, question_id DESC
                """
            )
            questions = cursor.fetchall()

            cursor.execute(
                """
                SELECT
                    u.user_id,
                    u.fullname,
                    u.email,
                    u.current_class,
                    COUNT(r.result_id) AS total_attempts,
                    ROUND(AVG(r.score)::numeric, 1) AS average_score
                FROM users u
                LEFT JOIN results r ON u.user_id = r.user_id
                WHERE u.role = 'student'
                GROUP BY u.user_id, u.fullname, u.email, u.current_class
                ORDER BY u.current_class DESC, total_attempts DESC
                """
            )
            students = cursor.fetchall()

            student_details = []
            for s in students:
                cursor.execute(
                    """
                    SELECT score, level_assigned
                    FROM results
                    WHERE user_id = %s
                    ORDER BY taken_at DESC
                    LIMIT 1
                    """,
                    (s["user_id"],),
                )
                latest = cursor.fetchone()

                cursor.execute(
                    """
                    SELECT score
                    FROM results
                    WHERE user_id = %s
                    ORDER BY taken_at ASC
                    LIMIT 1
                    """,
                    (s["user_id"],),
                )
                first = cursor.fetchone()

                improving = None
                if latest and first and s["total_attempts"] > 1:
                    if latest["score"] > first["score"]:
                        improving = "Yes ↑"
                    elif latest["score"] < first["score"]:
                        improving = "No ↓"
                    else:
                        improving = "Same"

                student_details.append(
                    {
                        "user_id": s["user_id"],
                        "fullname": s["fullname"],
                        "email": s["email"],
                        "current_class": s["current_class"],
                        "total_attempts": int(s["total_attempts"]),
                        "average_score": float(s["average_score"]) if s["average_score"] is not None else 0,
                        "latest_score": latest["score"] if latest else None,
                        "latest_level": latest["level_assigned"] if latest else None,
                        "improving": improving,
                    }
                )
    finally:
        conn.close()

    return render_template(
        "admin.html",
        fullname=session["fullname"],
        total_students=total_students,
        total_questions=total_questions,
        total_quizzes=total_quizzes,
        questions=questions,
        students=student_details,
    )

# ========== DELETE QUESTION ==========
@app.route("/admin/delete_question/<int:question_id>")
def delete_question(question_id):
    if "user_id" not in session or session.get("role") != "admin":
        flash("Admin access required", "danger")
        return redirect(url_for("login"))

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM questions WHERE question_id = %s",
                (question_id,),
            )
        conn.commit()
        flash("Question deleted successfully", "success")
    except Exception:
        conn.rollback()
        flash("Unable to delete question.", "danger")
    finally:
        conn.close()
    return redirect(url_for("admin_panel"))

# ========== TEMPORARY: CREATE ADMIN ==========
@app.route("/create-admin")
def create_admin():
    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            hashed_password = generate_password_hash("admin123")  # Change password later
            cursor.execute(
                """
                INSERT INTO users (fullname, email, password, role, current_class)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (email) DO NOTHING
                """,
                ("Admin User", "admin@gmail.com", hashed_password, "admin", 1)
            )
        conn.commit()
        return "✅ Admin created successfully!<br>Email: admin@gmail.com<br>Password: admin123"
    except Exception as e:
        conn.rollback()
        return f"❌ Error: {str(e)}"
    finally:
        conn.close()

# ========== TEMPORARY: IMPORT QUESTIONS ==========
@app.route("/import-questions")
def import_questions():
    if "user_id" not in session or session.get("role") != "admin":
        return "Admin access required. Please login as admin first."

    questions_data = [
        # Class 1
        ("What does Artificial Intelligence (AI) generally refer to?", "The physical construction of a computer", "The storage of files on a hard drive", "The ability of machines to perform tasks that normally require human intelligence", "The process of connecting computers to a network", "C", "Artificial Intelligence (Basics)", 1),
        ("Which of the following is an example of an AI application?", "A keyboard entering letters", "A recommendation system suggesting movies", "A word processor displaying text", "A calculator performing basic addition", "B", "Artificial Intelligence (Basics)", 1),
        ("What is an intelligent agent designed to do?", "Create electrical power", "Perceive its environment and take actions", "Only store information", "Replace computer hardware", "B", "Artificial Intelligence (Basics)", 1),
        ("Which AI field focuses on enabling computers to understand human language?", "Natural language processing", "Computer graphics", "Database management", "Computer networking", "A", "Artificial Intelligence (Basics)", 1),
        ("What is an expert system primarily designed to do?", "Provide solutions using stored expert knowledge and rules", "Replace all computer hardware", "Increase internet speed", "Format computer disks", "A", "Rule-Based AI / Expert Systems", 1),
        ("In a rule-based system, which statement is an example of an IF-THEN rule?", "Store the patient's name", "Display the login page", "Create a new database", "IF temperature is high THEN check for fever", "D", "Rule-Based AI / Expert Systems", 1),
        ("What is a knowledge base in an expert system?", "A collection of computer cables", "A list of internet addresses", "A collection of stored facts and rules", "A type of computer monitor", "C", "Rule-Based AI / Expert Systems", 1),
        ("What is the main purpose of an inference engine?", "To apply rules to known facts and derive conclusions", "To display web pages", "To store passwords as plain text", "To create HTML images", "A", "Rule-Based AI / Expert Systems", 1),
        ("What does adaptive learning attempt to do?", "Give every learner exactly the same content", "Remove all assessments", "Adjust learning experiences according to learner needs", "Prevent students from receiving feedback", "C", "Adaptive Learning Concepts", 1),
        ("Which information can an adaptive learning system use to adjust difficulty?", "Screen size", "Student performance", "Computer brand", "Printer type", "B", "Adaptive Learning Concepts", 1),
        ("What is personalized learning?", "Learning without teachers", "Learning only through printed books", "Learning that is adjusted to the needs or characteristics of an individual learner", "Learning without assessment", "C", "Adaptive Learning Concepts", 1),
        ("Why is progress tracking useful in adaptive learning?", "It removes learning objectives", "It helps the system understand learner development", "It replaces all course materials", "It prevents students from studying", "B", "Adaptive Learning Concepts", 1),
        ("What is machine learning?", "A method where computers learn patterns from data", "A method for repairing keyboards", "A system for printing documents", "A type of computer cable", "A", "Machine Learning (Basic Differences)", 1),
        ("Which type of machine learning uses labeled examples during training?", "Supervised learning", "Manual learning", "Unsupervised learning", "Random learning", "A", "Machine Learning (Basic Differences)", 1),
        ("What is clustering commonly associated with?", "Password hashing", "Supervised learning", "HTML styling", "Unsupervised learning", "D", "Machine Learning (Basic Differences)", 1),
        ("What is a label in a supervised learning dataset?", "The computer's operating system", "The name of a database table", "The size of a web page", "The target value associated with an example", "D", "Machine Learning (Basic Differences)", 1),
        ("What is the main purpose of HTML?", "To structure content on web pages", "To style web pages", "To store database records", "To encrypt passwords", "A", "Web Development (HTML, CSS, Flask)", 1),
        ("What does CSS primarily control?", "User passwords", "Database records", "The presentation and styling of web pages", "Machine learning models", "C", "Web Development (HTML, CSS, Flask)", 1),
        ("What is Flask?", "A Python web framework", "A CSS selector", "A database engine", "An HTML element", "A", "Web Development (HTML, CSS, Flask)", 1),
        ("What is a database table used to organize?", "Web browser history", "Only computer images", "CSS selectors", "Rows and columns of related data", "D", "Database (MySQL & SQL)", 1),
        ("Which SQL command is commonly used to retrieve data?", "FETCHALL", "SELECT", "SHOWDATA", "REMOVE", "B", "Database (MySQL & SQL)", 1),
        ("What is a primary key?", "A password used to access a computer", "A column that always contains images", "A field that uniquely identifies records in a table", "A type of SQL comment", "C", "Database (MySQL & SQL)", 1),
        ("Which SQL command adds new records to a table?", "ORDER", "UPDATE", "SELECT", "INSERT", "D", "Database (MySQL & SQL)", 1),
        ("What is instant feedback in an assessment system?", "Feedback provided before a question is answered", "Feedback that is never shown to learners", "Feedback given only at the end of a school year", "Feedback provided immediately after a learner response", "D", "Instant Feedback & Assessment", 1),
        ("Which assessment is commonly used during learning to monitor progress?", "Entrance assessment only", "Final certification", "Formative assessment", "Summative assessment", "C", "Instant Feedback & Assessment", 1),
        ("What can automated assessment systems do?", "Remove all learning objectives", "Prevent students from answering questions", "Automatically evaluate certain learner responses", "Replace every teacher", "C", "Instant Feedback & Assessment", 1),
        ("Why can explanations improve feedback?", "They remove the need for questions", "They can help learners understand why an answer is correct or incorrect", "They make questions impossible to answer", "They prevent performance tracking", "B", "Instant Feedback & Assessment", 1),
        ("Why should passwords generally not be stored as plain text?", "Plain text prevents users from logging in", "Plain-text storage exposes the original passwords if the database is accessed", "Plain text automatically creates strong encryption", "Plain text makes passwords impossible to remember", "B", "Basic Security (Password Hashing)", 1),
        ("What is password hashing?", "Saving a password in a spreadsheet", "Sending a password through email", "Changing a password into a username", "Converting a password into a fixed-format hash value using a hashing function", "D", "Basic Security (Password Hashing)", 1),
        ("What is a salt in password security?", "A database table", "A type of firewall", "A user's username", "Additional random data used with a password before hashing", "D", "Basic Security (Password Hashing)", 1),

        # Class 2
        ("An AI system receives information from its surroundings and selects an action. Which concept best describes this process?", "CSS inheritance", "Database normalization", "Intelligent-agent behavior", "Password salting", "C", "Artificial Intelligence (Basics)", 2),
        ("A hospital wants software that can interpret medical images to identify possible abnormalities. Which AI area is most directly relevant?", "Web styling", "Natural language processing", "Computer vision", "Database indexing", "C", "Artificial Intelligence (Basics)", 2),
        ("Why is knowledge representation important in AI?", "It provides ways to represent information so an AI system can reason with it", "It determines the physical size of a computer", "It prevents computers from storing information", "It replaces all training data", "A", "Artificial Intelligence (Basics)", 2),
        ("An expert system contains the fact 'temperature = high' and the rule 'IF temperature is high THEN fever = likely'. What conclusion can the inference engine derive?", "The rule is deleted", "Fever is likely", "Temperature is low", "No fact can be used", "B", "Rule-Based AI / Expert Systems", 2),
        ("An expert system must determine whether a patient may have a condition by starting from a possible diagnosis and checking supporting facts. Which reasoning approach fits this situation?", "Data normalization", "Random search", "Forward chaining", "Backward chaining", "D", "Rule-Based AI / Expert Systems", 2),
        ("Why can a rule-based expert system become difficult to maintain as rules increase?", "Expert systems cannot store facts", "Many interacting rules can make the knowledge base complex to update and manage", "Rules cannot contain conditions", "The inference engine cannot use rules", "B", "Rule-Based AI / Expert Systems", 2),
        ("A student repeatedly answers introductory questions correctly but struggles with advanced questions. How should an adaptive system respond?", "Disable progress tracking", "Provide more suitable intermediate practice before advancing", "Increase difficulty immediately to the highest level", "Keep all questions at the same difficulty", "B", "Adaptive Learning Concepts", 2),
        ("Which learner information would be most useful for creating a student model?", "Printer speed", "Monitor brand", "Keyboard layout", "Recent performance and learning progress", "D", "Adaptive Learning Concepts", 2),
        ("Why might adaptive learning reduce unnecessary repetition?", "It gives every learner identical content", "It removes all assessments", "It can use performance data to identify concepts the learner has already demonstrated", "It prevents learners from reviewing material", "C", "Adaptive Learning Concepts", 2),
        ("A model is trained using examples where each image is labeled 'cat' or 'dog'. What type of learning is being used?", "Unsupervised learning", "Supervised learning", "Clustering without labels", "Reinforcement learning", "B", "Machine Learning (Basic Differences)", 2),
        ("A dataset contains student study hours and examination scores. Predicting the numerical examination score is an example of which task?", "Classification", "Regression", "Clustering", "Association only", "B", "Machine Learning (Basic Differences)", 2),
        ("Why is a test dataset normally kept separate from training data?", "To evaluate how well the trained model performs on unseen examples", "To remove all features", "To prevent the model from learning anything", "To increase the number of labels in the training set", "A", "Machine Learning (Basic Differences)", 2),
        ("A Flask application receives information submitted by an HTML form. Which HTTP method is commonly used when the form sends data to the server?", "HEAD", "GET", "TRACE", "POST", "D", "Web Development (HTML, CSS, Flask)", 2),
        ("A table named Students has columns id, name, and score. Which SQL query retrieves only students with scores above 70?", "SELECT * FROM Students WHERE score > 70;", "SELECT Students WHERE score > 70;", "GET * FROM Students IF score > 70;", "SELECT score > 70 FROM Students;", "A", "Database (MySQL & SQL)", 2),
        ("Two tables contain related student and course records. Which SQL operation is commonly used to combine matching records from the tables?", "ORDER BY", "DELETE", "JOIN", "INSERT", "C", "Database (MySQL & SQL)", 2),
        ("A database has a student_id column that uniquely identifies each student. Which constraint is most suitable for that column?", "ORDER BY", "GROUP BY", "PRIMARY KEY", "FOREIGN KEY", "C", "Database (MySQL & SQL)", 2),
        ("A quiz system immediately tells a learner that an answer is wrong and provides an explanation. What is the main instructional benefit?", "The learner no longer needs to study", "The system guarantees mastery", "The system removes the need for assessment", "The learner can identify and correct a misunderstanding while the task is still recent", "D", "Instant Feedback & Assessment", 2),
        ("Why can instant feedback support formative assessment?", "It provides information that can guide improvement during the learning process", "It prevents teachers from reviewing performance", "It only measures final achievement", "It eliminates learning objectives", "A", "Instant Feedback & Assessment", 2),
        ("An adaptive quiz uses previous answers to select the next question. What assessment feature is being demonstrated?", "Password encryption", "Assessment personalization", "Database normalization", "Static page rendering", "B", "Instant Feedback & Assessment", 2),
        ("A website stores user passwords in a database. Which approach is appropriate?", "Store the password in a public HTML page", "Store the password in a CSS file", "Store a password hash produced by an appropriate password-hashing method", "Store the original password so it can be displayed later", "C", "Basic Security (Password Hashing)", 2),

        # Class 3
        ("A delivery company wants an AI system to decide which route to take based on current road conditions and its objective of reaching a destination efficiently. Which AI concept is most relevant?", "Password salting", "Intelligent-agent decision making", "Database normalization", "HTML parsing", "B", "Artificial Intelligence (Basics)", 3),
        ("An AI image classifier performs well on clear images but frequently fails when images contain shadows and poor lighting. Which factor should be investigated first?", "The database primary key", "The quality and representativeness of the training data", "The HTML page title", "The password salt length only", "B", "Artificial Intelligence (Basics)", 3),
        ("An AI application must process spoken questions and convert them into meaningful language for further processing. Which component is most directly relevant?", "Computer vision", "CSS", "SQL JOIN", "Natural language processing", "D", "Artificial Intelligence (Basics)", 3),
        ("Consider the rules: 'IF fever THEN infection_possible' and 'IF infection_possible AND cough THEN respiratory_condition'. If the facts are fever and cough, what can forward chaining derive?", "respiratory_condition", "Only cough", "Only fever", "No conclusion because there is no rule", "A", "Rule-Based AI / Expert Systems", 3),
        ("An expert system starts with the hypothesis 'respiratory_condition' and searches backward for rules that could establish it. Which reasoning method is being used?", "Forward chaining", "Regression", "Clustering", "Backward chaining", "D", "Rule-Based AI / Expert Systems", 3),
        ("A rule-based diagnostic system gives no useful result for a new case because none of its rules cover the situation. What does this illustrate?", "Automatic adaptation to unseen cases", "Dependence on predefined knowledge and rules", "Unsupervised learning", "Guaranteed generalization", "B", "Rule-Based AI / Expert Systems", 3),
        ("An adaptive platform observes that a learner answers advanced questions correctly but repeatedly misses questions on one prerequisite concept. What adjustment is most consistent with adaptive learning?", "Ignore the weak concept because advanced questions were answered correctly", "Delete the learner's previous results", "Provide targeted practice on the weak prerequisite while preserving progress in mastered areas", "Lower every subject to the easiest level", "C", "Adaptive Learning Concepts", 3),
        ("A learner's accuracy rises from 55% to 90% after targeted practice. Which adaptation would be most defensible if the system uses performance thresholds?", "Keep difficulty permanently unchanged", "Immediately remove all assessments", "Increase difficulty gradually while continuing to monitor performance", "Reset the learner to beginner level", "C", "Adaptive Learning Concepts", 3),
        ("An adaptive system recommends different learning sequences to two students based on their performance histories. What concept best explains this behavior?", "Password verification", "Static instruction", "Database deletion", "Student modeling and personalized learning paths", "D", "Adaptive Learning Concepts", 3),
        ("A dataset contains 10,000 labeled examples, but the model is evaluated using the same examples on which it was trained. What problem can this evaluation create?", "It converts classification into regression", "It may give an overly optimistic estimate of performance on unseen data", "It prevents the model from learning", "It guarantees that the model is unbiased", "B", "Machine Learning (Basic Differences)", 3),
        ("A model predicts whether an email is spam or not spam. Which evaluation task type is this?", "Dimensional indexing", "Classification", "Clustering", "Regression", "B", "Machine Learning (Basic Differences)", 3),
        ("A model predicts a house's selling price from features such as location and floor area. Which output type makes this a regression problem?", "An unlabeled cluster ID", "A password hash", "A continuous numerical value", "One of two class labels only", "C", "Machine Learning (Basic Differences)", 3),
        ("A Flask route is defined as @app.route('/profile/<username>'). What does <username> allow the route to receive?", "A database primary key automatically", "A CSS property", "A variable URL component that can be passed to the route function", "A password hash", "C", "Web Development (HTML, CSS, Flask)", 3),
        ("A Flask view passes a variable named score to a Jinja template. Which expression is normally used to display that variable?", "{{ score }}", "[[ score ]]", "(( score ))", "{% score %}", "A", "Web Development (HTML, CSS, Flask)", 3),
        ("Suppose a Students table contains id, name, and score. Which query returns the names of students whose score is at least 70, ordered from highest to lowest score?", "SELECT name FROM Students WHERE score >= 70 ORDER BY score DESC;", "SELECT Students WHERE score >= 70 ORDER name DESC;", "SELECT name FROM Students ORDER score >= 70 BY DESC;", "SELECT name FROM Students GROUP score >= 70;", "A", "Database (MySQL & SQL)", 3),
        ("Suppose Orders has customer_id and Customers has id. Which query is appropriate for returning each order together with the matching customer name?", "SELECT * FROM Orders WHERE Customers.id;", "SELECT Customers FROM Orders USING score;", "SELECT * FROM Orders JOIN Customers ON Orders.customer_id = Customers.id;", "JOIN Orders TO Customers WHERE customer_id;", "C", "Database (MySQL & SQL)", 3),
        ("A database query uses GROUP BY department to calculate the average score for each department. Why is GROUP BY appropriate?", "It organizes rows into groups so aggregate calculations can be performed per group", "It deletes duplicate departments", "It sorts every individual row alphabetically", "It creates a foreign key automatically", "A", "Database (MySQL & SQL)", 3),
        ("A quiz system marks an answer incorrect and immediately provides an explanation tailored to the concept the learner missed. Which feature goes beyond simply reporting a score?", "Database indexing", "Password salting", "Static assessment only", "Explanatory and personalized feedback", "D", "Instant Feedback & Assessment", 3),
        ("An assessment platform records repeated quiz attempts and uses the results to identify topics where a learner needs additional practice. What is this an example of?", "Password verification", "Summative assessment without data", "Performance tracking supporting personalized assessment", "HTML rendering", "C", "Instant Feedback & Assessment", 3),
        ("A learner answers a question incorrectly because of a misconception. Which feedback design is most likely to support learning?", "Restart the entire course without explanation", "Explain the relevant concept and indicate why the selected answer is incorrect", "Only display a red symbol with no information", "Hide the correct answer permanently", "B", "Instant Feedback & Assessment", 3),
    ]

    conn = get_db_connection()
    try:
        with conn.cursor() as cursor:
            # Clear existing questions first (optional)
            cursor.execute("DELETE FROM questions")
            
            for q in questions_data:
                cursor.execute(
                    """
                    INSERT INTO questions 
                    (question_text, option_a, option_b, option_c, option_d, correct_answer, topic, class_level)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    q
                )
        conn.commit()
        return f"✅ Successfully imported {len(questions_data)} questions!"
    except Exception as e:
        conn.rollback()
        return f"❌ Error: {str(e)}"
    finally:
        conn.close()

# ========== LOGOUT ==========
@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("login"))

# ========== HEALTH CHECK ==========
@app.route("/health")
def health():
    try:
        conn = get_db_connection()
        conn.close()
        return "OK", 200
    except Exception:
        return "Database connection failed", 500

# ========== CREATE TABLES ON STARTUP ==========
with app.app_context():
    create_tables()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
