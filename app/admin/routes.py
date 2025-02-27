from flask import Blueprint, request, render_template, redirect, url_for, flash, current_app, session, jsonify
from app import db, mail
from app.models.hr import HR
from app.models.company import Company
from app.models.interview import Interview
from app.models.interview_parameter import InterviewParameter
from app.models.admin import Admin
from app.models.session import Session
from app.models.review_question import ReviewQuestion
from flask_mail import Message
from datetime import datetime
from app.decorators import admin_required
from sqlalchemy import func
from helpers import get_url
from flask_jwt_extended import jwt_required, get_jwt_identity, set_access_cookies


admin = Blueprint('admin', __name__)

@admin.route('/home', methods=['GET'])
@jwt_required()
def home():
    admin_identity = get_jwt_identity()
    
    if not admin_identity or 'admin_id' not in admin_identity:
        flash('Please log in to access the admin dashboard.', 'danger')
        return redirect(url_for('auth.admin_login'))

    # Fetch the admin using the ID from the JWT token
    admin = Admin.query.get(admin_identity['admin_id'])

    if not admin:
        flash('Admin not found.', 'danger')
        return redirect(url_for('auth.admin_login'))
    hrs = HR.query.all()
    total_hr = HR.query.count()
    total_interviews = Interview.query.count()
    total_sessions = Session.query.count()

    # Ensure created_at is datetime object (if needed)
    for hr in hrs:
        if isinstance(hr.created_at, str):
            hr.created_at = datetime.strptime(hr.created_at, '%Y-%m-%d')
    
    # Fetch mean ratings per question
    questions = ReviewQuestion.query.with_entities(ReviewQuestion.text).distinct().all()
    question_ratings = {}
    for question in questions:
        avg_rating = db.session.query(func.avg(ReviewQuestion.rating)).filter(ReviewQuestion.text == question.text).scalar()
        rating_count = db.session.query(func.count(ReviewQuestion.rating)).filter(ReviewQuestion.text == question.text).scalar()
        question_ratings[question.text] = {
            'avg_rating': avg_rating,
            'rating_count': rating_count
        }


    # Fetch interviews and sessions count for each HR
    hr_interview_session_data = []
    for hr in hrs:
        interview_count = Interview.query.filter_by(hr_id=hr.id).count()
        session_count = db.session.query(Session).join(InterviewParameter).join(Interview).filter(Interview.hr_id == hr.id).count()
        hr_interview_session_data.append({
            'hr': hr,
            'interview_count': interview_count,
            'session_count': session_count
        }) 

    return render_template('admin/admin_homepage.html', admin=admin, hrs=hrs, 
                           total_hr=total_hr, total_interviews=total_interviews, 
                           total_sessions=total_sessions, question_ratings=question_ratings,
                           hr_interview_session_data=hr_interview_session_data)



@admin.route('/confirm/<int:hr_id>', methods=['GET', 'POST'])
@jwt_required()
def confirm_account(hr_id):
    admin_id = request.form.get('admin_id')  # Get admin_id from session set by the decorator
    print(f"admin_id from session: {admin_id}")

    hrs = HR.query.get(hr_id)
    if not hrs:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.home', admin_id=admin_id))
    

    return render_template('admin/admin_account_confirmation.html', email=hrs.email, name=hrs.name, surname=hrs.surname, company_name=hrs.company.name, hr_id=hrs.id, admin_id=admin_id)


@admin.route('/accept/<int:hr_id>', methods=['POST'])
@jwt_required()
def accept_account(hr_id):
    data = request.get_json()  # Fetch JSON data from the request
    if data is None:
        return jsonify({"msg": "Invalid input, JSON data required"}), 400
    
    admin_id = data.get('admin_id')
    if not admin_id:
        return jsonify({"msg": "Admin ID missing from form data"}), 400
    
    user = HR.query.get_or_404(hr_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.home', admin_id=admin_id))
    
    user.confirmed = True
    db.session.commit()

    # Send email to HR confirming account activation
    msg = Message('Tunz.ai Account Confirmation',
                  sender='noreply@tunz.ai',
                  recipients=[user.email])
    url = get_url('auth.login')
    msg.body = f'👋 Hello {user.name}, \n\nWe have just confirmed your account! You are all set. To login, go to: {url} \n\nThanks! \nThe Tunz AI Team.'
    mail.send(msg)
    
    return jsonify({"redirect_url": url_for('admin.home', admin_id=admin_id)}), 200


@admin.route('/deny/<int:hr_id>', methods=['POST'])
@jwt_required()
def deny_account(hr_id):
    data = request.get_json()  # Fetch JSON data from the request
    if data is None:
        return jsonify({"msg": "Invalid input, JSON data required"}), 400
    
    admin_id = data.get('admin_id')
    if not admin_id:
        return jsonify({"msg": "Admin ID missing from form data"}), 400
    
    user = HR.query.get_or_404(hr_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.home', admin_id=admin_id))

    # Send email to HR denying account activation
    msg = Message('Account Denied',
                  sender='noreply@tunz.ai',
                  recipients=[user.email])
    msg.body = f'👋 Hello {user.name}, \n\n Unfortunately, your account has been denied. If you have any questions, please contact us. \n\n The Tunz AI Team.'
    mail.send(msg)
    
    db.session.delete(user)
    db.session.commit()
    
    return jsonify({"redirect_url": url_for('admin.home', admin_id=admin_id)}), 200





@admin.route('/delete_hr/<int:hr_id>', methods=['POST'])
@jwt_required()
def delete_hr(hr_id):
    try:
        # Determine if the request is sending JSON data
        if request.is_json:
            data = request.get_json()
        else:
            # Fallback to form data if it's a regular form submission
            data = request.form

        # Proceed with the deletion
        hr = HR.query.get_or_404(hr_id)
        db.session.delete(hr)
        db.session.commit()

        # Handle JSON and form-based submissions
        if request.is_json:
            return jsonify({"msg": "HR deleted successfully.", "redirect_url": url_for('admin.home')}), 200
        else:
            flash('HR deleted successfully.', 'success')
            return redirect(url_for('admin.home'))

    except Exception as e:
        # Handle exceptions for both JSON and form-based submissions
        if request.is_json:
            return jsonify({"msg": f"An error occurred: {str(e)}"}), 500
        else:
            flash(f"An error occurred: {str(e)}", 'danger')
            return redirect(url_for('admin.home'))



@admin.route('/view_hr_info/<int:hr_id>', methods=['GET'])
@jwt_required()
def view_hr_info(hr_id):
    admin_id = session.get('admin_id')  # Get admin_id from session set by the decorator
    hr = HR.query.get_or_404(hr_id)
    if not hr:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.home', admin_id=admin_id))
    
    return render_template('admin/view_hr_info.html', hr=hr, admin_id=admin_id)
