import streamlit as st
import pandas as pd
import requests

from components.sidebar import show_sidebar
from components.cards import show_cards
from components.charts import (
    sales_trend_chart,
    top_products_chart
)

# ---------------- API Configuration ---------------- #
from config.config import DB_BASE_URL as BASE_URL
from services.sales_service import (
    fetch_all_sales_df,
    fetch_inventory_df,
    fetch_revenue_summary,
    clear_sales_cache
)

INVENTORY_API = f"{BASE_URL}/inventory/"
REVENUE_API = f"{BASE_URL}/revenue/summary"


# ---------------- Dashboard ---------------- #

def dashboard_page():

    show_sidebar()

    st.title("MarketMind AI Dashboard")
    st.caption("Small Business Sales Intelligence Platform")

    st.markdown("---")

    with st.spinner("Loading Dashboard..."):
        sales_df = fetch_all_sales_df(BASE_URL)
        inventory_df = fetch_inventory_df(BASE_URL)
        revenue = fetch_revenue_summary(BASE_URL)

    if sales_df.empty and inventory_df.empty:
        clear_sales_cache()
        st.warning("⚠️ The remote database server is currently sleeping or experiencing connection issues on Render. The dashboard will automatically update once it wakes up.")
        st.info("💡 Please wait 10-15 seconds and try refreshing the page, or verify the database service status in your Render dashboard.")
        return

    try:
        if sales_df.empty:
            clear_sales_cache()
            st.warning("No Sales Data Available. If your backend database recently restarted, please wait a few seconds and refresh.")
            return

        if inventory_df.empty:
            inventory_df = pd.DataFrame(columns=["id", "product_id", "product_name", "category", "stock_quantity", "low_stock_threshold"])

        # ---------------- Numeric Conversion ---------------- #

        numeric_sales = [
            "quantity",
            "unit_price",
            "discount",
            "total_amount"
        ]

        for col in numeric_sales:

            if col in sales_df.columns:

                sales_df[col] = pd.to_numeric(
                    sales_df[col],
                    errors="coerce"
                ).fillna(0)

        numeric_inventory = [
            "stock_quantity",
            "low_stock_threshold"
        ]

        for col in numeric_inventory:

            if col in inventory_df.columns:

                inventory_df[col] = pd.to_numeric(
                    inventory_df[col],
                    errors="coerce"
                ).fillna(0)

        # ---------------- Date Conversion ---------------- #

        if "transaction_date" in sales_df.columns:

            sales_df["transaction_date"] = pd.to_datetime(
                sales_df["transaction_date"],
                errors="coerce"
            )

            sales_df = sales_df.sort_values(
                by="transaction_date",
                ascending=False
            )
                # ---------------- KPI Values ---------------- #

        if "total_amount" in sales_df.columns and not sales_df.empty:
            total_revenue = float(sales_df["total_amount"].sum())
        else:
            total_revenue = float(
                revenue.get("total_revenue") or 0
            )

        total_outstanding = float(
            revenue.get("total_outstanding") or 0
        )

        daily_collections = float(
            revenue.get("daily_collections") or 0
        )

        total_orders = len(sales_df)

        if "quantity" in sales_df.columns:
            total_products_sold = int(
                sales_df["quantity"].sum()
            )
        else:
            total_products_sold = 0

        inventory_count = len(inventory_df)

        if (
            "stock_quantity" in inventory_df.columns
            and
            "low_stock_threshold" in inventory_df.columns
        ):

            low_stock_df = inventory_df[
                inventory_df["stock_quantity"]
                <= inventory_df["low_stock_threshold"]
            ]

        else:

            low_stock_df = pd.DataFrame()

        metrics = {

            "Revenue": total_revenue,

            "Outstanding": total_outstanding,

            "Today's Collection": daily_collections,

            "Orders": total_orders,

            "Products Sold": total_products_sold,

            "Inventory": inventory_count,

            "Low Stock": len(low_stock_df)

        }

        # ---------------- KPI Cards ---------------- #

        show_cards(metrics)

        st.markdown("---")

        # ---------------- Charts ---------------- #

        col1, col2 = st.columns(2)

        with col1:

            sales_trend_chart(sales_df)

        with col2:

            top_products_chart(sales_df)

        st.markdown("---")  
                # ---------------- Recent Sales ---------------- #

        st.subheader("Recent Sales")

        display_columns = [
            "transaction_id",
            "invoice_id",
            "transaction_date",
            "customer_id",
            "product_id",
            "quantity",
            "total_amount"
        ]

        available_columns = [
            col for col in display_columns
            if col in sales_df.columns
        ]

        if available_columns:

            st.dataframe(
                sales_df[available_columns].head(10),
                width="stretch",
                hide_index=True
            )

        else:

            st.info("No recent sales data available.")

        st.markdown("---")

        # ---------------- Low Stock Items ---------------- #

        st.subheader("Low Stock Items")

        if low_stock_df.empty:

            st.success("No Low Stock Items")

        else:

            display_inventory = [
                "id",
                "product_id",
                "stock_quantity",
                "low_stock_threshold"
            ]

            available_inventory = [
                col for col in display_inventory
                if col in low_stock_df.columns
            ]

            if available_inventory:

                st.dataframe(
                    low_stock_df[available_inventory],
                    width="stretch",
                    hide_index=True
                )

            else:

                st.info("Inventory columns not available.")

        st.markdown("---")

        # ---------------- Revenue Summary ---------------- #

        st.subheader("Revenue Summary")

        c1, c2, c3 = st.columns(3)

        c1.metric(
            "Total Revenue",
            f"₹ {total_revenue:,.2f}"
        )

        c2.metric(
            "Outstanding",
            f"₹ {total_outstanding:,.2f}"
        )

        c3.metric(
            "Today's Collection",
            f"₹ {daily_collections:,.2f}"
        )

        

       

    except requests.exceptions.Timeout:

        st.error("Backend request timed out.")

    except requests.exceptions.ConnectionError:

        st.error("Unable to connect to backend.")

    except requests.exceptions.HTTPError as e:

        st.error(f"API Error: {e}")

    except Exception as e:

        st.error(f"Unexpected Error: {e}")