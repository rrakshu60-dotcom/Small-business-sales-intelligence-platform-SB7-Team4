import os

# Discover from Streamlit st.secrets if running on Streamlit Cloud
try:
    import streamlit as st
    if hasattr(st, "secrets"):
        for k in ["AUTH_BASE_URL", "DB_BASE_URL", "SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "EMAIL_FROM"]:
            if k in st.secrets and not os.getenv(k):
                os.environ[k] = str(st.secrets[k])
except Exception:
    pass

# Central Config for Frontend APIs
AUTH_BASE_URL = os.getenv("AUTH_BASE_URL", "https://api-gateway-kwnl.onrender.com")      # Your Gateway link (Port 5000)
DB_BASE_URL = os.getenv("DB_BASE_URL", "https://small-business-sales-intelligence.onrender.com")     # Teammate's Database (Port 8000)
