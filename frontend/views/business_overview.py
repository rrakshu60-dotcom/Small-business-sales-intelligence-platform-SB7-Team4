import streamlit as st
import pandas as pd
import requests
import plotly.express as px

from components.sidebar import show_sidebar
from components.cards import show_cards


# ============================================================
# API Configuration
# ============================================================
from config.config import DB_BASE_URL as BASE_URL
from services.sales_service import (
    fetch_all_sales_df,
    fetch_inventory_df,
    fetch_revenue_summary,
    clear_sales_cache
)

INVENTORY_API = f"{BASE_URL}/inventory/"
REVENUE_API = f"{BASE_URL}/revenue/summary"


# ============================================================
# Business Overview Page
# ============================================================

def business_overview_page():

    show_sidebar()

    st.title(" Business Overview")
    st.caption("Complete Business Performance Dashboard")

    st.markdown("---")

    with st.spinner("Loading Business Overview..."):
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

        # ---------------- Numeric Columns ---------------- #

        sales_numeric = [

            "quantity",

            "unit_price",

            "discount",

            "total_amount"

        ]

        for col in sales_numeric:

            if col in sales_df.columns:

                sales_df[col] = pd.to_numeric(

                    sales_df[col],

                    errors="coerce"

                ).fillna(0)

        inventory_numeric = [

            "stock_quantity",

            "low_stock_threshold"

        ]

        for col in inventory_numeric:

            if col in inventory_df.columns:

                inventory_df[col] = pd.to_numeric(

                    inventory_df[col],

                    errors="coerce"

                ).fillna(0)

        if "transaction_date" in sales_df.columns:

            sales_df["transaction_date"] = pd.to_datetime(

                sales_df["transaction_date"],

                errors="coerce"

            )
        # ============================================================
        # KPI Calculations
        # ============================================================

        if "total_amount" in sales_df.columns and not sales_df.empty:
            total_revenue = float(sales_df["total_amount"].sum())
        else:
            total_revenue = float(
                revenue.get(
                    "total_revenue",
                    0
                )
            )

        total_outstanding = float(
            revenue.get(
                "total_outstanding",
                0
            )
        )

        daily_collections = float(
            revenue.get(
                "daily_collections",
                0
            )
        )

        total_orders = len(
            sales_df
        )

        if "quantity" in sales_df.columns:

            total_products_sold = int(
                sales_df["quantity"].sum()
            )

        else:

            total_products_sold = 0

        inventory_count = len(
            inventory_df
        )

        if (
            "stock_quantity" in inventory_df.columns
            and
            "low_stock_threshold" in inventory_df.columns
        ):

            low_stock_df = inventory_df[

                inventory_df["stock_quantity"]

                <=

                inventory_df["low_stock_threshold"]

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

        # ============================================================
        # KPI Cards
        # ============================================================

        show_cards(metrics)

        st.markdown("---")

        st.subheader(
            "Revenue Overview"
        )

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

        st.markdown("---")
                # ============================================================
        # Top Selling Products
        # ============================================================

        st.subheader("Top Selling Products")

        if (
            "product_id" in sales_df.columns
            and
            "quantity" in sales_df.columns
        ):

            top_products = (

                sales_df

                .groupby(
                    "product_id",
                    as_index=False
                )["quantity"]

                .sum()

                .sort_values(
                    "quantity",
                    ascending=False
                )

                .head(10)

            )

            fig = px.bar(

                top_products,

                x="quantity",

                y="product_id",

                orientation="h",

                text="quantity",

                color="quantity",

                color_continuous_scale="Blues"

            )

            fig.update_layout(

                height=500,

                template="plotly_white",

                xaxis_title="Quantity Sold",

                yaxis_title="Product"

            )

            st.plotly_chart(

                fig,

                width="stretch"

            )

        else:

            st.info(
                "Top product data not available."
            )

        st.markdown("---")


        # ============================================================
        # Revenue By Category
        # ============================================================

        st.subheader("Revenue By Category")

        if (
            "category" in sales_df.columns
            and
            "total_amount" in sales_df.columns
        ):

            category_df = (

                sales_df

                .groupby(
                    "category",
                    as_index=False
                )["total_amount"]

                .sum()

                .sort_values(
                    "total_amount",
                    ascending=False
                )

            )

            fig = px.pie(

                category_df,

                names="category",

                values="total_amount",

                hole=0.45,

                color_discrete_sequence=px.colors.qualitative.Set3

            )

            fig.update_layout(

                height=450,

                template="plotly_white"

            )

            st.plotly_chart(

                fig,

                width="stretch"

            )

        else:

            st.info(
                "Category information not available."
            )

        st.markdown("---")
        # ============================================================
        # Product Drill Down
        # ============================================================

        st.subheader("Product Drill Down")

        if (
            "product_id" in sales_df.columns
            and
            not sales_df.empty
        ):

            products = sorted(
                sales_df["product_id"]
                .dropna()
                .astype(str)
                .unique()
            )

            selected_product = st.selectbox(
                "Select Product",
                products
            )

            product_df = sales_df[
                sales_df["product_id"].astype(str)
                == selected_product
            ]

            # ---------------- KPI Cards ---------------- #

            revenue_value = product_df[
                "total_amount"
            ].sum()

            quantity_value = int(
                product_df["quantity"].sum()
            )

            order_count = len(product_df)

            stock_left = "N/A"

            if (
                "product_id" in inventory_df.columns
                and
                "stock_quantity" in inventory_df.columns
            ):

                stock = inventory_df[
                    inventory_df["product_id"]
                    .astype(str)
                    == selected_product
                ]

                if not stock.empty:

                    stock_left = int(
                        stock.iloc[0]["stock_quantity"]
                    )

            c1, c2, c3, c4 = st.columns(4)

            c1.metric(
                "Revenue",
                f"₹ {revenue_value:,.2f}"
            )

            c2.metric(
                "Units Sold",
                quantity_value
            )

            c3.metric(
                "Orders",
                order_count
            )

            c4.metric(
                "Stock Left",
                stock_left
            )

            st.markdown("---")

           

            # ---------------- Recent Transactions ---------------- #

            st.subheader(
                "Recent Transactions"
            )

            columns = [

                "transaction_date",

                "invoice_id",

                "customer_id",

                "quantity",

                "total_amount"

            ]

            available_columns = [

                col

                for col in columns

                if col in product_df.columns

            ]

            if available_columns:

                st.dataframe(

                    product_df[
                        available_columns
                    ].sort_values(
                        by="transaction_date",
                        ascending=False
                    ),

                    width="stretch",

                    hide_index=True

                )

            else:

                st.info(
                    "Transaction details not available."
                )

        else:

            st.info(
                "Product information not available."
            )

        st.markdown("---")
        # ============================================================
        # Customer Insights
        # ============================================================

        
        st.subheader(" Customer Insights")

        customer_df = (
            sales_df.groupby("customer_id", as_index=False)
            .agg(
                Revenue=("total_amount", "sum"),
                Orders=("invoice_id", "nunique")
            )
        )

        customer_df = customer_df.sort_values(
            "Revenue",
            ascending=False
        ).head(10)

        if customer_df.empty:

            st.info("No customer data available.")

        else:

            fig = px.bar(
                customer_df,
                x="Revenue",
                y="customer_id",
                orientation="h",
                text="Revenue",
                title=" Top 10 Customers by Revenue",
                color="Revenue",
            )

            fig.update_traces(
                texttemplate="₹%{text:.2f}",
                textposition="outside"
            )

            fig.update_layout(
                template="plotly_dark",
                height=500,
                xaxis_title="Revenue (₹)",
                yaxis_title="Customer ID",
                yaxis=dict(autorange="reversed")
            )

            st.plotly_chart(
                fig,
                use_container_width=True
            )

            st.dataframe(
                customer_df,
                use_container_width=True,
                hide_index=True
            )

        # ============================================================
        # Business Alerts
        # ============================================================

        st.subheader("Business Alerts")

        if len(low_stock_df) > 0:

            st.warning(

                f"{len(low_stock_df)} products are below the stock threshold."

            )

        else:

            st.success(
                "No low stock products."
            )

        if total_outstanding > 0:

            st.warning(

                f"Outstanding Payments : ₹ {total_outstanding:,.2f}"

            )

        else:

            st.success(
                "No outstanding payments."
            )

        st.markdown("---")


        # ============================================================
        # Recent Sales
        # ============================================================

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

            col

            for col in display_columns

            if col in sales_df.columns

        ]

        if available_columns:

            st.dataframe(

                sales_df

                .sort_values(
                    by="transaction_date",
                    ascending=False
                )[available_columns]

                .head(10),

                width="stretch",

                hide_index=True

            )

        else:

            st.info(
                "No recent sales available."
            )

        st.markdown("---")


        # ============================================================
        # Revenue Summary
        # ============================================================

        st.subheader("Revenue Summary")

        summary = pd.DataFrame({

            "Metric": [

                "Revenue",

                "Outstanding",

                "Today's Collection",

                "Orders",

                "Products Sold",

                "Inventory",

                "Low Stock"

            ],

            "Value": [
                f"₹ {total_revenue:,.2f}",
                f"₹ {total_outstanding:,.2f}",
                f"₹ {daily_collections:,.2f}",
                str(total_orders),
                str(total_products_sold),
                str(inventory_count),
                str(len(low_stock_df))
            ]
        })

        st.dataframe(

            summary,

            width="stretch",

            hide_index=True

        )

        st.markdown("---")


        # ============================================================
        # Export Report
        # ============================================================

        st.subheader("Export Report")

        csv = sales_df.to_csv(
            index=False
        ).encode("utf-8")

        st.download_button(

            label="Download Business Report",

            data=csv,

            file_name="business_overview_report.csv",

            mime="text/csv",

            width="stretch"

        )

       

        st.caption(
            "MarketMind AI • Business Overview • Version 2.0"
        )
    # ============================================================
    # Exception Handling
    # ============================================================

    except requests.exceptions.Timeout:

        st.error(
            "Backend request timed out. Please try again."
        )

    except requests.exceptions.ConnectionError:

        st.error(
            "Unable to connect to the backend server."
        )

    except requests.exceptions.HTTPError as e:

        st.error(
            f"API Error: {e}"
        )

        try:

            error_response = e.response.json()

            st.json(error_response)

        except Exception:

            if e.response is not None:

                st.code(e.response.text)

    except ValueError as e:

        st.error(
            f"Data Processing Error: {e}"
        )

    except KeyError as e:

        st.error(
            f"Missing Required Column: {e}"
        )

    except Exception as e:

        st.exception(e)