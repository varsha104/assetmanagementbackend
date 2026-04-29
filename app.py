from flask import Flask, request, jsonify
from passlib.context import CryptContext
from flask_sqlalchemy import SQLAlchemy
import barcode
from barcode.writer import ImageWriter
import io
import os
import sys
from flask_migrate import Migrate
from flask_cors import CORS
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from decimal import Decimal
import logging
from typing import Optional, List, Dict, Union
from flask_cors import CORS
from flask_mail import Mail, Message
import random
import string
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy import create_engine, text, inspect  # Keep this if you are using SQLAlchemy engine directly
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base




# Initialize Flask app and SQLAlchemy
app = Flask(__name__)
CORS(app)


# # Password hashing
# pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# Configure the app with database URI (modify with your actual credentials)
app.config['SQLALCHEMY_DATABASE_URI'] = 'postgresql://postgres:postgres@localhost:5432/assetmanagement'


# DATABASE_URL = "postgresql://postgres:Sudha%40143@localhost/assetmanagementdb1"

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Directory to save barcode images in the project directory (optional)
UPLOAD_FOLDER = 'barcodes'  # Folder inside the project directory to store barcode images
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)  # Create the folder if it doesn't exist



# Initialize the SQLAlchemy object with the app


app.config['MAIL_SERVER'] = 'smtp.office365.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = 'teja.g@makonissoft.com'  # Replace with your email
app.config['MAIL_PASSWORD'] = 'Rahithya007@'  # Store securely, e.g., use environment variables
app.config['MAIL_DEFAULT_SENDER'] = 'teja.g@makonissoft.com'  # Your email

db = SQLAlchemy(app)
migrate = Migrate(app, db)
mail = Mail(app)
STATUS_RETURN_REQUESTED = "RETURN_REQUESTED"
STATUS_RETURNED = "RETURNED"
STATUS_AVAILABLE = "AVAILABLE"
DEFAULT_USER_ROLE = "higher management"

_intangible_has_user_id_column_cache = None


def _format_date_for_json(value):
    return value.strftime('%Y-%m-%d') if value else None


def _intangible_has_user_id_column():
    global _intangible_has_user_id_column_cache
    if _intangible_has_user_id_column_cache is None:
        try:
            columns = {col['name'] for col in inspect(db.engine).get_columns('intangible_assets')}
            _intangible_has_user_id_column_cache = 'user_id' in columns
        except Exception:
            _intangible_has_user_id_column_cache = False
    return _intangible_has_user_id_column_cache


def _intangible_employee_match_sql():
    if _intangible_has_user_id_column():
        return """
            user_id = :employee_id
            OR CAST(assigned_to AS TEXT) = :employee_id_text
            OR (:employee_name IS NOT NULL AND CAST(assigned_to AS TEXT) = :employee_name)
        """

    return """
        CAST(assigned_to AS TEXT) = :employee_id_text
        OR (:employee_name IS NOT NULL AND CAST(assigned_to AS TEXT) = :employee_name)
    """


def _fetch_intangible_assets_for_employee(employee_id, employee_name=None):
    where_clause = _intangible_employee_match_sql()
    query = text(f"""
        SELECT
            id,
            name,
            license_key,
            validity_start_date,
            validity_end_date,
            vendor,
            status
        FROM intangible_assets
        WHERE {where_clause}
        ORDER BY id
    """)
    params = {
        "employee_id": employee_id,
        "employee_id_text": str(employee_id),
        "employee_name": employee_name
    }
    return db.session.execute(query, params).mappings().all()


def _update_intangible_assets_status_for_employee(employee_id, employee_name, status):
    where_clause = _intangible_employee_match_sql()
    query = text(f"""
        UPDATE intangible_assets
        SET status = :status
        WHERE {where_clause}
        RETURNING id, name, status
    """)
    params = {
        "status": status,
        "employee_id": employee_id,
        "employee_id_text": str(employee_id),
        "employee_name": employee_name
    }
    return db.session.execute(query, params).mappings().all()


def _update_intangible_asset_status_by_id(asset_id, status):
    query = text("""
        UPDATE intangible_assets
        SET status = :status
        WHERE id = :asset_id
        RETURNING id, name, status
    """)
    return db.session.execute(query, {"status": status, "asset_id": asset_id}).mappings().first()



#maintenance
def send_maintenance_email(user_email, asset_name, maintenance_date, remarks, completion=False):
    subject = f"Maintenance {'Completed' if completion else 'Scheduled'} for {asset_name}"
    
    body = f"""
Dear {user_email.split('@')[0].capitalize()},

The maintenance for your asset **{asset_name}** has been {'successfully completed' if completion else 'scheduled'}.

Details:
- Maintenance Date: {maintenance_date}
- Remarks: {remarks}

If you have any concerns, please contact our support team.

Best regards,  
**Asset Management Team**
"""
    try:
        with app.app_context():  # Ensures the app context is active
            msg = Message(
                subject=subject,
                recipients=[user_email],
                body=body
            )
            mail.send(msg)
            print(f"✅ Email sent successfully to {user_email}")
    except Exception as e:
        print(f"❌ Error sending email: {e}")




# Enable logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def send_renewal_email_to_management(management_emails, subscription_name, renewal_date):
    """Sends an email reminder to higher management about an upcoming subscription renewal."""
    with app.app_context():
        subject = f"ALERT: {subscription_name} Renewal Due in 2 Days!"
        body = f"""
        Dear Higher Management,

        The subscription '{subscription_name}' is due for renewal on {renewal_date}.
        
        📅 Days Left: 2  
        Please ensure timely renewal to avoid service disruption.

        Best Regards,  
        Asset Management System
        """
        
        msg = Message(subject, recipients=management_emails, body=body)
        
        try:
            mail.send(msg)
            logging.info(f"📩 Email sent to higher management for {subscription_name} renewal in 2 days.")
        except Exception as e:
            logging.error(f"❌ Failed to send email: {str(e)}")



def check_renewals():
    """Checks subscriptions expiring in exactly 2 days and sends email reminders to higher management."""
    with app.app_context():
        logging.info("Running check_renewals at: %s", datetime.now())  # Log when function runs

        today = datetime.today().date()
        reminder_date = today + timedelta(days=2)  # Fetch subscriptions renewing in 2 days

        logging.info("Reminder email should be sent on: %s", today)
        logging.info("Checking subscriptions renewing on: %s", reminder_date)

        # Fetch subscriptions that are due for renewal in 2 days
        query = text("""
            SELECT ia.name AS subscription_name, 
                   DATE(ia.validity_end_date) AS renewal_date
            FROM intangible_assets ia
            WHERE DATE(ia.validity_end_date) = :renewal_date;
        """)

        renewal_subscriptions = db.session.execute(query, {'renewal_date': reminder_date}).fetchall()

        # List of higher management emails
        higher_management_emails = ["prasanthgutha2002@gmail.com"]

        logging.info("Fetched subscriptions: %s", renewal_subscriptions)

        if not renewal_subscriptions:
            logging.info("No subscriptions due for renewal today.")
        else:
            for sub in renewal_subscriptions:
                logging.info(f"Sending email for subscription: {sub[0]} (Renewal Date: {sub[1]})")
                send_renewal_email_to_management(higher_management_emails, sub[0], sub[1])

# Create and start scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(check_renewals, 'cron', hour=15, minute=5)  # Runs every day at 11:41 AM
scheduler.start()

logging.info("Scheduler started. It will run daily at 03:05 PM.")

# Check if jobs are scheduled
print("Scheduled jobs:", scheduler.get_jobs())







class User(db.Model):
    __tablename__ = 'user'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)  # Added username
    email = db.Column(db.String(120), unique=True, nullable=False)
    phone_number = db.Column(db.String(15), unique=True, nullable=True)
    password = db.Column(db.String(200), nullable=False)
    department = db.Column(db.String(100), nullable=False, default=DEFAULT_USER_ROLE)




from datetime import datetime

class EmployeeAssetRequest(db.Model):
    __tablename__ = "employee_asset_requests"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))   # employee raising request
    employee_id = db.Column(db.Integer, db.ForeignKey("user.id"))  # HR

    asset_type = db.Column(db.String(100))
    asset_name = db.Column(db.String(200))
    department = db.Column(db.String(100))

    reason = db.Column(db.Text)

    required_from = db.Column(db.Date)

    urgency = db.Column(db.String(50))

    status = db.Column(db.String(50), default="PENDING")

    created_at = db.Column(db.DateTime, default=datetime.utcnow)



class HRAssetRequest(db.Model):
    __tablename__ = 'hr_asset_requests'

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    requested_by = db.Column(db.Integer)  # HR id

    asset_type = db.Column(db.String(100), nullable=False)

    status = db.Column(db.String(50), default="PENDING")

    created_at = db.Column(db.DateTime)



class AssetRequest(db.Model):
    __tablename__ = "asset_requests"

    id = db.Column(db.Integer, primary_key=True)

    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    asset_type = db.Column(db.String(100), nullable=False)
    asset_name = db.Column(db.String(100), nullable=False)

    reason = db.Column(db.Text, nullable=False)

    manager_status = db.Column(db.String(50), default="PENDING")
    accounts_status = db.Column(db.String(50), default="PENDING")

    final_status = db.Column(db.String(50), default="PENDING")


# class Product(db.Model):
#     __tablename__ = 'products'

#     id = db.Column(db.Integer, primary_key=True)
#     product_name = db.Column(db.String(255), nullable=False)
#     serial_number = db.Column(db.String(255), unique=True, nullable=False)
#     company = db.Column(db.String(255))  # Renamed 'product_details' to 'company'
#     barcode = db.Column(db.LargeBinary)  # To store the barcode image as binary data
#     user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Changed from employee_id to user_id

#     # New fields
#     purchase_date = db.Column(db.Date, nullable=True)  # Date of purchase
#     status = db.Column(db.String(50), nullable=True)  # Status of the product (Available/Allocated/Under Maintenance)
#     condition = db.Column(db.String(50), nullable=True)  # Condition of the product (e.g., new, used, damaged)

#     # Define relationship with Repairs (one-to-many relationship)
#     repairs = db.relationship('Repair', backref='product', lazy=True)
#     disposal_status = db.Column(db.String(50), default="NONE")
#     # Define relationship with User
#     user = db.relationship('User', backref='products', lazy=True)  # Establish relationship with User model
#     disposal_date = db.Column(db.Date, nullable=True)
#     location = db.Column(db.String(100), nullable=True)



class Product(db.Model):
    __tablename__ = 'products'

    id = db.Column(db.Integer, primary_key=True)

    # Basic
    asset_name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(100))
    category = db.Column(db.String(100))

    # Serial & company
    serial_number = db.Column(db.String(255), unique=True, nullable=False)
    company = db.Column(db.String(255))

    # Dates
    purchase_date = db.Column(db.Date)
    warranty_period = db.Column(db.String(100))  # keeping string because "N/A"

    # Status
    status = db.Column(db.String(50))
    approval_status = db.Column(db.String(50))

    # Assignment (FK)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Assigner info
    asset_name = db.Column(db.String(255), nullable=True)
    created_by = db.Column(db.String(255))
    assigner_location = db.Column(db.String(255))

    # Employee snapshot
    employee_name = db.Column(db.String(255))
    employee_contact_number = db.Column(db.String(20))
    employment_type = db.Column(db.String(50))
    employee_location = db.Column(db.String(255))

    # Laptop details
    laptop_model_number = db.Column(db.String(255))
    laptop_specifications = db.Column(db.Text)

    # Financial
    amount = db.Column(db.Numeric(10, 2))

    # Vendor
    vendor = db.Column(db.String(255))
    vendor_name = db.Column(db.String(255))

    # Condition
    condition = db.Column(db.String(50))

    # Existing
    barcode = db.Column(db.LargeBinary)
    disposal_status = db.Column(db.String(50), default="NONE")
    disposal_date = db.Column(db.Date)
    location = db.Column(db.String(100))

    # Relationships
    user = db.relationship('User', backref='products', lazy=True)
    repairs = db.relationship('Repair', backref='product', lazy=True)



# Define the Repair model
class Repair(db.Model):
    __tablename__ = 'repairs'

    id = db.Column(db.Integer, primary_key=True)
    issue_description = db.Column(db.String(255), nullable=False)
    repair_center = db.Column(db.String(255), nullable=True)
    repair_date = db.Column(db.Date, nullable=True)
    return_date = db.Column(db.Date, nullable=True)
    status = db.Column(db.String(50), nullable=True)
    message = db.Column(db.String(250), nullable=True)

    # Foreign key to connect this repair record with a product
    product_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)

    # Foreign key to associate the repair with a user
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    # Define relationship
    user = db.relationship('User', backref=db.backref('repairs', lazy=True))


    # def __init__(self, issue_description, repair_center, repair_date, return_date, product_id, status, message=None):
    #     self.issue_description = issue_description
    #     self.repair_center = repair_center
    #     self.repair_date = repair_date
    #     self.return_date = return_date
    #     self.product_id = product_id
    #     self.status = status
    #     self.message = message

