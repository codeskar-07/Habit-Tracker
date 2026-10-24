from datetime import datetime, timedelta, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash

db = SQLAlchemy()


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(30), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    habits = db.relationship("Habit", backref="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Habit(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow)
    logs = db.relationship("HabitLog", backref="habit", cascade="all, delete-orphan")

    def stats(self, today):
        """Return (current_streak, longest_streak, last_7_days, done_today)."""
        days = {log.log_date for log in self.logs}

        # Current streak: counts back from today (or yesterday if today isn't done yet)
        current = 0
        d = today if today in days else today - timedelta(days=1)
        while d in days:
            current += 1
            d -= timedelta(days=1)

        longest = run = 0
        prev = None
        for d in sorted(days):
            run = run + 1 if prev and d - prev == timedelta(days=1) else 1
            longest = max(longest, run)
            prev = d

        week = []
        for i in range(6, -1, -1):
            d = today - timedelta(days=i)
            week.append({"label": d.strftime("%a")[:2], "done": d in days, "today": d == today})

        return current, longest, week, today in days


class HabitLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    habit_id = db.Column(db.Integer, db.ForeignKey("habit.id"), nullable=False, index=True)
    log_date = db.Column(db.Date, nullable=False)
    __table_args__ = (db.UniqueConstraint("habit_id", "log_date", name="uq_habit_day"),)