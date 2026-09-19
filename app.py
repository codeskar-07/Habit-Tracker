from flask import Flask, render_template, redirect, url_for, request, flash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import date, timedelta
from models import db, User, Habit, HabitLog

app = Flask(__name__)
app.config['SECRET_KEY'] = 'dev-secret-key-123'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'

db.init_app(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def calculate_streak(habit_id):
    logs = HabitLog.query.filter_by(habit_id=habit_id, status=True)\
                         .order_by(HabitLog.log_date.desc()).all()
    if not logs:
        return 0

    streak = 0
    today = date.today()
    check_date = today
    logged_dates = {log.log_date for log in logs}

    if today not in logged_dates:
        check_date = today - timedelta(days=1)
        if check_date not in logged_dates:
            return 0

    while check_date in logged_dates:
        streak += 1
        check_date -= timedelta(days=1)

    return streak

@app.route('/')
@login_required
def dashboard():
    habits = Habit.query.filter_by(user_id=current_user.id).all()
    today = date.today()
    habit_data = []

    for habit in habits:
        today_log = HabitLog.query.filter_by(habit_id=habit.id, log_date=today).first()
        is_completed = today_log.status if today_log else False
        streak = calculate_streak(habit.id)
        
        habit_data.append({
            'habit': habit,
            'completed_today': is_completed,
            'streak': streak
        })

    return render_template('dashboard.html', habits=habit_data, today=today)

@app.route('/add-habit', methods=['POST'])
@login_required
def add_habit():
    title = request.form.get('title')
    description = request.form.get('description')
    if title:
        new_habit = Habit(title=title, description=description, user_id=current_user.id)
        db.session.add(new_habit)
        db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/toggle-habit/<int:habit_id>', methods=['POST'])
@login_required
def toggle_habit(habit_id):
    today = date.today()
    log = HabitLog.query.filter_by(habit_id=habit_id, log_date=today).first()

    if log:
        log.status = not log.status
    else:
        log = HabitLog(habit_id=habit_id, log_date=today, status=True)
        db.session.add(log)

    db.session.commit()
    return redirect(url_for('dashboard'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password')

    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        if User.query.filter_by(username=username).first():
            flash('Username already exists')
            return redirect(url_for('register'))

        hashed_pw = generate_password_hash(password, method='scrypt')
        new_user = User(username=username, password_hash=hashed_pw)
        db.session.add(new_user)
        db.session.commit()

        login_user(new_user)
        return redirect(url_for('dashboard'))

    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True)