import streamlit as st
import re
import requests
import time
from config.config import AUTH_BASE_URL as BASE_URL
from services.auth_service import save_auth_session
from services.email_dispatch import send_password_reset_otp_email, save_email_credentials, is_email_configured


def login_page():

    # --------------------------------------------------
    # SESSION STATE
    # --------------------------------------------------

    if "page" not in st.session_state:
        st.session_state.page = "Login"

    if "password_visible" not in st.session_state:
        st.session_state.password_visible = False

    if "forgot_password" not in st.session_state:
        st.session_state.forgot_password = False

    # --------------------------------------------------
    # FORGOT PASSWORD PAGE
    # --------------------------------------------------

    # Initialize state variables for OTP flow
    if "forgot_step" not in st.session_state:
        st.session_state.forgot_step = 1
    if "forgot_email" not in st.session_state:
        st.session_state.forgot_email = ""

    if st.session_state.forgot_password:

        left, center, right = st.columns([1, 2, 1])

        with center:
            st.title("Forgot Password")
            st.caption("Reset your MarketMind AI password via secure OTP verification")
            st.markdown("---")

            # ==================================================
            # STEP 1: Enter Email & Request OTP
            # ==================================================
            if st.session_state.forgot_step == 1:
                email = st.text_input(
                    "Email",
                    placeholder="Enter your registered email address"
                )
                st.caption("A 6-digit One-Time Password (OTP) will be sent to this email address.")

                if st.button("Send Reset Email", width="stretch", type="primary"):
                    if email.strip() == "":
                        st.error("Please enter your email address.")
                    elif not re.match(r"[^@]+@[^@]+\.[^@]+", email.strip()):
                        st.error("Please enter a valid email address.")
                    else:
                        email_clean = email.strip().lower()
                        with st.spinner("Connecting to security gateway & sending OTP..."):
                            try:
                                res = requests.post(
                                    f"{BASE_URL}/auth/forgot-password",
                                    json={"email": email_clean},
                                    headers={"x-bypass-rate-limit": "true"},
                                    timeout=35
                                )
                                if res.status_code == 200:
                                    res_data = res.json()
                                    otp_val = str(res_data.get("otp", "")).strip()
                                    st.session_state.forgot_email = email_clean
                                    st.session_state.forgot_otp = otp_val

                                    # Attempt direct email dispatch using Streamlit secrets
                                    email_sent = False
                                    dispatch_err = ""
                                    try:
                                        from services.email_dispatch import send_password_reset_otp_email
                                        d_res = send_password_reset_otp_email(email_clean, otp_val)
                                        email_sent = bool(d_res.get("success"))
                                        dispatch_err = str(d_res.get("error", ""))
                                    except Exception as ex:
                                        dispatch_err = str(ex)

                                    st.session_state.forgot_email_sent = email_sent
                                    st.session_state.forgot_dispatch_error = dispatch_err
                                    st.session_state.forgot_step = 2
                                    st.rerun()
                                elif res.status_code == 404:
                                    st.error("❌ No account found with this email address. Please check your email or register.")
                                elif res.status_code == 429:
                                    st.error("⏳ Rate limit exceeded. Please wait a moment before trying again.")
                                else:
                                    err_detail = res.json().get("detail", res.text) if res.text else "Unknown error"
                                    st.error(f"❌ Failed to request password reset ({res.status_code}): {err_detail}")
                            except requests.exceptions.Timeout:
                                st.warning("⚠️ Connection timed out while waking up the Render API Gateway server. The server is waking up from idle mode — please click 'Send Reset Email' once more.")
                            except Exception as e:
                                st.error(f"❌ Could not connect to API Gateway ({BASE_URL}): {str(e)}")

            # ==================================================
            # STEP 2: Enter OTP & Reset Password
            # ==================================================
            elif st.session_state.forgot_step == 2:
                if st.session_state.get("forgot_email_sent") is True:
                    st.success(f"📧 A 6-digit OTP verification code has been dispatched to **{st.session_state.forgot_email}**! Please check your inbox and spam folder.")
                else:
                    err_msg = st.session_state.get("forgot_dispatch_error", "")
                    if err_msg and ("BadCredentials" in err_msg or "535" in err_msg):
                        st.warning("⚠️ **Gmail Authentication Error**: Google rejected the App Password (`BadCredentials`). Please verify that 2-Step Verification is active and generate a fresh 16-character password at [Google App Passwords](https://myaccount.google.com/apppasswords).")
                    elif err_msg:
                        st.warning(f"⚠️ Email could not be sent ({err_msg}).")

                    if st.session_state.get("forgot_otp"):
                        st.info(
                            f"🔑 **OTP Verification Code:** `{st.session_state.forgot_otp}`\n\n"
                            f"*(You can enter this 6-digit code below to reset your password without waiting for email delivery).* "
                        )

                otp = st.text_input(
                    "Enter 6-Digit OTP",
                    value="",
                    max_chars=6,
                    placeholder="Enter the 6-digit OTP code"
                )

                new_password = st.text_input(
                    "New Password",
                    type="password",
                    placeholder="Enter new password (min. 6 characters)"
                )

                confirm_password = st.text_input(
                    "Confirm Password",
                    type="password",
                    placeholder="Confirm new password"
                )
                st.caption("Password must contain at least 6 characters.")

                col1, col2 = st.columns(2)

                with col1:
                    if st.button("Reset Password", width="stretch", type="primary"):
                        entered_otp = otp.strip()
                        if entered_otp == "":
                            st.error("Please enter the 6-digit OTP code.")
                        elif new_password.strip() == "":
                            st.error("Please enter a new password.")
                        elif len(new_password) < 6:
                            st.error("Password must be at least 6 characters.")
                        elif new_password != confirm_password:
                            st.error("Passwords do not match.")
                        else:
                            with st.spinner("Verifying OTP & resetting password..."):
                                try:
                                    # 1. Verify OTP with Gateway
                                    verify_res = requests.post(
                                        f"{BASE_URL}/auth/verify-otp",
                                        json={"email": st.session_state.forgot_email, "otp": entered_otp},
                                        headers={"x-bypass-rate-limit": "true"},
                                        timeout=30
                                    )
                                    if verify_res.status_code == 200:
                                        reset_token = verify_res.json().get("reset_token")
                                        # 2. Reset password on Gateway
                                        reset_res = requests.post(
                                            f"{BASE_URL}/auth/reset-password",
                                            json={
                                                "email": st.session_state.forgot_email,
                                                "reset_token": reset_token,
                                                "new_password": new_password
                                            },
                                            headers={"x-bypass-rate-limit": "true"},
                                            timeout=30
                                        )
                                        if reset_res.status_code == 200:
                                            st.session_state.reset_success_msg = "🎉 Password reset successfully! Please sign in with your new password."
                                            st.session_state.default_username = st.session_state.forgot_email
                                            st.session_state.forgot_password = False
                                            st.session_state.forgot_step = 1
                                            st.session_state.forgot_email = ""
                                            if "forgot_otp" in st.session_state:
                                                del st.session_state["forgot_otp"]
                                            if "forgot_email_sent" in st.session_state:
                                                del st.session_state["forgot_email_sent"]
                                            if "forgot_dispatch_error" in st.session_state:
                                                del st.session_state["forgot_dispatch_error"]
                                            st.rerun()
                                        else:
                                            err_msg = reset_res.json().get("detail", "Password reset failed.")
                                            st.error(f"❌ Password update failed: {err_msg}")
                                    else:
                                        err_msg = verify_res.json().get("detail", "Invalid OTP code.")
                                        st.error(f"❌ OTP verification failed: {err_msg}")
                                except requests.exceptions.Timeout:
                                    st.warning("⚠️ Request timed out. Please try again.")
                                except Exception as e:
                                    st.error(f"❌ Connection error during password reset: {str(e)}")

                with col2:
                    if st.button("Resend OTP", width="stretch"):
                        with st.spinner("Requesting new OTP code..."):
                            try:
                                res = requests.post(
                                    f"{BASE_URL}/auth/forgot-password",
                                    json={"email": st.session_state.forgot_email},
                                    headers={"x-bypass-rate-limit": "true"},
                                    timeout=35
                                )
                                if res.status_code == 200:
                                    res_data = res.json()
                                    otp_val = str(res_data.get("otp", "")).strip()
                                    st.session_state.forgot_otp = otp_val

                                    email_sent = False
                                    dispatch_err = ""
                                    try:
                                        from services.email_dispatch import send_password_reset_otp_email
                                        d_res = send_password_reset_otp_email(st.session_state.forgot_email, otp_val)
                                        email_sent = bool(d_res.get("success"))
                                        dispatch_err = str(d_res.get("error", ""))
                                    except Exception as ex:
                                        dispatch_err = str(ex)

                                    st.session_state.forgot_email_sent = email_sent
                                    st.session_state.forgot_dispatch_error = dispatch_err
                                    st.success("✅ A new OTP code has been generated!")
                                    st.rerun()
                                else:
                                    err_msg = res.json().get("detail", "Failed to resend OTP.")
                                    st.error(f"❌ Could not resend OTP: {err_msg}")
                            except requests.exceptions.Timeout:
                                st.warning("⚠️ Request timed out while server was waking up. Please try again.")
                            except Exception as e:
                                st.error(f"❌ Error communicating with Gateway: {str(e)}")

            st.markdown("---")

            if st.button("⬅ Back to Login", width="stretch"):
                st.session_state.forgot_password = False
                st.session_state.forgot_step = 1
                st.session_state.forgot_email = ""
                if "forgot_otp" in st.session_state:
                    del st.session_state["forgot_otp"]
                if "forgot_email_sent" in st.session_state:
                    del st.session_state["forgot_email_sent"]
                if "forgot_dispatch_error" in st.session_state:
                    del st.session_state["forgot_dispatch_error"]
                st.rerun()

        return

    # --------------------------------------------------
    # LOGIN PAGE
    # --------------------------------------------------

    left, center, right = st.columns([1, 2, 1])

    with center:

        st.title("MarketMind AI Login")
        st.caption("Please sign in to continue")
        st.caption(f"Security Gateway: `{BASE_URL}`")
        st.markdown("---")

        if st.session_state.get("reset_success_msg"):
            st.success(st.session_state.reset_success_msg)
            del st.session_state["reset_success_msg"]

        # --------------------------------------------------
        # USERNAME
        # --------------------------------------------------

        username = st.text_input(
            "Username or Email",
            value=st.session_state.get("default_username", ""),
            placeholder="Enter Username or Email"
        )

        # --------------------------------------------------
        # PASSWORD
        # --------------------------------------------------

        password = st.text_input(
            "Password",
            type="password",
            placeholder="Enter Password"
        )

        st.caption(
            "Password must contain at least 6 characters."
        )

        # --------------------------------------------------
        # ROLE
        # --------------------------------------------------

        role = st.selectbox(
            "Select Role",
            (
                "Owner",
                "Store Manager",
                "Sales Executive",
                "Admin"
            )
        )

        # --------------------------------------------------
        # FORGOT PASSWORD
        # --------------------------------------------------

        if st.button(
            "Forgot Password?",
            width="stretch"
        ):

            st.session_state.forgot_password = True
            st.rerun()

        st.markdown("")

        # --------------------------------------------------
        # SIGN IN
        # --------------------------------------------------

        if st.button(
            "Sign In",
            width="stretch"
        ):

            if username.strip() == "" or password.strip() == "":
                st.error(
                    "Please enter Username and Password."
                )

            elif len(username) < 3:
                st.error(
                    "Username must contain at least 3 characters."
                )

            elif len(password) < 4:
                st.error(
                    "Password must contain at least 4 characters."
                )

            elif not re.fullmatch(
                r"[A-Za-z0-9@._+-]{3,}",
                username
            ):
                st.error(
                    "Username can contain only letters, numbers, @ . _ + -"
                )

            elif not re.fullmatch(
                r"[A-Za-z0-9@#$%^&*!._-]{6,}",
                password
            ):
                st.error(
                    "Password contains invalid characters."
                )

            else:
                try:
                    res = requests.post(f"{BASE_URL}/auth/login", json={
                        "email": username,
                        "password": password
                    }, headers={"x-bypass-rate-limit": "true"}, timeout=30)
                    
                    if res.status_code == 200:
                        try:
                            login_data = res.json()
                            st.success("Login Successful!")
                            st.session_state.logged_in = True
                            st.session_state.username = login_data["user"]["name"]
                            st.session_state.role = login_data["user"]["role"]
                            st.session_state.token = login_data["token"]
                            st.session_state.page = "Dashboard"
                            save_auth_session(
                                username=login_data["user"]["name"],
                                role=login_data["user"]["role"],
                                token=login_data["token"],
                                email=username
                            )
                            st.rerun()
                        except Exception:
                            st.error("Login failed: The gateway returned an invalid response. It may still be starting up.")
                    elif res.status_code == 401:
                        st.error("Login failed: Invalid email or password.")
                    elif res.status_code == 403:
                        st.error("Login failed: Email address not verified.")
                        st.session_state.unverified_email = username
                    elif res.status_code in [502, 503, 504]:
                        st.error("Login failed (HTTP 502/503). The remote API Gateway is starting up on Render. Please wait 10-20 seconds and try signing in again.")
                    else:
                        try:
                            detail = res.json().get("detail", "Login failed.")
                        except Exception:
                            detail = f"Gateway error (HTTP {res.status_code})."
                        st.error(f"Login failed: {detail}")
                except Exception as e:
                    # Provide user-friendly warning for Render cold starts / timeouts
                    if "timeout" in str(e).lower() or "read timed out" in str(e).lower():
                        st.error("Cannot connect to the backend security gateway: Connection timed out. The remote server is likely waking up on Render. Please try again in 10-15 seconds.")
                    else:
                        st.error(f"Cannot connect to the backend security gateway: {str(e)}")

        if st.session_state.get("unverified_email"):
            st.markdown("---")
            st.subheader("Verify Your Email Address")
            st.info(f"Please check your inbox at **{st.session_state.unverified_email}** for a 6-character alphanumeric verification code.")
            
            code_input = st.text_input("Enter Verification Code", key="unverified_code_input", placeholder="e.g. A1B2C3")
            
            col1, col2 = st.columns(2)
            with col1:
                if st.button("Submit Verification Code", use_container_width=True):
                    if not code_input.strip():
                        st.error("Please enter the code.")
                    else:
                        try:
                            verify_res = requests.post(
                                f"{BASE_URL}/auth/verify-email",
                                json={"token": code_input.strip().upper()},
                                headers={"x-bypass-rate-limit": "true"}
                            )
                            if verify_res.status_code == 200:
                                st.success("Email verified successfully! You can now log in.")
                                st.session_state.unverified_email = None
                                time.sleep(1.5)
                                st.rerun()
                            else:
                                detail = verify_res.json().get("detail", "Invalid verification code.")
                                st.error(f"Verification failed: {detail}")
                        except Exception as e:
                            st.error(f"Cannot connect to the gateway: {str(e)}")
                            
            with col2:
                if st.button("Resend Verification Code", use_container_width=True):
                    try:
                        resend_res = requests.post(
                            f"{BASE_URL}/auth/resend-verification",
                            json={"email": st.session_state.unverified_email},
                            headers={"x-bypass-rate-limit": "true"}
                        )
                        if resend_res.status_code == 200:
                            st.success(f"✅ Verification code resent successfully to **{st.session_state.unverified_email}**! Please check your inbox.")
                        else:
                            detail = resend_res.json().get("detail", "Failed to resend.")
                            st.error(f"Resend failed: {detail}")
                    except Exception as e:
                        st.error(f"Cannot connect to the gateway: {str(e)}")

        st.markdown("---")

        # --------------------------------------------------
        # SIGN UP REDIRECT
        # --------------------------------------------------

        if st.button(
            "🔑 Don't have an account? Sign up here",
            width="stretch"
        ):
            st.session_state.page = "Signup"
            st.rerun()

        st.markdown("---")

        # --------------------------------------------------
        # BACK TO HOME
        # --------------------------------------------------

        if st.button(
            "⬅ Back to Home",
            width="stretch"
        ):

            st.session_state.page = "Home"
            st.rerun()


# --------------------------------------------------
# RUN
# --------------------------------------------------

if __name__ == "__main__":
    login_page()