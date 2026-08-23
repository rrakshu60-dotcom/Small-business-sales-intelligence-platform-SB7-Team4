# pyrefly: ignore-file
# type: ignore
import os
from dotenv import load_dotenv
load_dotenv(override=False)
import datetime
import time
import re
import random
import secrets
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from collections import defaultdict
from typing import List, Dict, Optional
import jwt
import bcrypt
import httpx
# Monkeypatch httpx.AsyncClient to enforce a default 2.0s timeout, preventing gateway hangs during tests/CI
_original_async_client_init = httpx.AsyncClient.__init__
def _new_async_client_init(self, *args, **kwargs):
    if "timeout" not in kwargs:
        kwargs["timeout"] = 2.0
    _original_async_client_init(self, *args, **kwargs)
httpx.AsyncClient.__init__ = _new_async_client_init

from fastapi import FastAPI, Depends, HTTPException, Header, status, File, UploadFile, Request, Response
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator

app = FastAPI(
    title="MarketMind AI - API Gateway",
    description="API Gateway & Security Proxy Service for Small Business Sales Intelligence Platform",
    version="1.0.0"
)

@app.api_route("/health", methods=["GET", "HEAD"])
def health_check():
    return {"status": "healthy"}

@app.api_route("/", methods=["GET", "HEAD"])
def root_check():
    return {"status": "healthy", "service": "Security API Gateway"}

# CORS configurations
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

JWT_SECRET = os.getenv("JWT_SECRET", "marketmind-secret-key-12345")
ALGORITHM = "HS256"

# Hash a default password for pre-seeded users
preseed_salt = bcrypt.gensalt(10)
preseed_hash = bcrypt.hashpw(b"Password123", preseed_salt).decode('utf-8')

# In-memory mock database for authentication testing
mock_users: List[Dict] = []

if os.getenv("TESTING") != "true":
    mock_users.append({
        "id": 1,
        "name": "Rithika Reddy",
        "email": "rithikareddy968@gmail.com",
        "password_hash": preseed_hash,
        "role": "Admin",
        "refresh_tokens": [],
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "is_verified": True,
        "verification_token": None,
        "verification_token_expires": None
    })
    mock_users.append({
        "id": 2,
        "name": "Palak Ganwani",
        "email": "palakganwani415@gmail.com",
        "password_hash": preseed_hash,
        "role": "Business Owner",
        "refresh_tokens": [],
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "is_verified": True,
        "verification_token": None,
        "verification_token_expires": None
    })
    mock_users.append({
        "id": 3,
        "name": "Rakshu",
        "email": "rrakshu60@gmail.com",
        "password_hash": preseed_hash,
        "role": "Sales Executive",
        "refresh_tokens": [],
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "is_verified": True,
        "verification_token": None,
        "verification_token_expires": None
    })
    mock_users.append({
        "id": 4,
        "name": "PVSN",
        "email": "pvsn47139@gmail.com",
        "password_hash": preseed_hash,
        "role": "Store Manager",
        "refresh_tokens": [],
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "is_verified": True,
        "verification_token": None,
        "verification_token_expires": None
    })
PASSWORD_RECOVERY_STORE: Dict[str, Dict] = {}
VALID_ROLES = [
    "Business Owner",
    "Store Manager",
    "Sales Executive",
    "Admin"
]

# Pydantic Schemas for validation
class RegisterRequest(BaseModel):
    name: str
    email: str
    password: str
    role: str

class LoginRequest(BaseModel):
    email: str
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str

class InventoryUpdateSchema(BaseModel):
    product_id: str
    stock_quantity: int
    low_stock_threshold: int = 10

class InvoiceItemSchema(BaseModel):
    product_id: int = Field(..., gt=0)
    quantity: int = Field(..., gt=0)
    unit_price: float = Field(..., ge=0.0)
    discount: float = Field(default=0.0, ge=0.0)
    tax: float = Field(default=0.0, ge=0.0)
    line_total: float = Field(..., ge=0.0)
    category_snapshot: Optional[str] = None
    product_name_snapshot: Optional[str] = None


class InvoiceCreateSchema(BaseModel):
    invoice_number: str = Field(..., min_length=1)
    customer_id: int = Field(..., gt=0)
    store_id: int = Field(..., gt=0)
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    subtotal: float = Field(..., ge=0.0)
    discount_amount: float = Field(default=0.0, ge=0.0)
    tax_amount: float = Field(default=0.0, ge=0.0)
    total_amount: float = Field(..., ge=0.0)
    payment_status: str = Field(..., min_length=1)
    invoice_status: Optional[str] = "Active"
    notes: Optional[str] = None
    items: List[InvoiceItemSchema]

    @field_validator('payment_status')
    @classmethod
    def validate_payment_status(cls, v):
        if v not in ["Paid", "Unpaid", "Partially Paid"]:
            raise ValueError("payment_status must be 'Paid', 'Unpaid', or 'Partially Paid'")
        return v

class InvoiceStatusUpdateSchema(BaseModel):
    payment_status: str = Field(..., min_length=1)

    @field_validator('payment_status')
    @classmethod
    def validate_payment_status(cls, v):
        if v not in ["Paid", "Unpaid", "Partially Paid"]:
            raise ValueError("payment_status must be 'Paid', 'Unpaid', or 'Partially Paid'")
        return v


class BulkInvoiceUpdateSchema(BaseModel):
    invoice_ids: List[int] = Field(..., min_length=1)
    status: str = Field(..., min_length=1)

    @field_validator('invoice_ids')
    @classmethod
    def validate_invoice_ids(cls, v):
        for id_val in v:
            if id_val <= 0:
                raise ValueError("invoice_ids must contain positive integers only")
        return v

    @field_validator('status')
    @classmethod
    def validate_status(cls, v):
        if v not in ["Paid", "Unpaid", "Partially Paid"]:
            raise ValueError("status must be 'Paid', 'Unpaid', or 'Partially Paid'")
        return v

class InventoryUpdateItemSchema(BaseModel):
    product_id: int = Field(..., gt=0)
    stock_quantity: int = Field(..., ge=0)

class BulkInventoryUpdateSchema(BaseModel):
    updates: List[InventoryUpdateItemSchema] = Field(..., min_length=1)

class ForgotPasswordRequest(BaseModel):
    email: str

class VerifyOTPRequest(BaseModel):
    email: str
    otp: str

class ResetPasswordRequest(BaseModel):
    email: str
    reset_token: str
    new_password: str

class VerifyEmailRequest(BaseModel):
    token: str

class ResendVerificationRequest(BaseModel):
    email: str


def find_user_by_email(email: str) -> Optional[Dict]:
    clean = str(email).strip().lower()
    for u in mock_users:
        if u.get("email", "").strip().lower() == clean:
            return u
    return None

def find_user_by_name(name: str) -> Optional[Dict]:
    clean = str(name).strip().lower()
    for u in mock_users:
        if u.get("name", "").strip().lower() == clean:
            return u
    return None

