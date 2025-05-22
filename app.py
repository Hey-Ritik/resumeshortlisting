from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)
app.secret_key = "admin@123"

# Database configuration
db_config = {
    'host': 'localhost',
    'user': 'root',
    'password': '8085683002',
    'database': 'ResumeShortlisting'
}

# Flask-Login Setup
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

class User(UserMixin):
    def __init__(self, id, username, password):
        self.id = id
        self.username = username
        self.password = password

    @staticmethod
    def get(user_id):
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM User WHERE id = %s", (user_id,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user:
            return User(user["id"], user["username"], user["password"])
        return None

    @staticmethod
    def get_by_username(username):
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM User WHERE username = %s", (username,))
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        if user:
            return User(user["id"], user["username"], user["password"])
        return None

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

@app.route('/')
@login_required
def home():
    return render_template("index.html", name=current_user.username)

@app.route('/login', methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.get_by_username(username)
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('home'))
        flash("Invalid username or password!")
        return redirect(url_for('login'))
    return render_template("login.html")

@app.route('/register', methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        password = generate_password_hash(request.form["password"])
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        try:
            cursor.execute("INSERT INTO User (username, password) VALUES (%s, %s)", (username, password))
            conn.commit()
            flash("Registered successfully! Now log in.")
            return redirect(url_for("login"))
        except Exception as e:
            flash("Username already exists.")
            return redirect(url_for("register"))
        finally:
            cursor.close()
            conn.close()
    return render_template("register.html")

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for("login"))

def recalculate_score_for_candidate(conn, cid):
    cursor = conn.cursor(dictionary=True)

    cursor.execute("SELECT * FROM Candidate WHERE candidate_id = %s", (cid,))
    candidate = cursor.fetchone()

    cursor.execute("SELECT * FROM Skills WHERE candidate_id = %s", (cid,))
    skills = cursor.fetchall()

    cursor.execute("SELECT * FROM Certifications WHERE candidate_id = %s", (cid,))
    certs = cursor.fetchall()

    cursor.execute("SELECT * FROM RankingWeights LIMIT 1")
    weights = cursor.fetchone()

    exp_score = min(candidate['experience'], 10) / 10.0
    edu_score_map = {'PhD': 1.0, 'Master': 0.8, 'Bachelor': 0.6, 'Diploma': 0.4, 'Other': 0.2}
    edu_score = edu_score_map.get(candidate['education_level'], 0.2)

    skill_score = (sum(skill['proficiency_level'] for skill in skills) / len(skills) / 10.0) if skills else 0.0
    cert_score = (min(sum(cert['validity_years'] for cert in certs), 10) / 10.0) if certs else 0.0

    total = (exp_score * weights['experience_weight'] +
             edu_score * weights['education_weight'] +
             skill_score * weights['skill_weight'] +
             cert_score * weights['certification_weight'])

    cursor.execute("UPDATE Candidate SET total_score = %s WHERE candidate_id = %s", (total, cid))
    conn.commit()
    cursor.close()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/add')
def add_page():
    return render_template('add.html')

@app.route('/delete')
def delete_page():
    return render_template('delete.html')

@app.route('/display')
def display_page():
    return render_template('display.html')

@app.route('/sort')
def sort_page():
    return render_template('sort.html')

@app.route('/search_page')
def search_page():
    return render_template('search.html')

@app.route('/api/candidates', methods=['GET'])
def get_all_candidates():
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT c.*, 
                GROUP_CONCAT(DISTINCT CONCAT(s.skill_name, ' (', s.proficiency_level, ')')) AS skills,
                GROUP_CONCAT(DISTINCT CONCAT(cert.certification_name, ' - ', cert.issuing_organization, ' (', cert.validity_years, ' yrs)')) AS certifications
            FROM Candidate c
            LEFT JOIN Skills s ON c.candidate_id = s.candidate_id
            LEFT JOIN Certifications cert ON c.candidate_id = cert.candidate_id
            GROUP BY c.candidate_id
        """
        cursor.execute(query)
        return jsonify(cursor.fetchall())
    except Exception as e:
        return jsonify({'error': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/api/candidates/sorted', methods=['GET'])
def get_sorted_candidates():
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM Candidate ORDER BY total_score DESC")
        return jsonify(cursor.fetchall())
    except Exception as e:
        return jsonify({'error': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/candidates', methods=['POST'])
def add_candidate():
    data = request.json
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()

        cursor.execute("""
            INSERT INTO Candidate (name, email, phone, experience, education_level)
            VALUES (%s, %s, %s, %s, %s)
        """, (data['name'], data['email'], data['phone'], data['experience'], data['education_level']))
        candidate_id = cursor.lastrowid

        for skill in data.get('skills', []):
            cursor.execute("""
                INSERT INTO Skills (candidate_id, skill_name, proficiency_level)
                VALUES (%s, %s, %s)
            """, (candidate_id, skill['skill_name'], skill['proficiency_level']))

        for cert in data.get('certifications', []):
            cursor.execute("""
                INSERT INTO Certifications (candidate_id, certification_name, issuing_organization, validity_years)
                VALUES (%s, %s, %s, %s)
            """, (candidate_id, cert['certification_name'], cert['issuing_organization'], cert['validity_years']))

        conn.commit()
        recalculate_score_for_candidate(conn, candidate_id)

        return jsonify({'message': 'Candidate added successfully'}), 201
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/delete', methods=['POST'])
def delete_candidate():
    data = request.get_json()
    candidate_id = data.get('candidate_id')

    if not candidate_id:
        return jsonify({'error': 'Candidate ID is required'}), 400

    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM Candidate WHERE candidate_id = %s", (candidate_id,))
        conn.commit()

        if cursor.rowcount == 0:
            return jsonify({'message': f'No candidate found with ID {candidate_id}'}), 404
        else:
            return jsonify({'message': f'Candidate with ID {candidate_id} deleted successfully'}), 200
    except Exception as e:
        if conn:
            conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/search', methods=['GET'])
def search_candidates():
    skill = request.args.get('skill')
    min_experience = request.args.get('experience', 0, type=int)

    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)
        query = """
            SELECT DISTINCT c.*
            FROM Candidate c
            JOIN Skills s ON c.candidate_id = s.candidate_id
            WHERE s.skill_name LIKE %s AND c.experience >= %s
        """
        cursor.execute(query, ('%' + skill + '%', min_experience))
        return jsonify(cursor.fetchall())
    except Exception as e:
        return jsonify({'error': str(e)})
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

@app.route('/recalculate_scores', methods=['POST'])
def recalculate_scores():
    conn = None
    cursor = None
    try:
        conn = mysql.connector.connect(**db_config)
        cursor = conn.cursor(dictionary=True)

        cursor.execute("SELECT * FROM Candidate")
        candidates = cursor.fetchall()

        for candidate in candidates:
            recalculate_score_for_candidate(conn, candidate['candidate_id'])

        return jsonify({'message': 'Scores recalculated successfully'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if cursor:
            cursor.close()
        if conn and conn.is_connected():
            conn.close()

if __name__ == '__main__':
    app.run(debug=True)