# class IntangibleAsset(db.Model):
#     __tablename__ = 'intangible_assets'

#     id = db.Column(db.Integer, primary_key=True)
#     name = db.Column(db.String(255), nullable=False)  # Name of the asset
#     license_key = db.Column(db.String(255), unique=True, nullable=True)  # License key (optional for non-license assets)
#     validity_start_date = db.Column(db.Date, nullable=True)  # Start date of validity
#     validity_end_date = db.Column(db.Date, nullable=True)  # End date of validity
#     vendor = db.Column(db.String(255), nullable=True)  # Vendor or provider name
#     assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Assigned user (not employee)
#     status = db.Column(db.String(50), nullable=False, default='active')  # Status (e.g., active, expired, inactive)
#     amount = db.Column(db.Numeric(10, 2), nullable=True)  # Amount column added
#     subscription_type = db.Column(db.String(100), nullable=True)  # Subscription type (e.g., Monthly, Yearly, Lifetime)

#     # Define relationship with User
#     assigned_user = db.relationship('User', backref='intangible_assets', lazy=True)

#     def __init__(self, name, license_key=None, validity_start_date=None, validity_end_date=None, vendor=None, assigned_to=None, status='active', amount=None, subscription_type=None):
#         self.name = name
#         self.license_key = license_key
#         self.validity_start_date = validity_start_date
#         self.validity_end_date = validity_end_date
#         self.vendor = vendor
#         self.assigned_to = assigned_to
#         self.status = status
#         self.amount = amount
#         self.subscription_type = subscription_type



class IntangibleAsset(db.Model):
    __tablename__ = 'intangible_assets'

    id = db.Column(db.Integer, primary_key=True)

    # Basic
    name = db.Column(db.String(255), nullable=False)
    type = db.Column(db.String(100))
    category = db.Column(db.String(100))

    # Dates
    purchase_date = db.Column(db.Date)
    warranty_period = db.Column(db.Date)
    validity_start_date = db.Column(db.Date)
    validity_end_date = db.Column(db.Date)
    renewal_date = db.Column(db.Date)

    # Status
    status = db.Column(db.String(50), default='active')
    approval_status = db.Column(db.String(50))

    # FK (IMPORTANT)
    assigned_to = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)

    # Other fields
    created_by = db.Column(db.String(255))
    assigner_location = db.Column(db.String(255))

    # Employee info (optional duplication for history)
    employee_name = db.Column(db.String(255))
    employee_contact_number = db.Column(db.String(20))
    employment_type = db.Column(db.String(50))
    employee_location = db.Column(db.String(255))

    # Subscription
    subscription_type = db.Column(db.String(100))

    # Financial
    amount_paid = db.Column(db.Numeric(10, 2))

    # Vendor & License
    vendor = db.Column(db.String(255))
    license_key = db.Column(db.String(255), unique=True)

    # Relationship
    assigned_user = db.relationship('User', backref='intangible_assets', lazy=True)





class AdditionalAsset(db.Model):
    __tablename__ = 'additional_assets'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)  # Name of the asset
    number = db.Column(db.Integer, nullable=False)  # Quantity or number of assets
    status = db.Column(db.String(50), nullable=True)  # Status of the asset (e.g., 'Available', 'Requested', etc.)
    company = db.Column(db.String(50), nullable=True)
    approval_status = db.Column(db.String(50), nullable=True)
    
    
    
class AdditionalIntangibleAsset(db.Model):
    __tablename__ = 'add_intangible_assets'

    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    months = db.Column(db.Integer, nullable=False)
    approval_status = db.Column(db.String(50), default='Pending')
    
    
class Maintenance(db.Model):
    __tablename__ = 'maintenance'
    
    id = db.Column(db.Integer, primary_key=True)
    asset_id = db.Column(db.Integer, db.ForeignKey('products.id'), nullable=False)  # Corrected FK reference
    scheduled_by = db.Column(db.String(100), nullable=False)  # Technician's email
    maintenance_date = db.Column(db.Date, nullable=False)
    remarks = db.Column(db.String(200), nullable=True)
    status = db.Column(db.String(20), default='Scheduled')  # 'Scheduled' or 'Completed'

    # Establish relationship with Product table
    product = db.relationship('Product', backref='maintenance_records', lazy=True)
    
class NewAssetRequests(db.Model):
    __tablename__ = 'new_asset_requests'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)  # Asset name
    #number = db.Column(db.Integer, nullable=False)  # Quantity requested
    company = db.Column(db.String(50), nullable=True)  # Company providing the asset
    amount = db.Column(db.Float, nullable=False)  # Cost of the asset
    status = db.Column(db.String(50), nullable=False, default="Approval Pending")  # Status (Approval Pending / Approved)
    product_details = db.Column(db.Text, nullable=True)  # Additional product details
    technician_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # Link to User table
    asset_type = db.Column(db.String(100), nullable=True)  # ✅ New field for Asset Type




    


def generate_random_password(length=10):
    characters = string.ascii_letters + string.digits + "!@#$%^&*()"
    return ''.join(random.choice(characters) for _ in range(length))

# Function to send an email
def send_email(to_email, username, password):
    try:
        msg = Message("Your Account Credentials", recipients=[to_email])
        msg.body = (
            f"Dear {username},\n\n"
            "Your account has been created successfully.\n\n"
            f"Username: {username}\n"
            f"Password: {password}\n\n"
            "Please change your password after logging in.\n\n"
            "Best regards,\nYour Company Team"
        )
        mail.send(msg)
        print("Email sent successfully!")
    except Exception as e:
        print("Error sending email:", str(e))

# API to register a user
@app.route('/register', methods=['POST'])
def register_user():
    data = request.get_json()

    # Validate required fields
    if not all(key in data for key in ['name', 'username', 'email']):
        return jsonify({"error": "Missing required fields"}), 400

    # Check if username or email already exists
    existing_user = User.query.filter((User.username == data['username']) | (User.email == data['email'])).first()
    if existing_user:
        return jsonify({"error": "Username or email already exists"}), 400

    # Use user-provided password when available (self-registration flow),
    # otherwise fall back to generated password (admin-created accounts).
    raw_password = data.get('password') or generate_random_password()
    hashed_password = generate_password_hash(raw_password)

    # Create a new user
    new_user = User(
        name=data['name'],
        username=data['username'],
        email=data['email'],
        phone_number=data.get('phone_number'),  # Optional field
        password=hashed_password,
        department=DEFAULT_USER_ROLE
    )

    try:
        db.session.add(new_user)
        db.session.commit()
        # Send credentials to the registered user's email.
        send_email(data['email'], data['username'], raw_password)
        return jsonify({"message": "User registered successfully"}), 201
    except Exception as e:
        return jsonify({"error": "Error registering user"}), 500



@app.route('/api/productss', methods=['POST'])
def get_productss():
    data = request.get_json()
    product_name = data.get('product_name')
    status = data.get('product_status')  # Get status from frontend
    
    if not product_name:
        return jsonify({'error': 'Product name is required'}), 400

    # Base query filtering by product name
    query = Product.query.filter(Product.product_name == product_name)

    # Apply status filter if provided
    if status:
        query = query.filter(Product.status == status)

    products = query.all()

    if not products:
        return jsonify({'message': 'No products found'}), 200

    product_list = [
        {
            'id': product.id,
            'product_name': product.product_name,
            'serial_number': product.serial_number,
            'company': product.company,
            'purchase_date': product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else None,
            'status': product.status,
            'condition': product.condition
        }
        for product in products
    ]

    return jsonify({'products': product_list}), 200


pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


@app.route('/login', methods=['POST'])
def login_user():
    data = request.get_json()

    # Validate input
    if not all(key in data for key in ['username', 'password']):
        return jsonify({"error": "Missing username or password"}), 400

    # Fetch user from the database
    user = User.query.filter_by(username=data['username']).first()

    if user and check_password_hash(user.password, data['password']):
        return jsonify({
            "message": "Login successful",
            "id": user.id,
            "name": user.name,
            "username": user.username,
            "email": user.email,
            "department": DEFAULT_USER_ROLE,
            "role": DEFAULT_USER_ROLE
        }), 200
    else:
        return jsonify({"error": "Invalid username or password"}), 401

@app.route('/change-password', methods=['POST'])
def change_password():
    data = request.get_json()

    # Validate input
    if not all(key in data for key in ['email', 'old_password', 'new_password']):
        return jsonify({"error": "Missing required fields"}), 400

    # Fetch user from the database using email
    user = User.query.filter_by(email=data['email']).first()

    if not user:
        return jsonify({"error": "User not found"}), 404

    # Check if the old password is correct
    if not check_password_hash(user.password, data['old_password']):
        return jsonify({"error": "Incorrect old password"}), 401

    # Hash the new password and update it
    user.password = generate_password_hash(data['new_password'])
    
    try:
        db.session.commit()
        return jsonify({"message": "Password changed successfully"}), 200
    except Exception as e:
        return jsonify({"error": "Error updating password"}), 500




# @app.route('/add_product', methods=['POST'])
# def add_product():
#     data = request.get_json()

#     # Validate required fields
#     product_name = data.get('product_name')
#     serial_number = data.get('serial_number')
#     if not product_name or not serial_number:
#         return jsonify({'error': 'Product name and serial number are required'}), 400

#     # Optional fields
#     company = data.get('company')
#     user_id = data.get('user_id')  # The ID of the user the product is assigned to
#     purchase_date = data.get('purchase_date')  # Optional purchase date
#     status = data.get('status')  # Optional status
#     condition = data.get('condition')  # Optional condition

#     # If user_id is not provided, explicitly set it to None
#     if not user_id:
#         user_id = None
#     else:
#         # Validate if the user exists
#         user = User.query.get(user_id)
#         if not user:
#             return jsonify({'error': f'User with ID {user_id} not found.'}), 404

#     # Create a new Product instance
#     new_product = Product(
#         product_name=product_name,
#         serial_number=serial_number,
#         company=company,
#         user_id=user_id,  # Assign to User instead of Employee
#         purchase_date=purchase_date,
#         status=status,
#         condition=condition
#     )

#     try:
#         # Save the product to the database
#         db.session.add(new_product)
#         db.session.commit()

#         return jsonify({
#             'message': f"Product '{product_name}' added successfully.",
#             'product_id': new_product.id,
#             'assigned_to': user_id if user_id else None
#         }), 201
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 400


from datetime import datetime

def parse_date(date_str):
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    return None