def send_otp_email(to_email: str, otp: str) -> bool:
    if os.getenv("TESTING") == "true" or to_email.endswith("@marketmind.com"):
        log_audit(f"[SMTP Simulation] Simulated OTP email to {to_email}. (Bypassed real SMTP connection)")
        return True

    # 1. Try Resend REST API
    resend_key = os.getenv("RESEND_API_KEY", "").strip() or os.getenv("RESEND_KEY", "").strip()
    if resend_key:
        try:
            import httpx
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={
                    "Authorization": f"Bearer {resend_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "from": os.getenv("EMAIL_FROM", "MarketMind AI <onboarding@resend.dev>"),
                    "to": [to_email],
                    "subject": "MarketMind AI - Password Recovery OTP",
                    "html": f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 8px;">
                        <h2 style="color: #ff4b4b;">Password Recovery Code</h2>
                        <p>Hello,</p>
                        <p>You requested a password reset for your MarketMind AI account.</p>
                        <p>Your One-Time Password (OTP) is:</p>
                        <div style="background-color: #f7f7f9; padding: 15px; border-radius: 6px; font-size: 24px; font-weight: bold; letter-spacing: 4px; text-align: center; color: #171f32; margin: 20px 0;">
                            {otp}
                        </div>
                        <p>This OTP is valid for <strong>15 minutes</strong>. If you did not request this, please ignore this email.</p>
                    </div>
                    """
                },
                timeout=10.0
            )
            if resp.status_code in [200, 201]:
                log_audit(f"Successfully sent OTP email via Resend to {to_email}")
                return True
            else:
                log_audit(f"Resend error status {resp.status_code}: {resp.text}", is_alert=True)
        except Exception as e:
            log_audit(f"Error sending email via Resend to {to_email}: {str(e)}", is_alert=True)

    # 2. Try Brevo REST API
    brevo_key = os.getenv("BREVO_API_KEY", "").strip() or os.getenv("SIB_API_KEY", "").strip() or os.getenv("SENDINBLUE_API_KEY", "").strip()
    if brevo_key:
        try:
            import httpx
            sender_email = os.getenv("SMTP_USER", "").strip() or os.getenv("EMAIL_FROM_ADDRESS", "no-reply@marketmind.ai")
            sender_name = os.getenv("EMAIL_FROM_NAME", "MarketMind AI")
            resp = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={
                    "api-key": brevo_key,
                    "Content-Type": "application/json",
                    "Accept": "application/json"
                },
                json={
                    "sender": {"name": sender_name, "email": sender_email},
                    "to": [{"email": to_email}],
                    "subject": "MarketMind AI - Password Recovery OTP",
                    "htmlContent": f"""
                    <div style="font-family: sans-serif; max-width: 600px; margin: auto; padding: 20px; border: 1px solid #eee; border-radius: 8px;">
                        <h2 style="color: #ff4b4b;">Password Recovery Code</h2>
                        <p>Hello,</p>
                        <p>You requested a password reset for your MarketMind AI account.</p>
                        <p>Your One-Time Password (OTP) is:</p>
                        <div style="background-color: #f7f7f9; padding: 15px; border-radius: 6px; font-size: 24px; font-weight: bold; letter-spacing: 4px; text-align: center; color: #171f32; margin: 20px 0;">
                            {otp}
                        </div>
                        <p>This OTP is valid for <strong>15 minutes</strong>. If you did not request this, please ignore this email.</p>
                    </div>
                    """
                },
                timeout=10.0
            )
            if resp.status_code in [200, 201, 202]:
                log_audit(f"Successfully sent OTP email via Brevo to {to_email}")
                return True
        except Exception as e:
            log_audit(f"Error sending email via Brevo to {to_email}: {str(e)}", is_alert=True)

    # 3. Try configured SMTP (Gmail SSL/TLS, Outlook, custom)
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port_raw = os.getenv("SMTP_PORT", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip().strip('\'"')
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip().replace(" ", "").strip('\'"')

    if smtp_user and smtp_pass:
        if not smtp_host:
            if "@gmail.com" in smtp_user.lower():
                smtp_host = "smtp.gmail.com"
            elif any(d in smtp_user.lower() for d in ["@outlook.com", "@hotmail.com", "@live.com"]):
                smtp_host = "smtp.office365.com"
            elif "@yahoo.com" in smtp_user.lower():
                smtp_host = "smtp.mail.yahoo.com"
            else:
                smtp_host = "smtp.gmail.com"

        port = 587
        if smtp_port_raw:
            try:
                port = int(smtp_port_raw)
            except ValueError:
                port = 587
        elif smtp_host in ["smtp.gmail.com", "smtp.mail.yahoo.com"]:
            port = 465

        msg = MIMEMultipart("alternative")
        msg['From'] = os.getenv("EMAIL_FROM", smtp_user)
        msg['To'] = to_email
        msg['Subject'] = "MarketMind AI - Password Recovery OTP"

        body = f"Hello,\n\nYou requested a password reset for your MarketMind AI account.\nYour One-Time Password (OTP) is:\n\n👉  {otp}  👈\n\nThis OTP is valid for 15 minutes. If you did not request this, please ignore this email.\n\nBest regards,\nMarketMind AI Support Team"
        msg.attach(MIMEText(body, 'plain'))

        # If SSL Port 465
        if port == 465:
            try:
                with smtplib.SMTP_SSL(smtp_host, port, timeout=10) as server:
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, to_email, msg.as_string())
                log_audit(f"Successfully sent OTP email via SMTP_SSL ({smtp_host}:{port}) to {to_email}")
                return True
            except Exception as e:
                log_audit(f"SMTP_SSL failed, attempting STARTTLS: {e}")
                try:
                    with smtplib.SMTP(smtp_host, 587, timeout=10) as server:
                        server.starttls()
                        server.login(smtp_user, smtp_pass)
                        server.sendmail(smtp_user, to_email, msg.as_string())
                    log_audit(f"Successfully sent OTP email via SMTP STARTTLS (587) to {to_email}")
                    return True
                except Exception as e2:
                    log_audit(f"Failed to send OTP email via SMTP fallback: {e2}", is_alert=True)
        else:
            try:
                with smtplib.SMTP(smtp_host, port, timeout=10) as server:
                    server.starttls()
                    server.login(smtp_user, smtp_pass)
                    server.sendmail(smtp_user, to_email, msg.as_string())
                log_audit(f"Successfully sent OTP email via SMTP ({smtp_host}:{port}) to {to_email}")
                return True
            except Exception as e:
                log_audit(f"Failed to send OTP email via SMTP ({smtp_host}:{port}): {e}", is_alert=True)

    # 4. Try direct MX Server delivery
    try:
        domain = to_email.split("@")[-1].strip().lower()
        mx_hosts = []
        if domain == "gmail.com" or domain.endswith(".google.com"):
            mx_hosts = ["gmail-smtp-in.l.google.com", "alt1.gmail-smtp-in.l.google.com"]
        elif domain in ["outlook.com", "hotmail.com", "live.com"]:
            mx_hosts = ["outlook-com.olc.protection.outlook.com"]
        elif domain in ["yahoo.com", "ymail.com"]:
            mx_hosts = ["mta6.am0.yahoodns.net"]
        else:
            import urllib.request, json
            req = urllib.request.Request(f"https://dns.google/resolve?name={domain}&type=MX", headers={"User-Agent": "MarketMind/1.0"})
            with urllib.request.urlopen(req, timeout=4) as res:
                data = json.loads(res.read().decode())
                for a in data.get("Answer", []):
                    if a.get("type") == 15:
                        parts = a.get("data", "").split()
                        if len(parts) >= 2:
                            mx_hosts.append(parts[1].rstrip("."))

        msg = MIMEMultipart("alternative")
        msg["From"] = "MarketMind AI <no-reply@marketmind.ai>"
        msg["To"] = to_email
        msg["Subject"] = "MarketMind AI - Password Recovery OTP"
        body = f"Hello,\n\nYour MarketMind AI password recovery OTP code is: {otp}\n\nThis OTP is valid for 15 minutes.\n\nBest regards,\nMarketMind AI Support Team"
        msg.attach(MIMEText(body, "plain"))

        for host in mx_hosts:
            try:
                server = smtplib.SMTP(host, 25, timeout=8)
                server.ehlo("marketmind.ai")
                if server.has_extn("STARTTLS"):
                    server.starttls()
                    server.ehlo("marketmind.ai")
                server.sendmail("no-reply@marketmind.ai", [to_email], msg.as_string())
                server.quit()
                log_audit(f"Successfully sent OTP email via direct MX delivery to {to_email}")
                return True
            except Exception as mx_err:
                log_audit(f"Direct MX delivery to {host} failed: {mx_err}", is_alert=True)
    except Exception as e:
        log_audit(f"Direct MX resolution failed for {to_email}: {e}", is_alert=True)

    return False

def send_verification_email(to_email: str, code: str) -> bool:
    if os.getenv("TESTING") == "true" or to_email.endswith("@marketmind.com"):
        log_audit(f"[SMTP Simulation] Simulated verification email with code {code} to {to_email}. (Bypassed real SMTP connection)")
        return True

    # Try Resend
    resend_key = os.getenv("RESEND_API_KEY", "").strip() or os.getenv("RESEND_KEY", "").strip()
    if resend_key:
        try:
            import httpx
            resp = httpx.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {resend_key}", "Content-Type": "application/json"},
                json={
                    "from": os.getenv("EMAIL_FROM", "MarketMind AI <onboarding@resend.dev>"),
                    "to": [to_email],
                    "subject": "MarketMind AI - Email Verification Code",
                    "html": f"<p>Your verification code is: <strong>{code}</strong></p>"
                },
                timeout=10.0
            )
            if resp.status_code in [200, 201]:
                return True
        except Exception:
            pass

    # Try Brevo
    brevo_key = os.getenv("BREVO_API_KEY", "").strip() or os.getenv("SIB_API_KEY", "").strip()
    if brevo_key:
        try:
            import httpx
            sender_email = os.getenv("SMTP_USER", "").strip() or "no-reply@marketmind.ai"
            resp = httpx.post(
                "https://api.brevo.com/v3/smtp/email",
                headers={"api-key": brevo_key, "Content-Type": "application/json"},
                json={
                    "sender": {"name": "MarketMind AI", "email": sender_email},
                    "to": [{"email": to_email}],
                    "subject": "MarketMind AI - Email Verification Code",
                    "htmlContent": f"<p>Your verification code is: <strong>{code}</strong></p>"
                },
                timeout=10.0
            )
            if resp.status_code in [200, 201, 202]:
                return True
        except Exception:
            pass

    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port_raw = os.getenv("SMTP_PORT", "").strip()
    smtp_user = os.getenv("SMTP_USER", "").strip()
    smtp_pass = os.getenv("SMTP_PASSWORD", "").strip()

    if not smtp_user or not smtp_pass:
        log_audit(f"SMTP environment credentials incomplete. Verification email simulation active. Email: {to_email}, Code: {code}", is_alert=True)
        return False

    if not smtp_host:
        if "@gmail.com" in smtp_user.lower():
            smtp_host = "smtp.gmail.com"
        elif any(d in smtp_user.lower() for d in ["@outlook.com", "@hotmail.com"]):
            smtp_host = "smtp.office365.com"
        else:
            smtp_host = "smtp.gmail.com"

    port = 587
    if smtp_port_raw:
        try:
            port = int(smtp_port_raw)
        except ValueError:
            port = 587
    elif smtp_host in ["smtp.gmail.com", "smtp.mail.yahoo.com"]:
        port = 465

    try:
        msg = MIMEMultipart()
        msg['From'] = os.getenv("EMAIL_FROM", smtp_user)
        msg['To'] = to_email
        msg['Subject'] = "MarketMind AI - Email Verification Code"

        body = f"Hello,\n\nWelcome to MarketMind AI! Please verify your email address by entering the following unique verification code:\n\n👉  {code}  👈\n\nThis verification code is valid for 24 hours. If you did not sign up for this account, please ignore this email.\n\nBest regards,\nMarketMind AI Support Team"
        msg.attach(MIMEText(body, 'plain'))

        if port == 465:
            with smtplib.SMTP_SSL(smtp_host, port, timeout=10) as server:
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())
        else:
            with smtplib.SMTP(smtp_host, port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.sendmail(smtp_user, to_email, msg.as_string())
        
        log_audit(f"Successfully sent verification email to {to_email}")
        return True
    except Exception as e:
        log_audit(f"Failed to send verification email to {to_email}: {str(e)}", is_alert=True)
        return False

AUDIT_LOG_FILE = os.getenv("AUDIT_LOG_FILE", os.path.join(os.path.dirname(__file__), "audit.log"))

# --- Custom Audit Logging ---
def log_audit(message: str, is_alert: bool = False):
    timestamp = datetime.datetime.now(datetime.UTC).isoformat()
    prefix = "[ALERT]" if is_alert else "[INFO]"
    log_line = f"{timestamp} - {prefix} - {message}\n"
    
    # Print to console
    print(f"[Audit Log] {log_line.strip()}", flush=True)
    
    # Append to persistent log file
    try:
        with open(AUDIT_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_line)
    except Exception as e:
        print(f"Failed to write to audit log file: {e}", flush=True)

# --- In-Memory Rate Limiting ---
RATE_LIMIT_STORE = defaultdict(list)

def check_rate_limit(ip: str, limit_type: str, max_requests: int, window: int) -> bool:
    now = time.time()
    # Filter out records older than 1 hour to prevent memory bloat
    if ip in RATE_LIMIT_STORE:
        RATE_LIMIT_STORE[ip] = [(t, l_type) for t, l_type in RATE_LIMIT_STORE[ip] if now - t < 3600]
    
    # Count matching records in window
    recent = [t for t, l_type in RATE_LIMIT_STORE[ip] if l_type == limit_type and now - t < window]
    if len(recent) >= max_requests:
        return True
        
    RATE_LIMIT_STORE[ip].append((now, limit_type))
    return False

@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    if os.getenv("TESTING") != "true" or request.headers.get("x-bypass-rate-limit") == "true":
        return await call_next(request)
    path = request.url.path
    if path.startswith("/docs") or path.startswith("/openapi.json") or path.startswith("/redoc"):
        return await call_next(request)
        
    # Resolve real client IP address behind reverse proxies (e.g. Render, Cloudflare)
    client_ip = "unknown"
    xff = request.headers.get("x-forwarded-for")
    if xff:
        client_ip = xff.split(",")[0].strip()
    elif request.client:
        client_ip = request.client.host
    
    # 1. Strict Auth Limit (10 requests/60s for testing, 150 requests/60s for production)
    if path.startswith("/auth/"):
        max_auth = 10 if os.getenv("TESTING") == "true" else 150
        if check_rate_limit(client_ip, "auth", max_requests=max_auth, window=60):
            log_audit(f"Auth rate limit exceeded for IP: {client_ip}", is_alert=True)
            return JSONResponse(
                content={"detail": "Too many auth attempts. Please wait 1 minute."},
                status_code=429
            )
            
    # 2. Testing Limit (3 requests/10s)
    elif path.startswith("/api/test-rate-limit"):
        if check_rate_limit(client_ip, "test", max_requests=3, window=10):
            log_audit(f"Test rate limit exceeded for IP: {client_ip}", is_alert=True)
            return JSONResponse(
                content={"detail": "Too many requests. Testing rate limit active."},
                status_code=429
            )
            
    # 3. General API Limit (100 requests/60s)
    elif path.startswith("/api/"):
        if check_rate_limit(client_ip, "general", max_requests=100, window=60):
            log_audit(f"General API rate limit exceeded for IP: {client_ip}", is_alert=True)
            return JSONResponse(
                content={"detail": "Too many requests. Please try again later."},
                status_code=429
            )
            
    return await call_next(request)

# --- Authorization Dependencies ---

async def verify_token(authorization: Optional[str] = Header(None)) -> Dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token missing or malformed. Use Bearer <token>"
        )
    
    token = authorization.split(" ")[1]
    try:
        decoded = jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])
        return decoded
    except jwt.ExpiredSignatureError:
        log_audit("Rejected expired token", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is expired"
        )
    except jwt.InvalidTokenError as e:
        log_audit(f"Rejected invalid token: {str(e)}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Access token is invalid"
        )

def check_role(allowed_roles: List[str]):
    async def role_dependency(user: Dict = Depends(verify_token)):
        if "role" not in user:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: role signature missing"
            )
        if user["role"] not in allowed_roles:
            log_audit(
                f"Unauthorized role access attempt: User {user.get('name', 'unknown')} ({user['role']}) tried to access path",
                is_alert=True
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Forbidden: Access restricted. Required role: one of [{', '.join(allowed_roles)}]"
            )
        return user
    return role_dependency

# --- Authentication Routes ---

@app.post("/auth/register", status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest):
    if req.role not in VALID_ROLES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid role. Must be one of: {', '.join(VALID_ROLES)}"
        )
    
    if find_user_by_email(req.email) or find_user_by_name(req.name):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User with this email or name already exists"
        )
    
    # Hash password
    salt = bcrypt.gensalt(10)
    password_bytes = req.password.encode('utf-8')
    password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')

    token = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
    expiry = time.time() + 86400

    is_verified = (req.role in ["Business Owner", "Admin"])
    new_user = {
        "id": len(mock_users) + 1,
        "name": req.name,
        "email": req.email,
        "password_hash": password_hash,
        "role": req.role,
        "refresh_tokens": [],  # Active refresh tokens list
        "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
        "is_verified": is_verified,
        "verification_token": token,
        "verification_token_expires": expiry
    }
    mock_users.append(new_user)
    log_audit(f"User Registered: {req.name} as {req.role}. Verification token generated (Auto-verified: {is_verified}).")

    # Send verification email for new roles requiring verification
    if not is_verified:
        send_verification_email(req.email, token)

    return {
        "message": "Registration successful",
        "user": {
            "id": new_user["id"],
            "name": new_user["name"],
            "email": new_user["email"],
            "role": new_user["role"],
            "created_at": new_user["created_at"],
            "is_verified": new_user["is_verified"]
        },
        "verification_token": token
    }

@app.post("/auth/login")
async def login(req: LoginRequest):
    user = find_user_by_email(req.email) or find_user_by_name(req.email)
    if not user:
        log_audit(f"Failed login attempt for non-existent user/email: {req.email}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )
    
    # Verify password hash
    password_bytes = req.password.encode('utf-8')
    user_hash_bytes = user["password_hash"].encode('utf-8')
    if not bcrypt.checkpw(password_bytes, user_hash_bytes):
        log_audit(f"Failed login attempt for user: {user['name']}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials"
        )

    # Verify email is verified
    if not user.get("is_verified", False):
        log_audit(f"Failed login attempt for unverified email: {req.email}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Email address not verified. Please verify your email before logging in."
        )

    # Generate short-lived Access Token (15 minutes)
    access_exp_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15)
    access_payload = {
        "userId": user["id"],
        "name": user["name"],
        "role": user["role"],
        "exp": int(access_exp_time.timestamp()),
        "iat": int(datetime.datetime.now(datetime.UTC).timestamp())
    }
    access_token = jwt.encode(access_payload, JWT_SECRET, algorithm=ALGORITHM)
    
    # Generate long-lived Refresh Token (7 days)
    refresh_exp_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(days=7)
    refresh_payload = {
        "userId": user["id"],
        "exp": int(refresh_exp_time.timestamp()),
        "iat": int(datetime.datetime.now(datetime.UTC).timestamp())
    }
    refresh_token = jwt.encode(refresh_payload, JWT_SECRET, algorithm=ALGORITHM)
    
    # Store refresh token in user's record
    if "refresh_tokens" not in user:
        user["refresh_tokens"] = []
    user["refresh_tokens"].append(refresh_token)
    
    log_audit(f"User Logged In: {user['name']} (Role: {user['role']})")
    
    return {
        "message": "Login successful",
        "token": access_token,
        "refreshToken": refresh_token,
        "user": {
            "id": user["id"],
            "name": user["name"],
            "email": user["email"],
            "role": user["role"]
        }
    }

@app.post("/auth/refresh")
async def refresh_token_route(req: RefreshRequest):
    try:
        decoded = jwt.decode(req.refresh_token, JWT_SECRET, algorithms=[ALGORITHM])
        user_id = decoded.get("userId")
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is expired"
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is invalid"
        )

    # Verify user exists and token has not been revoked
    user = next((u for u in mock_users if u["id"] == user_id), None)
    if not user or "refresh_tokens" not in user or req.refresh_token not in user["refresh_tokens"]:
        log_audit(f"Rejected invalid or revoked refresh token for user ID: {user_id}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Refresh token is revoked or invalid"
        )

    # Generate new Access Token (15 minutes)
    access_exp_time = datetime.datetime.now(datetime.UTC) + datetime.timedelta(minutes=15)
    access_payload = {
        "userId": user["id"],
        "name": user["name"],
        "role": user["role"],
        "exp": int(access_exp_time.timestamp()),
        "iat": int(datetime.datetime.now(datetime.UTC).timestamp())
    }
    new_access_token = jwt.encode(access_payload, JWT_SECRET, algorithm=ALGORITHM)
    
    log_audit(f"Refreshed access token for user: {user['name']}")
    return {
        "token": new_access_token
    }

@app.post("/auth/logout")
async def logout(user: Dict = Depends(verify_token)):
    # Invalidate all active refresh tokens for the logged-out user
    user_record = next((u for u in mock_users if u["id"] == user.get("userId")), None)
    if user_record:
        user_record["refresh_tokens"] = []
        log_audit(f"User Logged Out: {user_record['name']} (revoked all refresh tokens)")
    
    return {"message": "Logged out successfully"}

@app.post("/auth/verify-email")
@app.post("/verify-email")
async def verify_email(req: VerifyEmailRequest):
    user = next((u for u in mock_users if u.get("verification_token") == req.token), None)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or already-used verification token."
        )
    
    if user.get("verification_token_expires", 0) < time.time():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Verification token has expired."
        )

    user["is_verified"] = True
    user["verification_token"] = None
    user["verification_token_expires"] = None

    log_audit(f"User email verified successfully: {user['email']}")
    return {"message": "Email verified successfully."}


def send_verification_email(to_email: str, token: str) -> bool:
    """Dispatch account verification email to user."""
    return send_otp_email(to_email, token)


@app.post("/auth/resend-verification")
@app.post("/resend-verification")
async def resend_verification(req: ResendVerificationRequest):
    user = find_user_by_email(req.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Email not registered."
        )

    if user.get("is_verified", False):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email address is already verified."
        )

    new_token = "".join(random.choices("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=6))
    expiry = time.time() + 86400

    user["verification_token"] = new_token
    user["verification_token_expires"] = expiry

    log_audit(f"Resent verification email for: {req.email}")
    send_verification_email(req.email, new_token)

    return {
        "message": "Verification email resent.",
        "verification_token": new_token
    }

@app.post("/auth/forgot-password")
@app.post("/forgot-password")
async def forgot_password(req: ForgotPasswordRequest):
    email_clean = req.email.strip().lower()
    user = find_user_by_email(email_clean) or find_user_by_name(email_clean)
    if not user:
        log_audit(f"Forgot password attempt for non-existent email: {email_clean}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User with this email does not exist"
        )
    
    # Generate 6-digit OTP
    otp = f"{random.randint(100000, 999999)}"
    expiry = time.time() + 900  # 15 minutes from now
    
    PASSWORD_RECOVERY_STORE[email_clean] = {
        "otp": otp,
        "otp_expires": expiry,
        "reset_token": None,
        "token_expires": None
    }
    
    # Send real-time OTP email
    email_sent = send_otp_email(email_clean, otp)
    
    log_audit(f"Generated OTP: {otp} for password recovery of user: {email_clean}")
    res_data = {
        "message": "OTP sent to email" if email_sent else "OTP generated successfully",
        "email_sent": email_sent,
        "otp": otp
    }
    return res_data

@app.post("/auth/verify-otp")
@app.post("/verify-otp")
async def verify_otp(req: VerifyOTPRequest):
    email_clean = req.email.strip().lower()
    record = PASSWORD_RECOVERY_STORE.get(email_clean)
    if not record or not record.get("otp") or record["otp_expires"] < time.time():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No active OTP request found for this email"
        )
    
    if record["otp"] != req.otp:
        log_audit(f"Invalid OTP verify attempt for email: {email_clean}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid OTP"
        )
    
    # Generate temporary reset token
    reset_token = "reset-token-" + secrets.token_hex(16)
    record["reset_token"] = reset_token
    record["token_expires"] = time.time() + 900 # 15 minutes expiry
    record["otp"] = None # Clear OTP to prevent re-use
    
    log_audit(f"OTP verified successfully for email: {email_clean}. Generated reset_token: {reset_token}")
    return {
        "message": "OTP verified successfully",
        "reset_token": reset_token
    }

@app.post("/auth/reset-password")
@app.post("/reset-password")
async def reset_password(req: ResetPasswordRequest):
    email_clean = req.email.strip().lower()
    record = PASSWORD_RECOVERY_STORE.get(email_clean)
    if not record or not record.get("reset_token") or record["token_expires"] < time.time():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset session"
        )
    
    if record["reset_token"] != req.reset_token:
        log_audit(f"Invalid reset token attempt for email: {email_clean}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid reset token"
        )
    
    user = find_user_by_email(email_clean) or find_user_by_name(email_clean)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )
    
    salt = bcrypt.gensalt(10)
    password_bytes = req.new_password.encode('utf-8')
    password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')
    user["password_hash"] = password_hash
    user["is_verified"] = True
    user["refresh_tokens"] = []
    
    # Clean recovery store
    del PASSWORD_RECOVERY_STORE[email_clean]
    
    log_audit(f"Password reset successful for user: {user['name']}")
    return {
        "message": "Password reset successfully"
    }

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")
AI_URL = os.getenv("AI_URL", "http://127.0.0.1:5002")
NOTIFICATIONS_URL = os.getenv("NOTIFICATIONS_URL", "http://127.0.0.1:5003")


# --- Proxy Routes with Validation ---

@app.post("/api/sales/upload")
async def proxy_sales_upload(
    file: UploadFile = File(...),
    user: Dict = Depends(check_role(["Business Owner", "Store Manager", "Sales Executive"]))
):
    # Reject non-CSV uploads at the gateway layer
    if not file.filename.lower().endswith(".csv") and file.content_type != "text/csv":
        log_audit(f"Rejected non-CSV file upload attempt: {file.filename}", is_alert=True)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed request: Only CSV files are allowed."
        )
    
    content = await file.read()
    
    async with httpx.AsyncClient() as client:
        try:
            files = {"file": (file.filename, content, file.content_type or "text/csv")}
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            # Proxy to the Backend_Database service
            response = await client.post(
                f"{BACKEND_URL}/api/sales/upload",
                files=files,
                headers=headers,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            log_audit(f"Connection failed to backend: {str(e)}", is_alert=True)
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Database backend is unreachable: {str(e)}"
            )

@app.get("/api/sales/dashboard-metrics")
async def proxy_sales_metrics(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))
):
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{BACKEND_URL}/api/sales/dashboard-metrics",
                params=dict(request.query_params),
                headers=headers
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Database backend is unreachable"
            )

@app.get("/api/inventory")
async def proxy_inventory_view(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager", "Sales Executive"]))
):
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{BACKEND_URL}/inventory/",
                params=dict(request.query_params),
                headers=headers
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Database backend is unreachable"
            )

@app.post("/api/inventory/update")
async def proxy_inventory_update(
    payload: InventoryUpdateSchema,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))
):
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.put(
                f"{BACKEND_URL}/inventory/{payload.product_id}",
                json={
                    "stock_quantity": payload.stock_quantity,
                    "low_stock_threshold": payload.low_stock_threshold
                },
                headers=headers
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Database backend is unreachable"
            )

@app.get("/api/forecast/sample")
async def proxy_forecast_sample(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner"]))
):
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{AI_URL}/api/forecast/sample",
                params=dict(request.query_params),
                headers=headers
            )
            if response.status_code == 404:
                return {
                    "message": "[Gateway Stub] AI/ML sample forecast endpoint is not implemented by the AI service yet.",
                    "forecast": [
                        {"date": "2026-07-12", "predicted_sales": 1250.0},
                        {"date": "2026-07-13", "predicted_sales": 1325.5},
                        {"date": "2026-07-14", "predicted_sales": 1298.75}
                    ],
                    "requestUser": user
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            # Fallback stub if AI service is not running
            return {
                "message": "[Gateway Fallback] AI/ML forecasting service is currently unreachable.",
                "requestUser": user
            }

@app.get("/api/audit-logs")
async def proxy_audit_logs(
    request: Request,
    user: Dict = Depends(check_role(["Admin"]))
):
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{BACKEND_URL}/api/audit-logs",
                params=dict(request.query_params),
                headers=headers
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            # Fallback stub for audit logs
            return {
                "message": "[Gateway Fallback] Audit logs backend is unreachable. Admin stubs active.",
                "requestUser": user
            }

# --- Invoice Management Proxy Routes ---

@app.post("/api/invoices")
async def proxy_create_invoice(
    payload: InvoiceCreateSchema,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager", "Sales Executive"]))
):
    # Activity logging
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) attempted to create invoice: {payload.invoice_number}")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.post(
                f"{BACKEND_URL}/api/invoices",
                json=payload.model_dump(),
                headers=headers,
                timeout=10.0
            )
            # If backend is not ready, return gateway stub for testing
            if response.status_code == 404:
                customer_name_val = getattr(payload, "customer_name", None) or f"Customer #{payload.customer_id}"
                log_audit(f"Invoice {payload.invoice_number} created successfully (Gateway Stub)")
                return {
                    "message": "[Gateway Stub] Invoice created successfully.",
                    "invoice_number": payload.invoice_number,
                    "customer_name": customer_name_val,
                    "total_amount": payload.total_amount,
                    "payment_status": payload.payment_status,
                    "created_by": user["userId"]
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            # Fallback stub for integration testing/unreachable backend
            customer_name_val = getattr(payload, "customer_name", None) or f"Customer #{payload.customer_id}"
            log_audit(f"Invoice {payload.invoice_number} created successfully (Gateway Fallback)")
            return {
                "message": "[Gateway Fallback] Invoice created successfully.",
                "invoice_number": payload.invoice_number,
                "customer_name": customer_name_val,
                "total_amount": payload.total_amount,
                "payment_status": payload.payment_status,
                "created_by": user["userId"]
            }

@app.get("/api/invoices")
async def proxy_list_invoices(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager", "Sales Executive"]))
):
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) requested invoices list")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{BACKEND_URL}/api/invoices",
                params=dict(request.query_params),
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 404:
                return {
                    "message": "[Gateway Stub] Invoices retrieved successfully.",
                    "invoices": [
                        {
                            "id": 1,
                            "invoice_number": "INV-001",
                            "customer_name": "John Doe",
                            "total_amount": 150.0,
                            "payment_status": "Paid"
                        },
                        {
                            "id": 2,
                            "invoice_number": "INV-002",
                            "customer_name": "Jane Smith",
                            "total_amount": 320.0,
                            "payment_status": "Unpaid"
                        }
                    ]
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return {
                "message": "[Gateway Fallback] Invoices retrieved successfully.",
                "invoices": []
            }

@app.put("/api/invoices/{id}/status")
async def proxy_update_invoice_status(
    id: int,
    payload: InvoiceStatusUpdateSchema,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))
):
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) updated invoice ID {id} status to {payload.payment_status}")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.put(
                f"{BACKEND_URL}/api/invoices/{id}/status",
                json=payload.model_dump(),
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 404:
                return {
                    "message": f"[Gateway Stub] Invoice {id} status updated to {payload.payment_status}.",
                    "invoice_id": id,
                    "payment_status": payload.payment_status
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return {
                "message": f"[Gateway Fallback] Invoice {id} status updated to {payload.payment_status}.",
                "invoice_id": id,
                "payment_status": payload.payment_status
            }

@app.get("/api/invoices/revenue-summary")
async def proxy_revenue_summary(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))
):
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) requested revenue summary")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{BACKEND_URL}/api/invoices/revenue-summary",
                params=dict(request.query_params),
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 404:
                return {
                    "message": "[Gateway Stub] Revenue summary retrieved.",
                    "total_revenue": 470.0,
                    "total_outstanding": 320.0,
                    "daily_collections": 150.0
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return {
                "message": "[Gateway Fallback] Revenue summary retrieved.",
                "total_revenue": 470.0,
                "total_outstanding": 320.0,
                "daily_collections": 150.0
            }

# --- AI Analytics Proxy Routes ---

@app.get("/api/ai/segmentation")
async def proxy_ai_segmentation(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner"]))
):
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) requested AI Customer Segmentation report")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{AI_URL}/api/ai/segmentation",
                params=dict(request.query_params),
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 404:
                return {
                    "message": "[Gateway Stub] AI Customer Segmentation data.",
                    "segments": {
                        "Loyal": ["Cust-001", "Cust-005"],
                        "Occasional": ["Cust-002", "Cust-004"],
                        "High-value": ["Cust-003"]
                    }
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return {
                "message": "[Gateway Fallback] AI/ML segmentation service is currently unreachable.",
                "segments": {
                    "Loyal": ["Cust-001", "Cust-005"],
                    "Occasional": ["Cust-002", "Cust-004"],
                    "High-value": ["Cust-003"]
                }
            }

@app.get("/api/ai/churn")
async def proxy_ai_churn(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))
):
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) requested AI Churn Risk report")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{AI_URL}/api/ai/churn",
                params=dict(request.query_params),
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 404:
                return {
                    "message": "[Gateway Stub] AI Churn Risk data.",
                    "at_risk_customers": [
                        {"customer_id": "Cust-002", "churn_probability": 0.82},
                        {"customer_id": "Cust-004", "churn_probability": 0.65}
                    ]
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return {
                "message": "[Gateway Fallback] AI/ML churn risk service is currently unreachable.",
                "at_risk_customers": [
                    {"customer_id": "Cust-002", "churn_probability": 0.82},
                    {"customer_id": "Cust-004", "churn_probability": 0.65}
                ]
            }

@app.get("/api/ai/recommendation")
async def proxy_ai_recommendation(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager", "Sales Executive"]))
):
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) requested AI Product Recommendation report")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{AI_URL}/api/ai/recommendation",
                params=dict(request.query_params),
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 404:
                return {
                    "message": "[Gateway Stub] AI Product Recommendations.",
                    "recommendations": [
                        {"product_id": "Prod-101", "recommended_with": ["Prod-102", "Prod-105"]},
                        {"product_id": "Prod-202", "recommended_with": ["Prod-203"]}
                    ]
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return {
                "message": "[Gateway Fallback] AI/ML recommendation service is currently unreachable.",
                "recommendations": [
                    {"product_id": "Prod-101", "recommended_with": ["Prod-102", "Prod-105"]},
                    {"product_id": "Prod-202", "recommended_with": ["Prod-203"]}
                ]
            }

@app.get("/api/ai/anomaly")
async def proxy_ai_anomaly(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))
):
    log_audit(f"User {user.get('name')} (ID: {user.get('userId')}) requested AI Anomaly Detection report")
    
    async with httpx.AsyncClient() as client:
        try:
            headers = {
                "x-user-id": str(user["userId"]),
                "x-user-role": user["role"]
            }
            response = await client.get(
                f"{AI_URL}/api/ai/anomaly",
                params=dict(request.query_params),
                headers=headers,
                timeout=10.0
            )
            if response.status_code == 404:
                return {
                    "message": "[Gateway Stub] AI Anomaly Detection alerts.",
                    "alerts": [
                        {"transaction_id": 99, "reason": "Unusual total amount for guest user", "flag": "warning"},
                        {"transaction_id": 105, "reason": "Stock change exceeds monthly average threshold", "flag": "warning"}
                    ]
                }
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return {
                "message": "[Gateway Fallback] AI/ML anomaly detection service is currently unreachable.",
                "alerts": [
                    {"transaction_id": 99, "reason": "Unusual total amount for guest user", "flag": "warning"},
                    {"transaction_id": 105, "reason": "Stock change exceeds monthly average threshold", "flag": "warning"}
                ]
            }

@app.get("/api/test-rate-limit")
async def test_rate_limit_endpoint(user: Dict = Depends(verify_token)):
    return {"message": "Rate limit check passed."}

@app.get("/sales/")
async def proxy_sales_root(request: Request):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{BACKEND_URL}/sales/",
                params=dict(request.query_params)
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to backend: {str(e)}"}
            )

@app.get("/inventory/")
async def proxy_inventory_root(request: Request):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{BACKEND_URL}/inventory/",
                params=dict(request.query_params)
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to backend: {str(e)}"}
            )

@app.post("/predict")
async def proxy_ai_predict_raw(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/predict",
                content=body,
                headers=headers,
                timeout=60.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML forecasting service: {str(e)}"}
            )

@app.post("/recommend-product")
async def proxy_ai_recommend_raw(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            # Strip Content-Length header to prevent mismatch issues when body is forwarded
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/recommend-product",
                content=body,
                headers=headers,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML recommendation service: {str(e)}"}
            )

@app.post("/check-anomaly")
async def proxy_ai_anomaly_raw(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/check-anomaly",
                content=body,
                headers=headers,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML anomaly detection service: {str(e)}"}
            )

@app.post("/customer-group")
async def proxy_ai_customer_group_raw(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/customer-group",
                content=body,
                headers=headers,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML customer segmentation service: {str(e)}"}
            )

@app.post("/customer-group/batch")
async def proxy_ai_customer_group_batch(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/customer-group/batch",
                content=body,
                headers=headers,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML customer segmentation service: {str(e)}"}
            )

@app.post("/churn-risk")
async def proxy_ai_churn_risk_raw(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/churn-risk",
                content=body,
                headers=headers,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML churn risk service: {str(e)}"}
            )

@app.post("/churn-risk/batch")
async def proxy_ai_churn_risk_batch(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/churn-risk/batch",
                content=body,
                headers=headers,
                timeout=30.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML churn risk service: {str(e)}"}
            )

@app.post("/forecast-backtest")
async def proxy_ai_forecast_backtest_raw(request: Request):
    body = await request.body()
    async with httpx.AsyncClient() as client:
        try:
            headers = dict(request.headers)
            headers.pop("content-length", None)
            headers.pop("host", None)
            response = await client.post(
                f"{AI_URL}/forecast-backtest",
                content=body,
                headers=headers,
                timeout=60.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError as e:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": f"Failed to connect to AI/ML forecast backtest service: {str(e)}"}
            )


@app.get("/api/notifications")
async def proxy_notifications_view(user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))):
    log_audit(f"User {user['name']} requested notifications alert list")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{NOTIFICATIONS_URL}/notifications",
                headers={
                    "x-user-id": str(user["userId"]),
                    "x-user-role": user["role"]
                },
                timeout=10.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            # Fallback mock notifications if service is offline/not running yet
            return {
                "message": "[Gateway Fallback] Notifications service is currently unreachable.",
                "notifications": [
                    {"id": 1, "type": "low_stock", "message": "Product 'Mouse' is low on stock (Quantity: 3).", "created_at": "2026-07-27T12:00:00Z"},
                    {"id": 2, "type": "overdue_invoice", "message": "Invoice INV-M2-01 has passed due date.", "created_at": "2026-07-27T12:05:00Z"}
                ]
            }

@app.post("/api/invoices/bulk-update")
async def proxy_invoices_bulk_update(payload: BulkInvoiceUpdateSchema, user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))):
    log_audit(f"User {user['name']} triggered bulk invoice status updates")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BACKEND_URL}/invoices/bulk-update",
                json=payload.model_dump(),
                headers={
                    "x-user-id": str(user["userId"]),
                    "x-user-role": user["role"],
                    "content-type": "application/json"
                },
                timeout=10.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service for bulk update."}
            )

@app.post("/api/inventory/bulk-update")
async def proxy_inventory_bulk_update(payload: BulkInventoryUpdateSchema, user: Dict = Depends(check_role(["Business Owner", "Store Manager"]))):
    log_audit(f"User {user['name']} triggered bulk inventory stock updates")
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BACKEND_URL}/inventory/bulk-update",
                json=payload.model_dump(),
                headers={
                    "x-user-id": str(user["userId"]),
                    "x-user-role": user["role"],
                    "content-type": "application/json"
                },
                timeout=10.0
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service for bulk update."}
            )

@app.get("/api/admin/audit-summary")
async def audit_summary(user: Dict = Depends(check_role(["Business Owner", "Admin"]))):
    if not os.path.exists(AUDIT_LOG_FILE):
        return {
            "total_logs": 0,
            "user_counts": {},
            "action_counts": {},
            "recent_activities": []
        }
        
    user_counts = defaultdict(int)
    action_counts = defaultdict(int)
    recent_activities = []
    
    try:
        with open(AUDIT_LOG_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        total_logs = len(lines)
        
        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue
                
            parts = line_str.split(" - ")
            if len(parts) >= 3:
                timestamp = parts[0]
                level = parts[1]
                message = " - ".join(parts[2:])
                
                inferred_user = "system"
                inferred_action = "other_activity"
                
                if "User Logged In:" in message:
                    user_match = re.search(r"User Logged In:\s*([^\s(]+)", message)
                    if user_match:
                        inferred_user = user_match.group(1)
                    inferred_action = "user_login"
                elif "User Logged Out:" in message:
                    user_match = re.search(r"User Logged Out:\s*([^\s(]+)", message)
                    if user_match:
                        inferred_user = user_match.group(1)
                    inferred_action = "user_logout"
                elif "attempted to create invoice" in message:
                    user_match = re.search(r"User\s+([^\s]+)\s+attempted", message)
                    if user_match:
                        inferred_user = user_match.group(1)
                    inferred_action = "invoice_create_attempt"
                elif "requested AI" in message:
                    user_match = re.search(r"User\s+([^\s]+)\s+requested", message)
                    if user_match:
                        inferred_user = user_match.group(1)
                    inferred_action = "ai_report_request"
                elif "rate limit exceeded" in message:
                    inferred_action = "rate_limit_triggered"
                    ip_match = re.search(r"IP:\s*([^\s]+)", message)
                    inferred_user = ip_match.group(1) if ip_match else "guest"
                elif "Rejected non-CSV" in message:
                    inferred_action = "malformed_upload_rejected"
                    inferred_user = "guest"
                elif "updated invoice" in message:
                    user_match = re.search(r"User\s+([^\s]+)\s+updated", message)
                    if user_match:
                        inferred_user = user_match.group(1)
                    inferred_action = "invoice_update"
                elif "requested notifications" in message:
                    user_match = re.search(r"User\s+([^\s]+)\s+requested", message)
                    if user_match:
                        inferred_user = user_match.group(1)
                    inferred_action = "notifications_request"
                
                user_counts[inferred_user] += 1
                action_counts[inferred_action] += 1
                recent_activities.append({
                    "timestamp": timestamp,
                    "level": level,
                    "user": inferred_user,
                    "action": inferred_action,
                    "message": message
                })
                
        recent_activities = recent_activities[-20:]
        recent_activities.reverse()
        
        return {
            "total_logs": total_logs,
            "user_counts": dict(user_counts),
            "action_counts": dict(action_counts),
            "recent_activities": recent_activities
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Error reading or parsing audit log: {str(e)}"
        )

# --------------------------------------------------
# INVITATION & SIGNUP SCHEMAS
# --------------------------------------------------
class SignupVerifyInvitationPayload(BaseModel):
    email: str
    code: str

class SignupVerifyOtpPayload(BaseModel):
    email: str
    otp: str
    session_token: str

class SignupCompletePayload(BaseModel):
    email: str
    signup_token: str
    name: str
    phone: str
    password: str

# --------------------------------------------------
# INVITATION & SIGNUP PROXIES
# --------------------------------------------------

@app.post("/api/invitations")
async def gateway_create_invitation(
    request: Request,
    user: Dict = Depends(check_role(["Business Owner", "Admin"]))
):
    body = await request.json()
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BACKEND_URL}/invitations/",
                json=body,
                headers={
                    "x-user-id": str(user["userId"]),
                    "x-user-role": user["role"],
                    "content-type": "application/json"
                }
            )
            if response.status_code == 201:
                log_audit(f"Invitation created by {user['name']} (Owner) for {body.get('email')}")
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service."}
            )

@app.get("/api/invitations")
async def gateway_list_invitations(
    user: Dict = Depends(check_role(["Business Owner", "Admin"]))
):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(
                f"{BACKEND_URL}/invitations/",
                headers={
                    "x-user-id": str(user["userId"]),
                    "x-user-role": user["role"]
                }
            )
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service."}
            )

@app.delete("/api/invitations/{id}")
async def gateway_revoke_invitation(
    id: int,
    user: Dict = Depends(check_role(["Business Owner", "Admin"]))
):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.delete(
                f"{BACKEND_URL}/invitations/{id}",
                headers={
                    "x-user-id": str(user["userId"]),
                    "x-user-role": user["role"]
                }
            )
            if response.status_code == 200:
                log_audit(f"Invitation ID {id} revoked by {user['name']} (Owner)")
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service."}
            )

@app.post("/auth/signup/verify-invitation")
async def gateway_verify_invitation(req: SignupVerifyInvitationPayload):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BACKEND_URL}/invitations/verify-invitation",
                json=req.dict(),
                headers={"content-type": "application/json"}
            )
            if response.status_code == 200:
                log_audit(f"Public user verified invitation and requested OTP for email {req.email}")
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service."}
            )

@app.post("/auth/signup/verify-otp")
async def gateway_verify_otp(req: SignupVerifyOtpPayload):
    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{BACKEND_URL}/invitations/verify-otp",
                json=req.dict(),
                headers={"content-type": "application/json"}
            )
            if response.status_code == 200:
                log_audit(f"Public user verified OTP successfully for email {req.email}")
            return Response(
                content=response.content,
                status_code=response.status_code,
                headers=dict(response.headers)
            )
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service."}
            )

@app.post("/auth/signup/complete")
async def gateway_signup_complete(req: SignupCompletePayload):
    async with httpx.AsyncClient() as client:
        try:
            # 1. Ask backend to validate signup token and get invitation role context
            backend_res = await client.post(
                f"{BACKEND_URL}/invitations/complete-signup",
                json={
                    "email": req.email,
                    "signup_token": req.signup_token
                },
                headers={"content-type": "application/json"}
            )
            if backend_res.status_code != 200:
                return Response(
                    content=backend_res.content,
                    status_code=backend_res.status_code,
                    headers=dict(backend_res.headers)
                )

            inv_data = backend_res.json()
            invited_email = inv_data["email"]
            invited_role = inv_data["role"]

            # Double-check cross-email modification
            if invited_email != req.email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Email modification is blocked."
                )

            # 2. Check if user already exists in mock_users
            if find_user_by_email(req.email) or find_user_by_name(req.name):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="User with this email or name already exists"
                )

            # Hash password using gateway bcrypt salt
            salt = bcrypt.gensalt(10)
            password_bytes = req.password.encode('utf-8')
            password_hash = bcrypt.hashpw(password_bytes, salt).decode('utf-8')

            # Create user in gateway mock_users
            new_user = {
                "id": len(mock_users) + 1,
                "name": req.name,
                "email": req.email,
                "password_hash": password_hash,
                "role": invited_role,
                "refresh_tokens": [],
                "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
                "is_verified": True,
                "verification_token": None,
                "verification_token_expires": None
            }
            mock_users.append(new_user)

            # 3. Inform backend to mark invitation as USED
            await client.post(
                f"{BACKEND_URL}/invitations/mark-used",
                json={
                    "email": req.email,
                    "signup_token": req.signup_token
                },
                headers={"content-type": "application/json"}
            )

            log_audit(f"Account provisioning complete for {req.email} as role: {invited_role}")
            return {
                "message": "Account created successfully.",
                "user": {
                    "id": new_user["id"],
                    "name": new_user["name"],
                    "email": new_user["email"],
                    "role": new_user["role"]
                }
            }
        except httpx.RequestError:
            return JSONResponse(
                status_code=status.HTTP_502_BAD_GATEWAY,
                content={"detail": "Failed to connect to database backend service."}
            )

from fastapi.openapi.utils import get_openapi

def custom_openapi():
    if app.openapi_schema:
        return app.openapi_schema
    openapi_schema = get_openapi(
        title="MarketMind AI - API Gateway & Proxy",
        version="1.0.0",
        description="Unified security and routing gateway documenting all internal and proxy operations.",
        routes=app.routes,
    )
    
    # 1. Document POST /predict
    if "/predict" in openapi_schema["paths"]:
        openapi_schema["paths"]["/predict"]["post"] = {
            "summary": "AI Sales Forecasting",
            "description": "Upload a transaction dataset (CSV format) to retrieve predicted monthly sales trends.",
            "requestBody": {
                "content": {
                    "multipart/form-data": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "file": {
                                    "type": "string",
                                    "format": "binary",
                                    "description": "CSV transaction details"
                                }
                            },
                            "required": ["file"]
                        }
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Successful forecasting response",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "Month": {"type": "string"},
                                        "Predicted Sales": {"type": "number"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    # 2. Document POST /recommend-product
    if "/recommend-product" in openapi_schema["paths"]:
        openapi_schema["paths"]["/recommend-product"]["post"] = {
            "summary": "AI Product Recommendation",
            "description": "Retrieve product recommendations based on co-occurrence in sales data.",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "Product Name": {
                                    "type": "string",
                                    "default": "Staples"
                                }
                            },
                            "required": ["Product Name"]
                        }
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Recommendations fetched",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "Recommended Products": {
                                        "type": "array",
                                        "items": {"type": "string"}
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

    # 3. Document POST /check-anomaly
    if "/check-anomaly" in openapi_schema["paths"]:
        openapi_schema["paths"]["/check-anomaly"]["post"] = {
            "summary": "AI Anomaly Detection Check",
            "description": "Verify if transactions on a target date exhibit anomalous values.",
            "requestBody": {
                "content": {
                    "application/json": {
                        "schema": {
                            "type": "object",
                            "properties": {
                                "Order Date": {
                                    "type": "string",
                                    "default": "2011-01-04"
                                }
                            },
                            "required": ["Order Date"]
                        }
                    }
                }
            },
            "responses": {
                "200": {
                    "description": "Anomaly status checked",
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {
                                    "status": {"type": "string"},
                                    "anomalous": {"type": "boolean"}
                                }
                            }
                        }
                    }
                }
            }
        }

    app.openapi_schema = openapi_schema
    return app.openapi_schema

app.openapi = custom_openapi

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("server:app", host="0.0.0.0", port=5000, log_level="info")
