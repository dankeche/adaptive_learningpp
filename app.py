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