@app.route('/add_product', methods=['POST'])
def add_product():
    data = request.get_json()
 
    asset_name = data.get('assetName')
    serial_number = data.get('serialNumber')
    assigned_to = data.get('assignedTo')
 
    if not asset_name or not serial_number:
        return jsonify({'error': 'Asset name and serial number are required'}), 400
 
    # Validate user
    user = None
    if assigned_to:
        user = User.query.get(assigned_to)
        if not user:
            return jsonify({'error': f'User with ID {assigned_to} not found'}), 404
 
    try:
        new_product = Product(
 
            # Basic
            asset_name=asset_name,
            type=data.get('type'),
            category=data.get('category'),
 
            # Serial
            serial_number=serial_number,
            company=data.get('company'),
 
            # Dates
            purchase_date=parse_date(data.get('purchaseDate')),
            warranty_period=data.get('warrantyPeriod'),
 
            # Status
            status=data.get('status'),
            approval_status=data.get('approvalStatus'),
 
            # Assignment
            user_id=assigned_to if user else None,
 
            # Assigner
#            assigner_name=data.get('name'),
            created_by=data.get('name'),
            assigner_location=data.get('assignerLocation'),
 
            # Employee snapshot
            employee_name=data.get('employeeName'),
            employee_contact_number=data.get('employeeContactNumber'),
            employment_type=data.get('employmentType'),
            employee_location=data.get('employeeLocation'),
 
            # Laptop
            laptop_model_number=data.get('laptopModelNumber'),
            laptop_specifications=data.get('laptopSpecifications'),
 
            # Financial
            amount=data.get('amount'),
 
            # Vendor
            vendor=data.get('vendor'),
            vendor_name=data.get('vendorName'),
 
            # Condition
            condition=data.get('condition')
        )
 
        db.session.add(new_product)
        db.session.commit()
 
        return jsonify({
            "message": "Product added successfully",
            "product": {
                "id": new_product.id,
                "assetName": new_product.asset_name,
                "assignedTo": new_product.user_id
            }
        }), 201
 
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400
    data = request.get_json()

    asset_name = data.get('assetName')
    serial_number = data.get('serialNumber')
    assigned_to = data.get('assignedTo')

    if not asset_name or not serial_number:
        return jsonify({'error': 'Asset name and serial number are required'}), 400

    # Validate user
    user = None
    if assigned_to:
        user = User.query.get(assigned_to)
        if not user:
            return jsonify({'error': f'User with ID {assigned_to} not found'}), 404

    try:
        new_product = Product(

            # Basic
            asset_name=asset_name,
            type=data.get('type'),
            category=data.get('category'),

            # Serial
            serial_number=serial_number,
            company=data.get('company'),

            # Dates
            purchase_date=parse_date(data.get('purchaseDate')),
            warranty_period=data.get('warrantyPeriod'),

            # Status
            status=data.get('status'),
            approval_status=data.get('approvalStatus'),

            # Assignment
            user_id=assigned_to if user else None,

            # Assigner
            assigner_name=data.get('name'),
            created_by=data.get('createdBy'),
            assigner_location=data.get('assignerLocation'),

            # Employee snapshot
            employee_name=data.get('employeeName'),
            employee_contact_number=data.get('employeeContactNumber'),
            employment_type=data.get('employmentType'),
            employee_location=data.get('employeeLocation'),

            # Laptop
            laptop_model_number=data.get('laptopModelNumber'),
            laptop_specifications=data.get('laptopSpecifications'),

            # Financial
            amount=data.get('amount'),

            # Vendor
            vendor=data.get('vendor'),
            vendor_name=data.get('vendorName'),

            # Condition
            condition=data.get('condition')
        )

        db.session.add(new_product)
        db.session.commit()

        return jsonify({
            "message": "Product added successfully",
            "product": {
                "id": new_product.id,
                "assetName": new_product.asset_name,
                "assignedTo": new_product.user_id
            }
        }), 201

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400




@app.route('/api/assets/<int:user_id>', methods=['GET'])
def get_assets_by_user(user_id):
    employee = User.query.get(user_id)
    employee_name = employee.name if employee else None
 
    # Fetch products and intangible assets linked to this employee
    products = Product.query.filter_by(user_id=user_id).all()
    intangible_assets = _fetch_intangible_assets_for_employee(user_id, employee_name)
 
    if not products and not intangible_assets:
        return jsonify({'message': 'No products or intangible assets found for this user'}), 404
 
    # Serialize product data
    product_list = [
        {
            'id': product.id,
            'product_name': product.product_name,
            'serial_number': product.serial_number,
            'company': product.company,
            'purchase_date': _format_date_for_json(product.purchase_date),
            'status': product.status,        
            'condition': product.condition
        }
        for product in products
    ]
 
    # Serialize intangible asset data
    intangible_asset_list = [
        {
            'id': asset['id'],
            'name': asset['name'],
            'license_key': asset['license_key'],
            'validity_start_date': _format_date_for_json(asset['validity_start_date']),
            'validity_end_date': _format_date_for_json(asset['validity_end_date']),
            'vendor': asset['vendor'],
            'status': asset['status']
        }
        for asset in intangible_assets
    ]
 
    return jsonify({
        'products': product_list,
        'intangible_assets': intangible_asset_list
    }), 200
    employee = User.query.get(user_id)
    employee_name = employee.name if employee else None

    # Fetch products and intangible assets linked to this employee
    products = Product.query.filter_by(user_id=user_id).all()
    intangible_assets = _fetch_intangible_assets_for_employee(user_id, employee_name)

    if not products and not intangible_assets:
        return jsonify({'message': 'No products or intangible assets found for this user'}), 404

    # Serialize product data
    product_list = [
        {
            'id': product.id,
            'product_name': product.product_name,
            'serial_number': product.serial_number,
            'company': product.company,
            'purchase_date': _format_date_for_json(product.purchase_date),
            'status': product.status,        
            'condition': product.condition
        }
        for product in products
    ]

    # Serialize intangible asset data
    intangible_asset_list = [
        {
            'id': asset['id'],
            'name': asset['name'],
            'license_key': asset['license_key'],
            'validity_start_date': _format_date_for_json(asset['validity_start_date']),
            'validity_end_date': _format_date_for_json(asset['validity_end_date']),
            'vendor': asset['vendor'],
            'status': asset['status']
        }
        for asset in intangible_assets
    ]

    return jsonify({
        'products': product_list,
        'intangible_assets': intangible_asset_list
    }), 200

@app.route('/products', methods=['GET'])
def get_all_products():
    products = Product.query.all()
 
    if not products:
        return jsonify({'message': 'No products found'}), 404
 
    product_list = [
        {
            'id': product.id,
 
            # Basic
            'asset_name': product.asset_name,
            'type': product.type,
            'category': product.category,
 
            # Serial & company
            'serial_number': product.serial_number,
            'company': product.company,
 
            # Dates
            'purchase_date': product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else None,
            'warranty_period': product.warranty_period,
 
            # Status
            'status': product.status,
            'approval_status': product.approval_status,
 
            # Assignment
            'user_id': product.user_id,
 
            # Assigner
            'created_by': product.created_by,
            'assigner_location': product.assigner_location,
 
            # Employee snapshot
            'employee_name': product.employee_name,
            'employee_contact_number': product.employee_contact_number,
            'employment_type': product.employment_type,
            'employee_location': product.employee_location,
 
            # Laptop
            'laptop_model_number': product.laptop_model_number,
            'laptop_specifications': product.laptop_specifications,
 
            # Financial
            'amount': float(product.amount) if product.amount else None,
 
            # Vendor
            'vendor': product.vendor,
            'vendor_name': product.vendor_name,
 
            # Condition
            'condition': product.condition,
 
            # Existing
            'barcode': product.barcode.decode('utf-8') if product.barcode else None,
            'disposal_status': product.disposal_status,
            'disposal_date': product.disposal_date.strftime('%Y-%m-%d') if product.disposal_date else None,
            'location': product.location,
 
            # Relationship
            'assigned_to': product.user.name if product.user else None,
        }
        for product in products
    ]
 
    return jsonify({'products': product_list}), 200
    products = Product.query.all()
 
    if not products:
        return jsonify({'message': 'No products found'}), 404
 
    product_list = [
        {
            'id': product.id,
            'assetName': product.asset_name,  # ✅ FIXED
            'serialNumber': product.serial_number,
            'company': product.company,
            'purchaseDate': product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else None,
            'status': product.status,
            'condition': product.condition,
            'userId': product.user_id,
            'assignedTo': product.user.name if product.user else None,
            'location': product.location  # ✅ fixed casing
        }
        for product in products
    ]
 
    return jsonify({'products': product_list}), 200
    products = Product.query.all()

    if not products:
        return jsonify({'message': 'No products found'}), 404

    product_list = [
        {
            'id': product.id,
            'product_name': product.product_name,
            'serial_number': product.serial_number,
            'company': product.company,
            'purchase_date': product.purchase_date.strftime('%Y-%m-%d') if product.purchase_date else None,
            'status': product.status,
            'condition': product.condition,
            'user_id': product.user_id,
            'assigned_to': product.user.name if product.user else None,
            'Location': product.location  # 👈 Capital L
        }
        for product in products
    ]

    return jsonify({'products': product_list}), 200



