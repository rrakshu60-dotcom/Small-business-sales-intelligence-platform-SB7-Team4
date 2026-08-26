import streamlit as st
import pandas as pd
import requests

from components.sidebar import show_sidebar

# ================= API Configuration ================= #
from config.config import DB_BASE_URL as BASE_URL

PAYMENT_API = f"{BASE_URL}/payments/"


@st.cache_data(ttl=300, show_spinner=False)
def fetch_payments_data(api_url):
    response = requests.get(api_url, timeout=15)
    response.raise_for_status()
    data = response.json()
    return data if isinstance(data, list) else []


def payments_page():

    show_sidebar()

    pay_hcol1, pay_hcol2 = st.columns([5, 1])
    with pay_hcol1:
        st.title("Payments")
        st.caption("Manage Customer Payments")
    with pay_hcol2:
        if st.button("🔄 Refresh", key="refresh_payments_btn", width="stretch"):
            fetch_payments_data.clear()
            st.rerun()

    st.markdown("---")

    # ================= Add Payment ================= #

    st.subheader("Add Payment")

    col1, col2 = st.columns(2)

    with col1:

        invoice_id = st.text_input(
            "Invoice ID",
            placeholder="INV900001"
        )

        payment_date = st.date_input(
            "Payment Date"
        )

        amount_paid = st.number_input(
            "Amount Paid",
            min_value=0.0,
            value=0.0,
            step=1.0
        )

    with col2:

        payment_method = st.selectbox(
            "Payment Method",
            [
                "UPI",
                "Cash",
                "Card",
                "Net Banking"
            ]
        )

        transaction_reference = st.text_input(
            "Transaction Reference",
            placeholder="UPI900001"
        )

        remarks = st.text_area(
            "Remarks",
            placeholder="Full Payment"
        )

    payload = {

        "invoice_id": invoice_id,

        "payment_date": str(payment_date),

        "amount_paid": amount_paid,

        "payment_method": payment_method,

        "transaction_reference": transaction_reference,

        "remarks": remarks

    }

    if st.button(
        "Add Payment",
        width="stretch"
    ):

        if not invoice_id.strip():
            st.warning("Please enter Invoice ID.")
        elif amount_paid <= 0:
            st.warning("Please enter a valid amount paid (greater than 0).")
        else:

            try:

                with st.spinner("Creating Payment..."):

                    response = requests.post(
                        PAYMENT_API,
                        json=payload,
                        timeout=30
                    )

                if response.status_code in [200, 201]:

                    st.success("Payment Added Successfully")
                    fetch_payments_data.clear()
                    st.balloons()
                else:
                    try:
                        err_detail = response.json().get("detail", f"Failed (HTTP {response.status_code})")
                    except Exception:
                        err_detail = f"Failed (HTTP {response.status_code})"
                    st.error(err_detail)

            except requests.exceptions.ConnectionError:

                st.error(
                    "❌ Unable to connect to backend."
                )

            except requests.exceptions.Timeout:

                st.error(
                    "❌ Request timed out."
                )

            except Exception as e:

                st.error(str(e))

    st.markdown("---")

    # ================= Load Payments ================= #

    try:
        with st.spinner("Loading Payments..."):
            payments = fetch_payments_data(PAYMENT_API)
        df = pd.DataFrame(payments)

    except Exception as e:

        st.error(
            f"Unable to load payments: {e}"
        )

        return

    if df.empty:

        st.warning("No payment records found.")

        return
        # ================= Dashboard Metrics ================= #

    df["amount_paid"] = pd.to_numeric(
        df["amount_paid"],
        errors="coerce"
    ).fillna(0)

    total_payments = len(df)

    total_amount = df["amount_paid"].sum()

    payment_methods = (
        df["payment_method"].nunique()
        if "payment_method" in df.columns
        else 0
    )

    c1, c2, c3 = st.columns(3)

    c1.metric(
        "Total Payments",
        total_payments
    )

    c2.metric(
        "Amount Received",
        f"₹ {total_amount:,.2f}"
    )

    c3.metric(
        "Payment Methods",
        payment_methods
    )

    st.markdown("---")

    # ================= Search & Filter ================= #

    col1, col2 = st.columns(2)

    with col1:

        search = st.text_input(
            "Search Invoice / Transaction"
        )

    with col2:

        methods = ["All"]

        if "payment_method" in df.columns:

            methods += sorted(
                df["payment_method"]
                .dropna()
                .unique()
                .tolist()
            )

        selected_method = st.selectbox(
            "Payment Method",
            methods
        )

    filtered_df = df.copy()

    if search:

        filtered_df = filtered_df[
            filtered_df.astype(str)
            .apply(
                lambda row:
                row.str.contains(
                    search,
                    case=False
                ).any(),
                axis=1
            )
        ]

    if (
        selected_method != "All"
        and "payment_method" in filtered_df.columns
    ):

        filtered_df = filtered_df[
            filtered_df["payment_method"]
            == selected_method
        ]

    st.markdown("---")

    # ================= Payment Records ================= #

    st.subheader("Payment Records")

    display_columns = [

        "payment_id",

        "invoice_id",

        "payment_date",

        "amount_paid",

        "payment_method",

        "transaction_reference",

        "remarks"

    ]

    available_columns = [

        col for col in display_columns

        if col in filtered_df.columns

    ]

    st.dataframe(

        filtered_df[available_columns],

        use_container_width=True,

        hide_index=True

    )

    st.markdown("---")

    # ================= Payment Summary ================= #

    st.subheader(" Payment Summary")

    summary = pd.DataFrame({

        "Metric": [

            "Total Payments",

            "Amount Received",

            "Payment Methods"
        ],
        "Value": [
            str(total_payments),
            f"₹ {total_amount:,.2f}",
            str(payment_methods)
        ]
    })

    st.dataframe(

        summary,

        use_container_width=True,

        hide_index=True

    )

    st.markdown("---")

    # ================= Download ================= #

    st.download_button(

        "Download Payments CSV",

        data=filtered_df.to_csv(index=False),

        file_name="payments.csv",

        mime="text/csv",

        use_container_width=True

    )

    st.success(
        "Payments loaded successfully from the backend."
    )