@app.route('/products/update/<int:product_id>', methods=['POST'])
def update_product(product_id):
    try:
        product = Product.query.get(product_id)
 
        if not product:
            return jsonify({'error': 'Product not found'}), 404
 
        data = request.get_json()
 
        # Basic
        if 'assetName' in data:
            product.asset_name = data['assetName']
 
        if 'type' in data:
            product.type = data['type']
 
        if 'category' in data:
            product.category = data['category']
 
        # Serial & Company
        if 'serialNumber' in data:
            product.serial_number = data['serialNumber']
 
        if 'company' in data:
            product.company = data['company']
 
        # Dates
        if 'purchaseDate' in data:
            product.purchase_date = parse_date(data.get('purchaseDate'))
 
        if 'warrantyPeriod' in data:
            product.warranty_period = data['warrantyPeriod']
 
        # Status
        if 'status' in data:
            product.status = data['status']
 
        if 'approvalStatus' in data:
            product.approval_status = data['approvalStatus']
 
        # Assignment (validate user)
        if 'assignedTo' in data:
            user = User.query.get(data['assignedTo'])
            if not user:
                return jsonify({'error': f"User with ID {data['assignedTo']} not found"}), 404
            product.user_id = user.id
 
        # Assigner
        if 'name' in data:
            product.created_by = data['name']
 
        if 'assignerLocation' in data:
            product.assigner_location = data['assignerLocation']
 
        # Employee snapshot
        if 'employeeName' in data:
            product.employee_name = data['employeeName']
 
        if 'employeeContactNumber' in data:
            product.employee_contact_number = data['employeeContactNumber']
 
        if 'employmentType' in data:
            product.employment_type = data['employmentType']
 
        if 'employeeLocation' in data:
            product.employee_location = data['employeeLocation']
 
        # Laptop
        if 'laptopModelNumber' in data:
            product.laptop_model_number = data['laptopModelNumber']
 
        if 'laptopSpecifications' in data:
            product.laptop_specifications = data['laptopSpecifications']
 
        # Financial
        if 'amount' in data:
            product.amount = data['amount']
 
        # Vendor
        if 'vendor' in data:
            product.vendor = data['vendor']
 
        if 'vendorName' in data:
            product.vendor_name = data['vendorName']
 
        # Condition
        if 'condition' in data:
            product.condition = data['condition']
 
        # Extra fields (optional but good)
        if 'location' in data:
            product.location = data['location']
 
        if 'disposalStatus' in data:
            product.disposal_status = data['disposalStatus']
 
        if 'disposalDate' in data:
            product.disposal_date = parse_date(data.get('disposalDate'))
 
        db.session.commit()
 
        return jsonify({
            'message': 'Product updated successfully',
            'product_id': product.id
        }), 200
 
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    try:
        product = Product.query.get(product_id)

        if not product:
            return jsonify({'error': 'Product not found'}), 404

        data = request.json

        if 'product_name' in data:
            product.product_name = data['product_name']
        if 'serial_number' in data:
            product.serial_number = data['serial_number']
        if 'company' in data:
            product.company = data['company']
        if 'purchase_date' in data:
            product.purchase_date = datetime.strptime(data['purchase_date'], '%Y-%m-%d').date()
        if 'status' in data:
            product.status = data['status']
        if 'condition' in data:
            product.condition = data['condition']

        db.session.commit()

        return jsonify({'message': 'Product updated successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500

# delete aseets tangible 
@app.route('/products/delete/<int:product_id>', methods=['POST'])
def delete_product(product_id):
    try:
        product = Product.query.get(product_id)
 
        if not product:
            return jsonify({'error': 'Product not found'}), 404
 
        # 🔥 Step 1: Delete all related repairs
        repairs = Repair.query.filter_by(product_id=product_id).all()
 
        for repair in repairs:
            db.session.delete(repair)
 
        # 🔥 Step 2: Delete the product
        db.session.delete(product)
 
        db.session.commit()
 
        return jsonify({
            'message': 'Product and all related data deleted successfully',
            'deleted_product_id': product_id,
            'deleted_repairs_count': len(repairs)
        }), 200
 
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
    try:
        product = Product.query.get(product_id)
 
        if not product:
            return jsonify({'error': 'Product not found'}), 404
 
        db.session.delete(product)
        db.session.commit()
 
        return jsonify({
            'message': 'Product deleted successfully',
            'product_id': product_id
        }), 200
 
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 500
# Route to add a new repair
@app.route('/add_repair', methods=['POST'])
def add_repair():
    data = request.get_json()

    # Get repair details from the request
    issue_description = data.get('issue_description')
    repair_center = data.get('repair_center')
    repair_date = data.get('repair_date')
    return_date = data.get('return_date')
    product_id = data.get('product_id')  # The ID of the product being repaired

    # Default status should be 'In Repair'
    status = data.get('status', 'In Repair')

    # Create a new Repair instance
    new_repair = Repair(
        issue_description=issue_description,
        repair_center=repair_center,
        repair_date=repair_date,
        return_date=return_date,
        product_id=product_id,
        status=status
    )

    try:
        # Save the repair to the database
        db.session.add(new_repair)
        db.session.commit()

        return jsonify({
            'message': f"Repair record added successfully for product ID {product_id}.",
            'repair_id': new_repair.id
        }), 201
    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400

# Route to add a new employee
# @app.route('/add_employee', methods=['POST'])
# def add_employee():
#     data = request.get_json()

#     # Validate required fields
#     name = data.get('name')
#     designation = data.get('designation')
#     email = data.get('email')
#     status = data.get('status', 'active')  # Default status to 'active' if not provided

#     if not name or not designation or not email:
#         return jsonify({'error': 'Name, designation, and email are required.'}), 400

#     # Create a new Employee instance
#     new_employee = Employee(name=name, designation=designation, email=email, status=status)

#     try:
#         # Save the employee to the database
#         db.session.add(new_employee)
#         db.session.commit()

#         return jsonify({
#             'message': f"Employee '{name}' added successfully.",
#             'employee_id': new_employee.id
#         }), 201
#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 400

    
# @app.route('/assign_employee/<int:product_id>', methods=['POST'])
# def assign_user(product_id):
#     data = request.get_json()
#     print("Received data:", data)

#     user_id = data.get('user_id')
#     location = data.get('location') or data.get('Location')  # handle case difference

#     if not user_id or not location:
#         return jsonify({'error': 'user_id and location are required'}), 400

#     product = Product.query.get(product_id)

#     if product:
#         product.user_id = user_id
#         product.location = location
#         db.session.commit()
#         return jsonify({'message': f"User {user_id} assigned to product {product_id} at location {location}."}), 200
#     else:
#         return jsonify({'error': 'Product not found'}), 404



@app.route('/assign_employee/<int:product_id>', methods=['POST'])
@app.route('/api/assign_employee/<int:product_id>', methods=['POST'])
def assign_user(product_id):

    data = request.get_json() or {}
    print("Received data:", data)

    user_id = data.get('user_id')
    location = data.get('location') or data.get('Location')
    request_id = data.get('request_id')

    if not user_id or not location:
        return jsonify({'error': 'user_id and location are required'}), 400

    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({'error': 'user_id must be an integer'}), 400

    product = Product.query.get(product_id)
    assigned_user = User.query.get(user_id)

    if request_id in ("", None):
        request_id = None

    asset_request = None
    if request_id is not None:
        try:
            request_id = int(request_id)
        except (TypeError, ValueError):
            return jsonify({'error': 'request_id must be an integer'}), 400
        asset_request = HRAssetRequest.query.get(request_id)

    if not product:
        return jsonify({'error': 'Product not found'}), 404

    if not assigned_user:
        return jsonify({'error': 'User not found'}), 404

    if request_id is not None and not asset_request:
        return jsonify({'error': 'Asset request not found'}), 404

    try:
        # Assign product to employee
        product.user_id = user_id
        product.location = location

        # Update request status only when request_id is provided
        if asset_request:
            asset_request.status = "ASSIGNED"

        db.session.commit()

        response = {
            "message": "Product assigned successfully",
            "product_id": product_id,
            "assigned_to": user_id,
            "location": location
        }
        if asset_request:
            response["request_id"] = request_id
            response["request_status"] = "ASSIGNED"

        return jsonify(response), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


# @app.route('/scan_barcode', methods=['POST'])
# def scan_barcode():
#     # Get the barcode data from the request (the barcode will contain the product's ID)
#     barcode_scanned = request.get_json().get('barcode')

#     if not barcode_scanned:
#         return jsonify({'error': 'No barcode provided'}), 400

#     # Query the product by the scanned barcode (which is the product ID)
#     product = Product.query.get(barcode_scanned)

#     if product:
#         # Initialize response data
#         response = {
#             'product_name': product.product_name,
#             'serial_number': product.serial_number,
#             'company': product.company,
#             'barcode': barcode_scanned
#         }

#         # Get employee details if assigned
#         if product.employee_id:
#             employee = Employee.query.get(product.employee_id)
#             if employee:
#                 response['employee'] = {
#                     'name': employee.name,
#                     'designation': employee.designation,
#                     'email': employee.email
#                 }

#         # Get repair details if assigned
#         repair = Repair.query.filter_by(product_id=product.id).first()
#         if repair:
#             response['repair_details'] = {
#                 'issue_description': repair.issue_description,
#                 'repair_center': repair.repair_center,
#                 'repair_date': repair.repair_date,
#                 'return_date': repair.return_date
#             }

#         return jsonify(response), 200
#     else:
#         return jsonify({'error': 'Product not found for the scanned barcode'}), 404

# @app.route('/add_intangible_asset', methods=['POST'])
# def add_intangible_asset():
#     data = request.get_json()

#     # Validate required fields
#     name = data.get('name')
#     licenseKey = data.get('licenseKey')  # Changed to licenseKey
#     validity_start_date = data.get('validity_start_date')  # ISO format
#     validity_end_date = data.get('validity_end_date')      # ISO format
#     vendor = data.get('vendor')
#     assigned_to = data.get('assigned_to')                  # User ID (optional)
#     status = data.get('status', 'active')
#     Subscription_type = data.get('Subscription_type')      # Changed to Subscription_type
#     amount = data.get('amount')

#     if not name:
#         return jsonify({'error': 'Asset name is required.'}), 400

#     user = None
#     if assigned_to:
#         user = User.query.get(assigned_to)
#         if not user:
#             return jsonify({'error': f'User with ID {assigned_to} not found.'}), 404

#     # Create the asset
#     new_asset = IntangibleAsset(
#         name=name,
#         license_key=licenseKey,  # Changed to licenseKey
#         validity_start_date=validity_start_date,
#         validity_end_date=validity_end_date,
#         vendor=vendor,
#         assigned_to=assigned_to if user else None,
#         status=status,
#         subscription_type=Subscription_type,  # Changed to Subscription_type
#         amount=amount
#     )

#     try:
#         db.session.add(new_asset)
#         db.session.commit()

#         return jsonify({
#             'message': f"Intangible asset '{name}' added successfully.",
#             'asset_details': {
#                 'asset_id': new_asset.id,
#                 'name': new_asset.name,
#                 'licenseKey': new_asset.license_key,  # Changed to licenseKey
#                 'assigned_to': assigned_to if user else None,
#                 'status': new_asset.status,
#                 'Subscription_type': new_asset.subscription_type,  # Changed to Subscription_type
#                 'amount': new_asset.amount
#             }
#         }), 200

#     except Exception as e:
#         db.session.rollback()
#         return jsonify({'error': str(e)}), 400



from datetime import datetime

def parse_date(date_str):
    if date_str:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    return None


@app.route('/add_intangible_asset', methods=['POST'])
def add_intangible_asset():
    data = request.get_json()

    name = data.get('name')
    assigned_to = data.get('assignedTo')

    if not name:
        return jsonify({'error': 'Asset name is required'}), 400

    # Validate user
    user = None
    if assigned_to:
        user = User.query.get(assigned_to)
        if not user:
            return jsonify({'error': f'User with ID {assigned_to} not found'}), 404

    try:
        new_asset = IntangibleAsset(

            # Basic
            name=name,
            type=data.get('type'),
            category=data.get('category'),

            # Dates
            purchase_date=parse_date(data.get('purchaseDate')),
            warranty_period=parse_date(data.get('warrantyPeriod')),
            validity_start_date=parse_date(data.get('validityStartDate')),
            validity_end_date=parse_date(data.get('validityEndDate')),
            renewal_date=parse_date(data.get('renewalDate')),

            # Status
            status=data.get('status'),
            approval_status=data.get('approvalStatus'),

            # FK
            assigned_to=assigned_to if user else None,

            # Other
            created_by=data.get('createdBy'),
            assigner_location=data.get('assignerLocation'),

            # Employee snapshot
            employee_name=data.get('employeeName'),
            employee_contact_number=data.get('employeeContactNumber'),
            employment_type=data.get('employmentType'),
            employee_location=data.get('employeeLocation'),

            # Subscription
            subscription_type=data.get('subscriptionType'),

            # Financial
            amount_paid=data.get('amountPaid'),

            # Vendor
            vendor=data.get('vendor'),
            license_key=data.get('licenseKey')
        )

        db.session.add(new_asset)
        db.session.commit()

        return jsonify({
            "message": "Intangible asset added successfully",
            "asset": {
                "id": new_asset.id,
                "name": new_asset.name,
                "assignedTo": new_asset.assigned_to,
                "status": new_asset.status
            }
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400


@app.route('/intangible_assets', methods=['GET'])
def get_all_intangible_assets():
    # Fetch all intangible assets from the database
    assets = IntangibleAsset.query.all()

    if not assets:
        return jsonify({'message': 'No intangible assets found'}), 404

    # Serialize asset data
    asset_list = [
        {
            'id': asset.id,
            'name': asset.name,
            'license_key': asset.license_key,
            'validity_start_date': asset.validity_start_date.strftime('%Y-%m-%d') if asset.validity_start_date else None,
            'validity_end_date': asset.validity_end_date.strftime('%Y-%m-%d') if asset.validity_end_date else None,
            'vendor': asset.vendor,
            'assigned_to': asset.assigned_user.name if asset.assigned_user else None,   # User ID of the assigned user
            'status': asset.status,
            'subscription_type': asset.subscription_type
        }
        for asset in assets
    ]

    return jsonify({'intangible_assets': asset_list}), 200







@app.route('/update_intangible_asset/<int:asset_id>', methods=['POST', 'PUT', 'PATCH'])
@app.route('/api/update_intangible_asset/<int:asset_id>', methods=['POST', 'PUT', 'PATCH'])
def update_intangible_asset(asset_id):
    try:
        # Fetch the asset by ID
        asset = IntangibleAsset.query.get(asset_id)

        if not asset:
            return jsonify({'error': 'Intangible asset not found'}), 404

        # Get request data
        data = request.json

        # Update fields (excluding `assigned_to` if necessary)
        if 'name' in data:
            asset.name = data['name']
        if 'license_key' in data:
            asset.license_key = data['license_key']
        if 'validity_start_date' in data:
            asset.validity_start_date = datetime.strptime(data['validity_start_date'], '%Y-%m-%d').date()
        if 'validity_end_date' in data:
            asset.validity_end_date = datetime.strptime(data['validity_end_date'], '%Y-%m-%d').date()
        if 'vendor' in data:
            asset.vendor = data['vendor']
        if 'status' in data:
            asset.status = data['status']
        if 'subscription_type' in data:
            asset.subscription_type = data['subscription_type']  # Update subscription_type

        # Commit changes to the database
        db.session.commit()

        return jsonify({'message': 'Intangible asset updated successfully'}), 200

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/edit_employee_status/<int:employee_id>', methods=['PUT'])
def edit_employee_status(employee_id):
    data = request.get_json()
    new_status = data.get('status')

    if not new_status:
        return jsonify({'error': 'Status is required.'}), 400

    # Fetch the employee
    employee = Employee.query.get(employee_id)
    if not employee:
        return jsonify({'error': f'Employee with ID {employee_id} not found.'}), 404

    try:
        # Update the employee's status
        employee.status = new_status

        # If the status is 'left', update related products and intangible assets
        if new_status.lower() == 'left':
            # Update products assigned to the employee
            Product.query.filter_by(employee_id=employee_id).update({
                'status': 'Available',
                'employee_id': None
            })

            # Update intangible assets assigned to the employee
            IntangibleAsset.query.filter_by(assigned_to=employee_id).update({
                'assigned_to': None
            })

        # Commit the changes to the database
        db.session.commit()

        return jsonify({
            'message': f"Employee status updated successfully to '{new_status}'.",
            'employee_id': employee.id
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({'error': str(e)}), 400











from flask import request, jsonify
from datetime import datetime

# @app.route('/employees', methods=['GET'])
# def get_employees():
#     # Retrieve optional query parameters
#     status = request.args.get('status', type=str)
#     designation = request.args.get('designation', type=str)

#     try:
#         # Build the query for filtering employees
#         query = Employee.query

#         if status is not None:
#             query = query.filter_by(status=status)

#         if designation is not None:
#             query = query.filter_by(designation=designation)

#         # Fetch the employees
#         employees = query.all()

#         # Serialize the employee data
#         employees_data = []
#         for employee in employees:
#             employees_data.append({
#                 'id': employee.id,
#                 'name': employee.name,
#                 'designation': employee.designation,
#                 'email': employee.email,
#                 'status': employee.status
#             })

#         return jsonify({'employees': employees_data}), 200

#     except Exception as e:
#         return jsonify({'error': str(e)}), 500

from datetime import date
@app.route('/add_repairs', methods=['POST'])
def create_repair():
    try:
        data = request.get_json()

        # Validate required fields
        if not all(key in data for key in ["issue_description", "product_id", "user_id"]):
            return jsonify({"error": "Missing required fields"}), 400

        # Create a new repair record with today's date
        new_repair = Repair(
            issue_description=data["issue_description"],
            product_id=data["product_id"],
            user_id=data["user_id"],
            status="In Repair",
            repair_date=date.today(),  # Auto-set today's date
        )

        # Save to database
        db.session.add(new_repair)
        db.session.commit()

        return jsonify({
            "message": "Repair record created successfully",
            "repair_id": new_repair.id,
            "repair_date": new_repair.repair_date.strftime("%Y-%m-%d")  # Return formatted date
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500

from datetime import datetime

@app.route('/edit_repair_status/<int:repair_id>', methods=['POST'])
def edit_repair_status(repair_id):
    data = request.get_json()

    if 'status' not in data:
        return jsonify({'message': 'Status is required'}), 400

    repair = Repair.query.get(repair_id)
    if not repair:
        return jsonify({'message': 'Repair record not found'}), 404

    repair.status = data['status']
    repair.message = data.get('message') if 'message' in data else None

    # ✅ Update return_date if provided
    if 'return_date' in data and data['return_date']:
        try:
            repair.return_date = datetime.strptime(data['return_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({'message': 'Invalid return_date format. Use YYYY-MM-DD'}), 400

    db.session.commit()

    return jsonify({
        'message': 'Repair status updated successfully',
        'repair_id': repair.id,
        'status': repair.status,
        'message': repair.message,
        'return_date': repair.return_date.isoformat() if repair.return_date else None
    }), 200



@app.route('/add_additional_asset', methods=['POST'])
def add_additional_asset():
    # Get the data from the request
    data = request.get_json()

    # Check if required fields are present
    if not data.get('product_name') or not data.get('purchase_no') or not data.get('company'):
        return jsonify({'message': 'Product name, company, and purchase number are required'}), 400

    # Set default values if not provided
    status = data.get('status', 'Pending')
    approval_status = data.get('approval_status', 'Pending')  # Default approval_status to 'Pending'

    # Create a new AdditionalAsset instance with the provided details
    new_asset = AdditionalAsset(
        name=data['product_name'],
        number=data['purchase_no'],
        company=data['company'],
        status=status,
        approval_status=approval_status
    )

    # Add the new asset to the database
    db.session.add(new_asset)
    db.session.commit()

    # Return a success response
    return jsonify({
        'message': 'Additional asset added successfully',
        'asset': {
            'id': new_asset.id,
            'name': new_asset.name,
            'number': new_asset.number,
            'company': new_asset.company,
            'status': new_asset.status,
            'approval_status': new_asset.approval_status
        }
    }), 201




@app.route('/get_repairs', methods=['GET'])
def get_all_repairs():
    try:
        # Fetch all repair records
        repairs = Repair.query.all()

        # Convert each repair record to a dictionary
        repair_list = []
        for repair in repairs:
            repair_list.append({
                "id": repair.id,
                "issue_description": repair.issue_description,
                "repair_center": repair.repair_center,
                "repair_date": repair.repair_date.strftime("%Y-%m-%d") if repair.repair_date else None,
                "return_date": repair.return_date.strftime("%Y-%m-%d") if repair.return_date else None,
                "status": repair.status,
                "message": repair.message,
                "product_id": repair.product_id,
                "user_id": repair.user_id
            })

        return jsonify({"repairs": repair_list}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/update_approval_status/<int:asset_id>', methods=['POST'])
def update_approval_status(asset_id):
    # Get the data from the request
    data = request.get_json()

    # Validate if 'approval_status' is provided in the request
    if 'approval_status' not in data:
        return jsonify({'message': 'Approval status is required'}), 400

    # Ensure the provided status is valid
    valid_statuses = ['Approved', 'Rejected']
    if data['approval_status'] not in valid_statuses:
        return jsonify({'message': f'Invalid approval status. Must be one of {valid_statuses}'}), 400

    # Find the asset by ID
    asset = AdditionalAsset.query.get(asset_id)
    if not asset:
        return jsonify({'message': 'Asset not found'}), 404

    # Update approval_status
    asset.approval_status = data['approval_status']
    db.session.commit()

    # Return success response
    return jsonify({
        'message': f'Asset approval status updated to {asset.approval_status}',
        'asset': {
            'id': asset.id,
            'name': asset.name,
            'number': asset.number,
            'company': asset.company,
            'status': asset.status,
            'approval_status': asset.approval_status
        }
    }), 200



@app.route('/pending_approval_assets', methods=['GET'])
def get_pending_approval_assets():
    # Query all assets where approval_status is 'Pending'
    pending_assets = AdditionalAsset.query.all()

    # Convert the result to a list of dictionaries
    assets_list = [
        {
            'id': asset.id,
            'name': asset.name,
            'number': asset.number,
            'company': asset.company,
            'status': asset.status,
            'approval_status': asset.approval_status
        }
        for asset in pending_assets
    ]

    # Return the list of pending assets
    return jsonify({'pending_assets': assets_list}), 200






@app.route('/update_asset_status/<int:asset_id>', methods=['PUT'])
def update_asset_status(asset_id):
    # Get the asset by its ID
    asset = AdditionalAsset.query.get(asset_id)

    # If the asset does not exist, return a 404 error
    if not asset:
        return jsonify({'message': 'Asset not found'}), 404

    # Update the status to 'Approved'
    asset.status = 'Approved'

    # Commit the changes to the database
    db.session.commit()

    # Return a success response
    return jsonify({
        'message': 'Asset status updated to Approved',
        'asset': {
            'id': asset.id,
            'name': asset.name,
            'number': asset.number,
            'status': asset.status
        }
    }), 200

@app.route('/get_pending_assets', methods=['GET'])
def get_pending_assets():
    # Query the database for assets with status 'Pending'
    pending_assets = AdditionalAsset.query.filter_by(status='Pending').all()

    # If no pending assets are found, return a message
    if not pending_assets:
        return jsonify({'message': 'No pending assets found'}), 404

    # Prepare the response with the details of the pending assets
    assets_data = [{
        'id': asset.id,
        'name': asset.name,
        'number': asset.number,
        'status': asset.status
    } for asset in pending_assets]

    # Return the response with the list of pending assets
    return jsonify({
        'message': 'Pending assets fetched successfully',
        'assets': assets_data
    }), 200

@app.route('/logout', methods=['POST'])
def logout():
    return jsonify({"message": "Logout successful!"}), 200


@app.route('/api/product_counts', methods=['GET'])
def get_product_counts():
    product_counts = db.session.query(Product.product_name, db.func.count(Product.id)).group_by(Product.product_name).all()
    
    result = {name: count for name, count in product_counts}

    return jsonify(result)


@app.route('/api/employees/products', methods=['GET'])
def get_all_users_products():
    users = User.query.all()  # Changed 'user' to 'User'
    
    result = []
    for user in users:
        assigned_products = Product.query.filter_by(user_id=user.id).all()  # Assuming employee_id should be user_id
        products_list = [{
            "id": product.id,
            "product_name": product.product_name,
            "serial_number": product.serial_number,
            "company": product.company,
            "status": product.status,
            "condition": product.condition
        } for product in assigned_products]

        result.append({
            "user": {
                "id": user.id,
                "name": user.name,
                "email": user.email,
                "department": DEFAULT_USER_ROLE,  # Single supported role
                "role": DEFAULT_USER_ROLE
            },
            "assigned_products": products_list
        })

    return jsonify(result)

@app.route('/employees', methods=['GET'])
def get_employees():
    employees = User.query.order_by(User.id.asc()).all()
    employee_list = [
        {
            'id': emp.id,
            'name': emp.name,
            'username': emp.username,
            'email': emp.email,
            'phone_number': emp.phone_number,
            'department': DEFAULT_USER_ROLE,
            'role': DEFAULT_USER_ROLE
        }
        for emp in employees
    ]
    return jsonify({'employees': employee_list})


@app.route('/api/reports/intangible_summary', methods=['GET'])
def get_all_intangible_reports():
    print(f"Raw request args: {request.args}")  # Debugging

    # Fetch data from intangible_assets table along with assigned user's name
    intangible_summaries = db.session.execute(
        text("""
        SELECT
            ia.name AS subscription_name, 
            ia.validity_start_date, 
            ia.validity_end_date AS renewal_date, 
            ia.amount,
            u.name AS assigned_user  -- Fetch assigned user's name
        FROM intangible_assets ia
        LEFT JOIN "user" u ON ia.assigned_to = u.id;  -- Join with user table
        """)
    ).fetchall()

    print("Fetched data:", intangible_summaries)  # Debugging

    if not intangible_summaries:
        return jsonify({'message': 'No intangible asset data found'}), 404

    # Format response
    report = [
        {
            "subscription_name": item.subscription_name,
            "validity_start_date": str(item.validity_start_date),
            "renewal_date": str(item.renewal_date),
            "amount": item.amount,
            "assigned_to": item.assigned_user if item.assigned_user else "Unassigned"  # Handle unassigned assets
        }
        for item in intangible_summaries
    ]

    return jsonify({'intangible_assets': report}), 200







# @app.route('/api/reports/product_summary', methods=['GET'])
# def get_all_product_reports():
#     print(f"Raw request args: {request.args}")  # Debugging

#     # Fetch product details with assigned user and repair status
#     product_summaries = db.session.execute(
#         text("""
#         SELECT
#             p.id AS product_id,
#             p.product_name,
#             p.status,
#             p.user_id,
#             u.name AS assigned_to,
#             r.id AS repair_id  -- If repair_id exists, product is under repair
#         FROM products p
#         LEFT JOIN "user" u ON p.user_id = u.id
#         LEFT JOIN repairs r ON p.id = r.product_id;
#         """)
#     ).fetchall()

#     print("Fetched data:", product_summaries)  # Debugging

#     if not product_summaries:
#         return jsonify({'message': 'No product data found'}), 404

#     # Dictionary to store product reports
#     report = {}
#     for product in product_summaries:
#         name = product.product_name
#         user_id = product.user_id
#         assigned_to = product.assigned_to
#         is_in_repair = product.repair_id is not None  # Check if product is under repair

#         if name not in report:
#             report[name] = {
#                 'name': name,
#                 'total_count': 0,
#                 'assigned_count': 0,
#                 'available_count': 0,
#                 'in_repair_count': 0,
#                 'assigned_to': []  # List of assigned users
#             }

#         # Always increment total count
#         report[name]['total_count'] += 1

#         # If product is in repair, update count
#         if is_in_repair:
#             report[name]['in_repair_count'] += 1

#         # If assigned, update assigned count
#         if user_id:
#             report[name]['assigned_count'] += 1
#             if assigned_to:
#                 report[name]['assigned_to'].append(assigned_to)

#     # Calculate available count
#     for item in report.values():
#         item['available_count'] = max(0, item['total_count'] - (item['assigned_count'] + item['in_repair_count']))

#     return jsonify({'products': list(report.values())}), 200

# @app.route('/additional_intangible_asset', methods=['POST'])
# def additional_intangible_asset():
#     data = request.get_json()

#     if not data.get('site_name') or not data.get('amount') or not data.get('months'):
#         return jsonify({'message': 'Site name, amount, and months are required'}), 400

#     approval_status = data.get('approval_status', 'Pending')

#     # ✅ Use the correct model here
#     new_asset = AdditionalIntangibleAsset(
#         site_name=data['site_name'],
#         amount=data['amount'],
#         months=data['months'],
#         approval_status=approval_status
#     )

#     db.session.add(new_asset)
#     db.session.commit()

#     return jsonify({
#         'message': 'Intangible asset request raised successfully',
#         'asset': {
#             'site_name': new_asset.site_name,
#             'amount': new_asset.amount,
#             'months': new_asset.months,
#             'approval_status': new_asset.approval_status
#         }
#     }), 201

@app.route('/api/reports/product_summary', methods=['GET'])
def get_all_product_reports():
    print(f"Raw request args: {request.args}")  # Debugging

    # Fetch product details with assigned user and repair status
    product_summaries = db.session.execute(
        text("""
        SELECT
            p.id AS product_id,
            p.product_name,
            p.status,
            p.user_id,
            u.name AS assigned_to,
            r.id AS repair_id  -- If repair_id exists, product is under repair
        FROM products p
        LEFT JOIN "user" u ON p.user_id = u.id
        LEFT JOIN repairs r ON p.id = r.product_id;
        """)
    ).fetchall()

    print("Fetched data:", product_summaries)  # Debugging

    if not product_summaries:
        return jsonify({'message': 'No product data found'}), 404

    # Dictionary to store product reports
    report = {}
    for product in product_summaries:
        name = product.product_name
        user_id = product.user_id
        assigned_to = product.assigned_to
        is_in_repair = product.repair_id is not None  # Check if product is under repair

        if name not in report:
            report[name] = {
                'name': name,
                'total_count': 0,
                'assigned_count': 0,
                'available_count': 0,
                'in_repair_count': 0,
                'assigned_to': []  # List of assigned users
            }

        # If product is assigned, update assigned count
        if user_id:
            report[name]['assigned_count'] += 1
            if assigned_to:
                report[name]['assigned_to'].append(assigned_to)

        # If product is in repair, update in repair count
        if is_in_repair:
            report[name]['in_repair_count'] += 1

        # Total count should be the sum of assigned and in repair
        report[name]['total_count'] = report[name]['assigned_count'] + report[name]['in_repair_count']

    # Calculate available count
    for item in report.values():
        item['available_count'] = max(0, item['total_count'] - (item['assigned_count'] + item['in_repair_count']))

    return jsonify({'products': list(report.values())}), 200


    
@app.route('/maintenance/schedule', methods=['POST'])
def schedule_maintenance():
    data = request.get_json()
    asset_id = data.get('asset_id')
    scheduled_by = data.get('scheduled_by')
    scheduled_date = data.get('scheduled_date')  
    remarks = data.get('remarks', 'General Maintenance')  # Default to 'General Maintenance' if no remarks are provided

    if not asset_id or not scheduled_by or not scheduled_date:
        return jsonify({"error": "asset_id, scheduled_by, and scheduled_date are required."}), 400

    asset = db.session.get(Product, asset_id)
    if asset:
        user = db.session.get(User, asset.user_id)
        if not user:
            return jsonify({"error": "User associated with the asset not found!"}), 404
        
        maintenance = Maintenance(
            asset_id=asset_id,
            scheduled_by=scheduled_by,
            maintenance_date=datetime.strptime(scheduled_date, '%Y-%m-%d'),
            remarks=remarks
        )
        db.session.add(maintenance)
        db.session.commit()

        # Send Maintenance Email Notification
        send_maintenance_email(user.email, asset.product_name, scheduled_date, remarks)
        
        return jsonify({"message": "Maintenance scheduled successfully and email notification sent!"})
    
    return jsonify({"error": "Asset not found!"}), 404

# Perform Maintenance API
@app.route('/maintenance/perform/<int:asset_id>', methods=['PUT'])
def perform_maintenance(asset_id):
    # Find the latest scheduled maintenance for the given asset
    maintenance = Maintenance.query.filter_by(asset_id=asset_id, status='Scheduled').first()

    if maintenance:
        maintenance.status = 'Completed'
        maintenance.remarks = request.json.get('remarks', maintenance.remarks)
        db.session.commit()

        # Send completion email to the associated user
        asset = Product.query.get(asset_id)
        user = User.query.get(asset.user_id)

        if user:
            send_maintenance_email(
                user.email,
                asset.product_name,
                maintenance.maintenance_date.strftime('%Y-%m-%d'),
                maintenance.remarks,
                completion=True  # Indicate it's a completion email
            )

        return jsonify({"message": "Maintenance completed successfully and email notification sent!"})

    return jsonify({"error": "No scheduled maintenance found for this asset!"}), 404


@app.route('/maintenance/history/<int:asset_id>', methods=['GET'])
def maintenance_history(asset_id):
    try:
        # Fetch maintenance records for the given asset ID
        maintenance_records = Maintenance.query.filter_by(asset_id=asset_id).all()

        if not maintenance_records:
            return jsonify({"message": "No maintenance records found for this asset."}), 404

        # Format maintenance history data
        history = [
            {
                "maintenance_id": record.id,
                "scheduled_by": record.scheduled_by,
                "maintenance_date": record.maintenance_date.strftime('%Y-%m-%d') if record.maintenance_date else "N/A",
                "remarks": record.remarks if record.remarks else "No remarks available",
                "status": record.status
            }
            for record in maintenance_records
        ]

        return jsonify({"maintenance_history": history}), 200

    except Exception as e:
        return jsonify({"error": f"An error occurred: {str(e)}"}), 500
    
# @app.route('/assets/request', methods=['POST'])
# def request_new_asset():
#     data = request.get_json()

#     name = data.get('product_name')
#     company = data.get('company')
#     amount = data.get('amount')
#     product_details = data.get('product_details')  # New field for additional product details

#     if not all([name, company, amount]):
#         return jsonify({"error": "All fields (name, company, amount) are required."}), 400
    
    

#     new_request = NewAssetRequests(
        
#         name=name,
#         company=company,
#         amount=amount,
#         product_details=product_details,  # Storing product details
#         status="Approval Pending"  # Default status when requested
#     )

#     db.session.add(new_request)
#     db.session.commit()

#     return jsonify({"message": "Asset request submitted successfully!", "request_id": new_request.id})

@app.route('/assets/request', methods=['POST'])
def request_new_asset():
    data = request.get_json()

    name = data.get('product_name')
    company = data.get('company')
    amount = data.get('amount')
    product_details = data.get('product_details')
    asset_type = data.get('assetType')  # ✅ Handle camelCase from frontend

    if not all([name, company, amount]):
        return jsonify({"error": "All fields (name, company, amount) are required."}), 400

    new_request = NewAssetRequests(
        name=name,
        company=company,
        amount=amount,
        product_details=product_details,
        asset_type=asset_type,
        status="Approval Pending"
    )

    db.session.add(new_request)
    db.session.commit()

    return jsonify({"message": "Asset request submitted successfully!", "request_id": new_request.id})



# @app.route('/assets/decision/<int:request_id>', methods=['PUT'])
# def approve_or_reject_asset(request_id):
#     data = request.get_json()
#     status = data.get('status')  # Expecting "Approved" or "Rejected"

#     if status not in ["Approved", "Rejected"]:
#         return jsonify({"error": "Invalid status. Use 'Approved' or 'Rejected'."}), 400

#     asset_request = NewAssetRequests.query.get(request_id)

#     if not asset_request:
#         return jsonify({"error": "Asset request not found!"}), 404

#     if asset_request.status in ["Approved", "Rejected"]:
#         return jsonify({"message": f"Asset request is already {asset_request.status.lower()}."})

#     # Update status
#     asset_request.status = status
#     db.session.commit()

#     return jsonify({"message": f"Asset request {status.lower()} successfully!"})


@app.route('/assets/decision/<int:request_id>', methods=['POST'])
def approve_or_reject_asset(request_id):
    data = request.get_json()
    status = data.get('status')  # Expecting "Approved" or "Rejected"

    if status not in ["Approved", "Rejected"]:
        return jsonify({"error": "Invalid status. Use 'Approved' or 'Rejected'."}), 400

    asset_request = NewAssetRequests.query.get(request_id)

    if not asset_request:
        return jsonify({"error": "Asset request not found!"}), 404

    if asset_request.status == "Approved":
        return jsonify({"message": "Asset request is already approved and cannot be modified."})

    # **Update status**
    asset_request.status = status
    db.session.commit()

    # Single-role setup: notify the first available user account.
    recipient_user = User.query.order_by(User.id.asc()).first()

    if recipient_user:
        send_decision_email(
            recipient_user.email,
            asset_request.name,
            asset_request.company,
            asset_request.amount,
            asset_request.product_details,
            status
        )

    return jsonify({"message": f"Asset request {status.lower()} successfully!"})

# **Function to Send Email**
def send_decision_email(recipient_email, asset_name, company, amount, product_details, status):
    subject = f"Asset Request {status}"
    body = f"""
    Dear Higher Management,

    An asset request has been {status.lower()}:

    Product Name: {asset_name}
    Company: {company}
    Amount: {amount}
    Product Details: {product_details}

    Best Regards,
    Asset Management Team
    """
    
    msg = Message(subject, recipients=[recipient_email])
    msg.body = body
    mail.send(msg)
    
@app.route('/api/assets/monitor', methods=['GET'])
def monitor_assets():
    # Fetch product details along with assigned user
    products = db.session.query(
        Product.id,
        Product.product_name,
        Product.serial_number,
        Product.company,
        Product.status,  # Directly taking status from Product table
        Product.condition,
        Product.location,
        Product.user_id,
        User.name.label('assigned_to')
    ).outerjoin(User, Product.user_id == User.id).all()

    if not products:
        return jsonify({'message': 'No asset data found'}), 404

    # Formatting the response
    asset_data = [
        {
            "product_id": product.id,
            "product_name": product.product_name,
            "serial_number": product.serial_number,
            "company": product.company,
            "status": product.status,  # Directly using status from Product table
            "condition": product.condition,
            "location": product.location,
            "assigned_to": product.assigned_to if product.assigned_to else "Not Assigned"
        }
        for product in products
    ]

    return jsonify({"assets": asset_data}), 200

@app.route('/api/asset/<int:product_id>', methods=['GET'])
def monitor_asset(product_id):
    product = db.session.query(
        Product.id,
        Product.product_name,
        Product.serial_number,
        Product.company,
        Product.status,  # Directly using status from Product table
        Product.condition,
        Product.location,
        Product.user_id,
        User.name.label('assigned_to')
    ).outerjoin(User, Product.user_id == User.id) \
     .filter(Product.id == product_id) \
     .first()

    if not product:
        return jsonify({'message': 'Product not found'}), 404

    # Use product status directly
    asset_data = {
        "product_id": product.id,
        "product_name": product.product_name,
        "serial_number": product.serial_number,
        "company": product.company,
        "status": product.status,  # No manual status calculation
        "condition": product.condition,
        "location": product.location,
        "assigned_to": product.assigned_to if product.assigned_to else "Not Assigned"
    }

    return jsonify(asset_data), 200

from sqlalchemy.sql import func


@app.route('/api/reports/location_summary', methods=['GET'])
def get_location_summary():
    # Query to count assets grouped by location
    location_assets = db.session.query(
        Product.location, func.count(Product.id)
    ).group_by(Product.location).all()

    # Query to count users grouped by location (users assigned to products)
    location_users = db.session.query(
        Product.location, func.count(func.distinct(User.id)), func.array_agg(User.name)
    ).join(User, Product.user_id == User.id, isouter=True) \
     .group_by(Product.location).all()

    # Convert query results into dictionaries
    asset_report = {location if location else "Unknown Location": count for location, count in location_assets}
    
    user_report = {}
    for location, user_count, user_list in location_users:
        key = location if location else "Unknown Location"
        user_report[key] = {
            "user_count": user_count,
            "users": user_list if user_list else ["No Assigned Users"]
        }

    return jsonify({"location_report": asset_report, "user_report": user_report}), 200


@app.route('/api/assets', methods=['GET'])
def get_assets():
    assets = NewAssetRequests.query.all()
   
    # Convert query results into a list of dictionaries
    assets_list = [{
        "id": asset.id,
        "name": asset.name,
        "company": asset.company,
        "amount": asset.amount,
        "status": asset.status,
        "product_details": asset.product_details,
        "asset_type": asset.asset_type  # ✅ Include asset type in response
    } for asset in assets]
    return jsonify(assets_list), 200


@app.route('/get-intangible-assets', methods=['GET'])
def get_intangible_assets():
    assets = AdditionalIntangibleAsset.query.all()  # ✅ Use the correct model name
    asset_list = [
        {
            "id": asset.id,
            "site_name": asset.site_name,
            "amount": asset.amount,
            "months": asset.months,
            "approval_status": asset.approval_status
        }
        for asset in assets
    ]
    return jsonify(asset_list)

# @app.route('/intangible-assets/<int:asset_id>', methods=['POST'])
# def update_approval_statuss(asset_id):
#     data = request.get_json()
#     new_status = data.get('approval_status')

#     if new_status not in ['Approve', 'Reject']:
#         return jsonify({"error": "Invalid status. Use 'Approve' or 'Reject'."}), 400

#     asset = AdditionalIntangibleAsset.query.get(asset_id)
    
#     if not asset:
#         return jsonify({"error": "Asset not found"}), 404

#     asset.approval_status = new_status
#     db.session.commit()

#     return jsonify({"message": f"Approval status updated to {new_status}"}), 200



# Helper function to send approval/rejection email
def send_approval_rejection_email(asset, status):
    subject = f"Asset Approval Status - {status.capitalize()}"
    body = f"The approval status of the asset '{asset.site_name}' has been {status.lower()}.\n\n" \
           f"Asset Amount: {asset.amount}\nMonths: {asset.months}\nApproval Status: {status.capitalize()}"
    recipient = 'prasanthgutha2002@gmail.com'  # Replace with HR email

    msg = Message(subject, recipients=[recipient])
    msg.body = body

    try:
        mail.send(msg)
        print(f"Email sent to HR about asset {asset.id} being {status}.")
    except Exception as e:
        print(f"Failed to send email: {str(e)}")

# Route to update approval status of intangible asset

@app.route('/intangible-assets/<int:asset_id>', methods=['POST'])
def update_approval_statuss(asset_id):
    data = request.get_json()
    new_status = data.get('approval_status')

    if new_status not in ['Approve', 'Reject']:
        return jsonify({"error": "Invalid status. Use 'Approve' or 'Reject'."}), 400

    # Get the asset by ID
    asset = AdditionalIntangibleAsset.query.get(asset_id)
    
    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    # Update approval status
    asset.approval_status = new_status
    db.session.commit()

    # Send the email notification to HR
    send_approval_rejection_email(asset, new_status.lower())

    return jsonify({"message": f"Approval status updated to {new_status}"}), 200

# if __name__ == "__main__":
#     app.run(host='0.0.0.0', port=5002)

@app.route('/assign-intangible-assets/<int:user_id>', methods=['POST'])
def assign_user_by_id(user_id):
    data = request.get_json()
    asset_id = data.get("asset_id")
    assigned_to_name = data.get("assigned_to")

    if not asset_id or not assigned_to_name:
        return jsonify({"error": "asset_id and assigned_to (name) are required"}), 400

    asset = IntangibleAsset.query.get(asset_id)
    user = User.query.filter_by(name=assigned_to_name).first()

    if not asset:
        return jsonify({"error": "Asset not found"}), 404

    if not user:
        return jsonify({"error": "User not found with that name"}), 404

    asset.assigned_to = user.id
    db.session.commit()

    return jsonify({
        "message": f"Asset {asset_id} assigned to User {user.id}",
        "assigned_to": user.name
    }), 200




def seed_dummy_data():
    today = datetime.now().date()
    summary = {
        'users': 0,
        'products': 0,
        'repairs': 0,
        'intangible_assets': 0,
        'additional_assets': 0,
        'additional_intangible_assets': 0,
        'maintenance': 0,
        'new_asset_requests': 0,
    }

    def add_if_missing(model, filters, payload, summary_key):
        instance = model.query.filter_by(**filters).first()
        if instance:
            return instance

        instance = model(**payload)
        db.session.add(instance)
        db.session.flush()
        summary[summary_key] += 1
        return instance

    users_data = [
        {
            'name': 'Admin User',
            'username': 'admin_demo',
            'email': 'admin_demo@example.com',
            'phone_number': '9000000001',
            'password': generate_password_hash('Admin@123'),
            'department': DEFAULT_USER_ROLE,
        },
        {
            'name': 'Ravi Kumar',
            'username': 'ravi_emp',
            'email': 'ravi_emp@example.com',
            'phone_number': '9000000002',
            'password': generate_password_hash('Employee@123'),
            'department': DEFAULT_USER_ROLE,
        },
        {
            'name': 'Ananya Sharma',
            'username': 'ananya_tech',
            'email': 'ananya_tech@example.com',
            'phone_number': '9000000003',
            'password': generate_password_hash('Technician@123'),
            'department': DEFAULT_USER_ROLE,
        },
    ]

    extra_usernames = [f'demo_user_{index:02d}' for index in range(1, 11)]

    for index, username in enumerate(extra_usernames, start=1):
        users_data.append({
            'name': f'Demo User {index:02d}',
            'username': username,
            'email': f'{username}@example.com',
            'phone_number': f'91000001{index:02d}',
            'password': generate_password_hash(f'DemoUser@{index:02d}'),
            'department': DEFAULT_USER_ROLE,
        })

    products_data = [
        {
            'product_name': 'Dell Latitude 5440',
            'serial_number': 'DL-1001',
            'company': 'Dell',
            'assigned_username': 'ravi_emp',
            'purchase_date': today - timedelta(days=180),
            'status': 'Allocated',
            'condition': 'Good',
            'disposal_date': None,
            'location': 'Hyderabad',
        },
        {
            'product_name': 'HP ProBook 440',
            'serial_number': 'HP-1002',
            'company': 'HP',
            'assigned_username': None,
            'purchase_date': today - timedelta(days=90),
            'status': 'Available',
            'condition': 'New',
            'disposal_date': None,
            'location': 'Bengaluru',
        },
        {
            'product_name': 'Lenovo ThinkPad E14',
            'serial_number': 'LN-1003',
            'company': 'Lenovo',
            'assigned_username': 'ananya_tech',
            'purchase_date': today - timedelta(days=240),
            'status': 'Under Maintenance',
            'condition': 'Used',
            'disposal_date': None,
            'location': 'Chennai',
        },
    ]

    product_catalog = [
        ('Acer Aspire 5', 'Acer'),
        ('Asus Vivobook 15', 'Asus'),
        ('Dell Vostro 3520', 'Dell'),
        ('HP EliteBook 840', 'HP'),
        ('Lenovo IdeaPad Slim 3', 'Lenovo'),
    ]
    product_locations = ['Hyderabad', 'Bengaluru', 'Chennai', 'Pune', 'Mumbai']

    for index, username in enumerate(extra_usernames, start=1):
        product_name, company = product_catalog[(index - 1) % len(product_catalog)]
        status = 'Allocated' if index % 3 == 1 else 'Available' if index % 3 == 2 else 'Under Maintenance'
        products_data.append({
            'product_name': f'{product_name} Demo {index:02d}',
            'serial_number': f'DEMO-TA-{index:03d}',
            'company': company,
            'assigned_username': username if status != 'Available' else None,
            'purchase_date': today - timedelta(days=20 * index),
            'status': status,
            'condition': 'New' if status == 'Available' else 'Good' if status == 'Allocated' else 'Used',
            'disposal_date': None,
            'location': product_locations[(index - 1) % len(product_locations)],
        })

    repairs_data = [
        {
            'serial_number': 'LN-1003',
            'username': 'ananya_tech',
            'issue_description': 'Battery health degraded significantly',
            'repair_center': 'Lenovo Service Center',
            'repair_date': today - timedelta(days=4),
            'return_date': today + timedelta(days=3),
            'status': 'In Progress',
            'message': 'Awaiting spare part delivery',
        },
        {
            'serial_number': 'DL-1001',
            'username': 'ravi_emp',
            'issue_description': 'Keyboard replacement requested',
            'repair_center': 'Dell Care',
            'repair_date': today - timedelta(days=15),
            'return_date': today - timedelta(days=10),
            'status': 'Completed',
            'message': 'Keyboard replaced successfully',
        },
    ]

    intangible_assets_data = [
        {
            'name': 'Microsoft 365 Business',
            'license_key': 'M365-DEMO-001',
            'validity_start_date': today - timedelta(days=30),
            'validity_end_date': today + timedelta(days=335),
            'vendor': 'Microsoft',
            'assigned_username': 'ravi_emp',
            'status': 'active',
            'amount': Decimal('4999.00'),
            'subscription_type': 'Yearly',
        },
        {
            'name': 'Adobe Creative Cloud',
            'license_key': 'ADBE-DEMO-002',
            'validity_start_date': today - timedelta(days=120),
            'validity_end_date': today + timedelta(days=60),
            'vendor': 'Adobe',
            'assigned_username': 'ananya_tech',
            'status': 'active',
            'amount': Decimal('7999.00'),
            'subscription_type': 'Yearly',
        },
    ]

    intangible_vendors = ['Microsoft', 'Google', 'Adobe', 'Atlassian', 'Zoho']
    subscription_cycle = ['Monthly', 'Quarterly', 'Yearly']

    for index, username in enumerate(extra_usernames, start=1):
        status = 'expired' if index in (5, 10) else 'active'
        validity_end_date = today - timedelta(days=index) if status == 'expired' else today + timedelta(days=90 + (index * 15))
        intangible_assets_data.append({
            'name': f'Demo Software License {index:02d}',
            'license_key': f'DEMO-LIC-{index:03d}',
            'validity_start_date': today - timedelta(days=15 * index),
            'validity_end_date': validity_end_date,
            'vendor': intangible_vendors[(index - 1) % len(intangible_vendors)],
            'assigned_username': username,
            'status': status,
            'amount': Decimal(str(2500 + (index * 425))),
            'subscription_type': subscription_cycle[(index - 1) % len(subscription_cycle)],
        })

    additional_assets_data = [
        {
            'name': 'External Monitor',
            'number': 6,
            'status': 'Available',
            'company': 'LG',
            'approval_status': 'Approved',
        },
        {
            'name': 'Wireless Keyboard',
            'number': 10,
            'status': 'Requested',
            'company': 'Logitech',
            'approval_status': 'Pending',
        },
    ]

    additional_intangible_assets_data = [
        {
            'site_name': 'AWS Sandbox Subscription',
            'amount': 15000.0,
            'months': 12,
            'approval_status': 'Pending',
        },
        {
            'site_name': 'Figma Team Plan',
            'amount': 9000.0,
            'months': 6,
            'approval_status': 'Approve',
        },
    ]

    maintenance_data = [
        {
            'serial_number': 'DL-1001',
            'scheduled_by': 'ananya_tech@example.com',
            'maintenance_date': today + timedelta(days=5),
            'remarks': 'Quarterly preventive maintenance',
            'status': 'Scheduled',
        },
        {
            'serial_number': 'HP-1002',
            'scheduled_by': 'ananya_tech@example.com',
            'maintenance_date': today - timedelta(days=7),
            'remarks': 'Initial inspection completed',
            'status': 'Completed',
        },
    ]

    new_asset_requests_data = [
        {
            'name': 'MacBook Pro 14',
            'company': 'Apple',
            'amount': 185000.0,
            'status': 'Approval Pending',
            'product_details': 'Needed for iOS testing and build pipelines',
            'technician_username': 'ananya_tech',
            'asset_type': 'Laptop',
        },
        {
            'name': 'Jira Enterprise License',
            'company': 'Atlassian',
            'amount': 54000.0,
            'status': 'Approved',
            'product_details': 'Project management upgrade for engineering teams',
            'technician_username': 'admin_demo',
            'asset_type': 'Software',
        },
    ]

    try:
        db.create_all()

        users = {}
        for user_data in users_data:
            user = add_if_missing(User, {'username': user_data['username']}, user_data, 'users')
            users[user_data['username']] = user

        products = {}
        for product_data in products_data:
            payload = {
                'product_name': product_data['product_name'],
                'serial_number': product_data['serial_number'],
                'company': product_data['company'],
                'barcode': None,
                'user_id': users[product_data['assigned_username']].id if product_data['assigned_username'] else None,
                'purchase_date': product_data['purchase_date'],
                'status': product_data['status'],
                'condition': product_data['condition'],
                'disposal_date': product_data['disposal_date'],
                'location': product_data['location'],
            }
            product = add_if_missing(Product, {'serial_number': product_data['serial_number']}, payload, 'products')
            products[product_data['serial_number']] = product

        for repair_data in repairs_data:
            product = products[repair_data['serial_number']]
            user = users[repair_data['username']]
            repair = Repair.query.filter_by(
                product_id=product.id,
                user_id=user.id,
                issue_description=repair_data['issue_description']
            ).first()
            if repair:
                continue

            db.session.add(Repair(
                issue_description=repair_data['issue_description'],
                repair_center=repair_data['repair_center'],
                repair_date=repair_data['repair_date'],
                return_date=repair_data['return_date'],
                status=repair_data['status'],
                message=repair_data['message'],
                product_id=product.id,
                user_id=user.id,
            ))
            summary['repairs'] += 1

        for asset_data in intangible_assets_data:
            payload = {
                'name': asset_data['name'],
                'license_key': asset_data['license_key'],
                'validity_start_date': asset_data['validity_start_date'],
                'validity_end_date': asset_data['validity_end_date'],
                'vendor': asset_data['vendor'],
                'assigned_to': users[asset_data['assigned_username']].id if asset_data['assigned_username'] else None,
                'status': asset_data['status'],
                'amount': asset_data['amount'],
                'subscription_type': asset_data['subscription_type'],
            }
            add_if_missing(
                IntangibleAsset,
                {'license_key': asset_data['license_key']},
                payload,
                'intangible_assets'
            )

        for asset_data in additional_assets_data:
            existing_asset = AdditionalAsset.query.filter_by(
                name=asset_data['name'],
                company=asset_data['company']
            ).first()
            if existing_asset:
                continue

            db.session.add(AdditionalAsset(**asset_data))
            summary['additional_assets'] += 1

        for asset_data in additional_intangible_assets_data:
            existing_asset = AdditionalIntangibleAsset.query.filter_by(site_name=asset_data['site_name']).first()
            if existing_asset:
                continue

            db.session.add(AdditionalIntangibleAsset(**asset_data))
            summary['additional_intangible_assets'] += 1

        for maintenance_item in maintenance_data:
            product = products[maintenance_item['serial_number']]
            existing_record = Maintenance.query.filter_by(
                asset_id=product.id,
                maintenance_date=maintenance_item['maintenance_date']
            ).first()
            if existing_record:
                continue

            db.session.add(Maintenance(
                asset_id=product.id,
                scheduled_by=maintenance_item['scheduled_by'],
                maintenance_date=maintenance_item['maintenance_date'],
                remarks=maintenance_item['remarks'],
                status=maintenance_item['status'],
            ))
            summary['maintenance'] += 1

        for request_data in new_asset_requests_data:
            technician = users[request_data['technician_username']]
            existing_request = NewAssetRequests.query.filter_by(
                name=request_data['name'],
                technician_id=technician.id
            ).first()
            if existing_request:
                continue

            db.session.add(NewAssetRequests(
                name=request_data['name'],
                company=request_data['company'],
                amount=request_data['amount'],
                status=request_data['status'],
                product_details=request_data['product_details'],
                technician_id=technician.id,
                asset_type=request_data['asset_type'],
            ))
            summary['new_asset_requests'] += 1

        db.session.commit()
        return summary
    except Exception:
        db.session.rollback()
        raise



@app.route('/raise-request', methods=['POST'])
def raise_request():

    data = request.get_json()

    if not all(key in data for key in ['user_id', 'asset_type', 'asset_name', 'reason']):
        return jsonify({"error": "Missing required fields"}), 400

    request_data = AssetRequest(
        user_id=data['user_id'],
        asset_type=data['asset_type'],
        asset_name=data['asset_name'],
        reason=data['reason']
    )

    db.session.add(request_data)
    db.session.commit()

    return jsonify({
        "message": "Asset request created successfully",
        "request_id": request_data.id
    }), 201



@app.route('/manager-approval/<int:request_id>', methods=['POST'])
def manager_approval(request_id):

    data = request.get_json()

    req = AssetRequest.query.get(request_id)

    if not req:
        return jsonify({"error": "Request not found"}), 404

    req.manager_status = data['status']

    if data['status'] == "REJECTED":
        req.final_status = "REJECTED"

    db.session.commit()

    return jsonify({"message": "Manager approval updated"})



@app.route('/accounts-approval/<int:request_id>', methods=['POST'])
def accounts_approval(request_id):

    data = request.get_json()

    req = AssetRequest.query.get(request_id)

    if not req:
        return jsonify({"error": "Request not found"}), 404

    if req.manager_status != "APPROVED":
        return jsonify({"error": "Manager approval pending"}), 400

    req.accounts_status = data['status']

    if data['status'] == "APPROVED":
        req.final_status = "APPROVED"
    else:
        req.final_status = "REJECTED"

    db.session.commit()

    return jsonify({"message": "Accounts approval updated"})



@app.route('/accounts-approvals', methods=['GET'])
def get_accounts_approvals():

    requests = AssetRequest.query.filter(
        AssetRequest.manager_status == "APPROVED"
    ).all()

    result = []

    for req in requests:
        result.append({
            "request_id": req.id,
            "user_id": req.user_id,
            "asset_type": req.asset_type,
            "asset_name": req.asset_name,
            "reason": req.reason,
            "manager_status": req.manager_status,
            "accounts_status": req.accounts_status,
            "final_status": req.final_status
        })

    return jsonify(result), 200



@app.route('/manager-approvals', methods=['GET'])
def get_manager_approvals():

    requests = AssetRequest.query.all()

    result = []

    for req in requests:
        result.append({
            "request_id": req.id,
            "user_id": req.user_id,
            "asset_type": req.asset_type,
            "asset_name": req.asset_name,
            "reason": req.reason,
            "manager_status": req.manager_status,
            "accounts_status": req.accounts_status,
            "final_status": req.final_status
        })

    return jsonify(result), 200


@app.route('/hr-asset-request', methods=['POST'])
def create_hr_asset_request():

    data = request.get_json()

    if not all(key in data for key in ['user_id', 'requested_by', 'asset_type']):
        return jsonify({"error": "Missing required fields"}), 400

    new_request = HRAssetRequest(
        user_id=data['user_id'],
        requested_by=data['requested_by'],
        asset_type=data['asset_type'],
        created_at=datetime.utcnow()
    )

    db.session.add(new_request)
    db.session.commit()

    return jsonify({
        "message": "HR asset request created successfully",
        "request_id": new_request.id
    }), 201


@app.route('/get-hr-asset-requests', methods=['GET'])
def get_hr_asset_requests():

    requests = HRAssetRequest.query.all()

    result = []

    for req in requests:
        result.append({
            "request_id": req.id,
            "user_id": req.user_id,
            "requested_by": req.requested_by,
            "asset_type": req.asset_type,
            "status": req.status,
            "created_at": req.created_at
        })

    return jsonify(result), 200




@app.route('/raise-asset-request', methods=['POST'])
def raise_asset_request():

    data = request.get_json()

    new_request = EmployeeAssetRequest(
        user_id=data.get("user_id"),
        employee_id=data.get("employee_id"),
        asset_type=data.get("asset_type"),
        asset_name=data.get("asset_name"),
        department=data.get("department"),
        reason=data.get("reason"),
        required_from=data.get("required_from"),
        urgency=data.get("urgency")
    )

    db.session.add(new_request)
    db.session.commit()

    return jsonify({
        "message": "Asset request raised successfully",
        "request_id": new_request.id
    }), 201


@app.route('/hr-asset-requests', methods=['GET'])
def get_hr_requests():

    requests = EmployeeAssetRequest.query.all()

    result = []

    for r in requests:
        result.append({
            "request_id": r.id,
            "user_id": r.user_id,
            "employee_id": r.employee_id,
            "asset_type": r.asset_type,
            "asset_name": r.asset_name,
            "department": r.department,
            "reason": r.reason,
            "required_from": r.required_from,
            "urgency": r.urgency,
            "status": r.status
        })

    return jsonify(result), 200




@app.route('/hr-approve-request/<int:request_id>', methods=['POST'])
def hr_approve_request(request_id):

    data = request.get_json()
    status = data.get("status")

    if status not in ["APPROVED", "REJECTED"]:
        return jsonify({"error": "Invalid status"}), 400

    req = EmployeeAssetRequest.query.get(request_id)

    if not req:
        return jsonify({"error": "Request not found"}), 404

    req.status = status

    db.session.commit()

    return jsonify({
        "message": f"Request {status.lower()} successfully",
        "request_id": request_id,
        "status": status
    }), 200



@app.route('/employee-asset-requests/<int:user_id>', methods=['GET'])
def get_employee_requests(user_id):

    requests = EmployeeAssetRequest.query.filter_by(user_id=user_id).all()

    result = []

    for r in requests:
        result.append({
            "request_id": r.id,
            "asset_type": r.asset_type,
            "asset_name": r.asset_name,
            "department": r.department,
            "reason": r.reason,
            "required_from": r.required_from,
            "urgency": r.urgency,
            "status": r.status,
            "created_at": r.created_at
        })

    return jsonify(result), 200




@app.route('/itadmin_update_repair', methods=['POST'])
def itadmin_update_repair():

    data = request.get_json()

    issue_id = data.get("issue_id")

    repair = Repair.query.get(issue_id)

    if not repair:
        return jsonify({"error": "Repair issue not found"}), 404

    # Update fields
    repair.status = data.get("status", repair.status)
    repair.message = data.get("description", repair.message)

    db.session.commit()

    return jsonify({
        "message": "Repair status updated successfully",
        "issue_id": repair.id,
        "asset_name": data.get("asset_name"),
        "raised_by": data.get("raised_by"),
        "status": repair.status
    }), 200



@app.route('/initiate-exit', methods=['POST'])
def initiate_exit():

    data = request.get_json() or {}
    user_id = data.get("employee_id")

    if not user_id:
        return jsonify({"error": "employee_id is required"}), 400
    try:
        user_id = int(user_id)
    except (TypeError, ValueError):
        return jsonify({"error": "employee_id must be an integer"}), 400

    employee = User.query.get(user_id)
    if not employee:
        return jsonify({"error": f"Employee with ID {user_id} not found"}), 404

    products = Product.query.filter_by(user_id=user_id).all()
    for product in products:
        product.status = STATUS_RETURN_REQUESTED

    try:
        updated_intangible_assets = _update_intangible_assets_status_for_employee(
            user_id,
            employee.name,
            STATUS_RETURN_REQUESTED
        )

        if not products and not updated_intangible_assets:
            return jsonify({"message": "No assets assigned to this employee"}), 404

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

    updated_product_ids = [product.id for product in products]
    updated_intangible_ids = [asset['id'] for asset in updated_intangible_assets]

    return jsonify({
        "message": "Exit initiated. Employee must return assets.",
        "employee_id": user_id,
        "employee_name": employee.name,
        "status_set": STATUS_RETURN_REQUESTED,
        "updated_counts": {
            "products": len(updated_product_ids),
            "intangible_assets": len(updated_intangible_ids)
        },
        "updated_ids": {
            "products": updated_product_ids,
            "intangible_assets": updated_intangible_ids
        },
        "updated_assets": {
            "products": [
                {"id": product.id, "status": product.status}
                for product in products
            ],
            "intangible_assets": [
                {"id": asset['id'], "status": asset['status']}
                for asset in updated_intangible_assets
            ]
        }
    }), 200

@app.route('/employee-return-asset/<int:product_id>', methods=['POST'])
@app.route('/api/employee-return-asset/<int:product_id>', methods=['POST'])
def employee_return_asset(product_id):

    product = Product.query.get(product_id)

    if not product:
        return jsonify({"error": "Asset not found"}), 404

    product.status = STATUS_RETURNED

    db.session.commit()

    return jsonify({
        "message": "Asset returned by employee",
        "product_id": product_id,
        "status": product.status
    }), 200


@app.route('/employee-return-intangible-asset/<int:asset_id>', methods=['POST', 'PUT'])
@app.route('/api/employee-return-intangible-asset/<int:asset_id>', methods=['POST', 'PUT'])
def employee_return_intangible_asset(asset_id):
    try:
        updated_asset = _update_intangible_asset_status_by_id(asset_id, STATUS_RETURNED)
        if not updated_asset:
            return jsonify({"error": "Intangible asset not found"}), 404

        db.session.commit()
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500

    return jsonify({
        "message": "Intangible asset returned by employee",
        "intangible_asset_id": asset_id,
        "status": updated_asset['status']
    }), 200


@app.route('/verify-return/<int:product_id>', methods=['POST'])
def verify_return(product_id):

    product = Product.query.get(product_id)

    if not product:
        return jsonify({"error": "Asset not found"}), 404

    product.status = STATUS_AVAILABLE
    product.user_id = None

    db.session.commit()

    return jsonify({
        "message": "Asset verified and available for reuse"
    }), 200



@app.route('/mark-asset-obsolete/<int:product_id>', methods=['POST'])
def mark_asset_obsolete(product_id):

    product = Product.query.get(product_id)

    if not product:
        return jsonify({"error": "Asset not found"}), 404

    product.status = "OBSOLETE"

    db.session.commit()

    return jsonify({
        "message": "Asset marked as obsolete. Waiting for management approval.",
        "product_id": product_id,
        "status": "OBSOLETE"
    }), 200





@app.route('/management-approve-disposal/<int:product_id>', methods=['POST'])
def management_approve_disposal(product_id):

    product = Product.query.get(product_id)

    if not product:
        return jsonify({"error": "Asset not found"}), 404

    if product.status != "OBSOLETE":
        return jsonify({"error": "Asset must be marked OBSOLETE first"}), 400

    product.status = "DISPOSED"
    product.user_id = None

    db.session.commit()

    return jsonify({
        "message": "Asset disposal approved by management",
        "product_id": product_id,
        "status": "DISPOSED"
}), 200


if __name__ == "__main__":
    if '--seed-dummy-data' in sys.argv:
        with app.app_context():
            inserted_rows = seed_dummy_data()
            print('Dummy data seed completed successfully.')
            print(inserted_rows)
    else:
        app.run(host='0.0.0.0', port=5002, debug=True)


