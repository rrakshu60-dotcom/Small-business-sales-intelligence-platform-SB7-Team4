import streamlit as st
import pandas as pd
import requests
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from config.config import DB_BASE_URL


@st.cache_data(ttl=120, show_spinner=False)
def fetch_all_sales(base_url=DB_BASE_URL):
    """
    Fetch all sales transactions from backend with session pooling and concurrency.
    Returns raw list preserving 100% of data.
    """
    session = requests.Session()
    url_p1 = f"{base_url}/sales/?page=1&page_size=2000"
    first_page = None
    
    # 1. Fetch first page (handling possible Render cold-start)
    for attempt in range(3):
        try:
            timeout = 15 if attempt == 0 else 60
            r = session.get(url_p1, timeout=timeout)
            r.raise_for_status()
            first_page = r.json()
            break
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError):
            if attempt == 2:
                fetch_all_sales.clear()
                return []
            time.sleep(2)
        except Exception:
            fetch_all_sales.clear()
            return []

    if not first_page or not isinstance(first_page, list):
        fetch_all_sales.clear()
        return []

    # If dataset fits in 1 page, return immediately
    if len(first_page) < 2000:
        return first_page

    # 2. Multi-page fetch using ThreadPoolExecutor
    all_pages = {1: first_page}
    page = 2
    done = False

    def _fetch_single_page(p):
        for retry in range(3):
            try:
                res = session.get(f"{base_url}/sales/?page={p}&page_size=2000", timeout=30)
                res.raise_for_status()
                data = res.json()
                return p, data if isinstance(data, list) else []
            except Exception:
                if retry == 2:
                    return p, []
                time.sleep(1)
        return p, []

    with ThreadPoolExecutor(max_workers=4) as executor:
        while not done:
            batch_pages = list(range(page, page + 4))
            futures = [executor.submit(_fetch_single_page, p) for p in batch_pages]
            for f in as_completed(futures):
                p, data = f.result()
                all_pages[p] = data

            for p in batch_pages:
                page_data = all_pages.get(p, [])
                if len(page_data) < 2000:
                    done = True
                    break
            page += 4

    # Assemble records strictly ordered by page
    ordered_sales = []
    for p in sorted(all_pages.keys()):
        ordered_sales.extend(all_pages[p])

    return ordered_sales


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_base_sales_df(base_url=DB_BASE_URL):
    """
    Returns pre-processed base sales DataFrame cached in memory to eliminate
    repetitive dataframe conversion and date parsing latency on reruns.
    """
    sales = fetch_all_sales(base_url)
    if not sales:
        _fetch_base_sales_df.clear()
        return pd.DataFrame()

    df = pd.DataFrame(sales)

    numeric_sales = [
        "quantity",
        "unit_price",
        "discount",
        "total_amount"
    ]
    for col in numeric_sales:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)

    if "transaction_date" in df.columns:
        df["transaction_date"] = pd.to_datetime(
            df["transaction_date"],
            errors="coerce"
        )
        df = df.sort_values(
            by="transaction_date",
            ascending=False
        )

    return df


def fetch_all_sales_df(base_url=DB_BASE_URL):
    """
    Returns complete sales DataFrame (base database sales + all active custom uploaded CSVs)
    reflecting instant app-wide updates when files are appended or removed.
    """
    base_df = _fetch_base_sales_df(base_url)
    uploaded_files = st.session_state.get("uploaded_sales_files", [])
    
    if not uploaded_files:
        return base_df.copy() if not base_df.empty else pd.DataFrame()

    appended_dfs = [f["df"] for f in uploaded_files if "df" in f and isinstance(f["df"], pd.DataFrame) and not f["df"].empty]
    if not appended_dfs:
        return base_df.copy() if not base_df.empty else pd.DataFrame()

    if base_df.empty:
        combined = pd.concat(appended_dfs, ignore_index=True)
    else:
        combined = pd.concat([base_df] + appended_dfs, ignore_index=True)

    if "transaction_date" in combined.columns:
        combined["transaction_date"] = pd.to_datetime(combined["transaction_date"], errors="coerce")
        combined = combined.sort_values(by="transaction_date", ascending=False)

    return combined


@st.cache_data(ttl=120, show_spinner=False)
def fetch_inventory_data(base_url=DB_BASE_URL):
    """Fetch all inventory records from backend with memory caching."""
    url = f"{base_url}/inventory/"
    session = requests.Session()
    for attempt in range(3):
        try:
            timeout = 10 if attempt == 0 else 30
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, list) and data:
                return data
            fetch_inventory_data.clear()
            return []
        except Exception:
            if attempt == 2:
                fetch_inventory_data.clear()
                return []
            time.sleep(1)
    fetch_inventory_data.clear()
    return []


@st.cache_data(ttl=120, show_spinner=False)
def fetch_inventory_df(base_url=DB_BASE_URL):
    """Returns pre-processed inventory DataFrame cached in memory."""
    inv = fetch_inventory_data(base_url)
    if not inv:
        fetch_inventory_df.clear()
        return pd.DataFrame()

    df = pd.DataFrame(inv)
    for col in ["stock_quantity", "low_stock_threshold"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0)
    return df


@st.cache_data(ttl=120, show_spinner=False)
def _fetch_base_revenue_summary(base_url=DB_BASE_URL):
    """Fetch base revenue summary dictionary from backend with memory caching."""
    url = f"{base_url}/revenue/summary"
    session = requests.Session()
    for attempt in range(3):
        try:
            timeout = 10 if attempt == 0 else 30
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            if isinstance(data, dict) and data:
                return data
            _fetch_base_revenue_summary.clear()
            return {}
        except Exception:
            if attempt == 2:
                _fetch_base_revenue_summary.clear()
                return {}
            time.sleep(1)
    _fetch_base_revenue_summary.clear()
    return {}


def fetch_revenue_summary(base_url=DB_BASE_URL):
    """
    Returns revenue summary including contributions from base sales data and custom appended CSV files.
    """
    base_rev = _fetch_base_revenue_summary(base_url).copy()
    try:
        sales_df = fetch_all_sales_df(base_url)
        if not sales_df.empty and "total_amount" in sales_df.columns:
            tot_rev = float(sales_df["total_amount"].sum())
            base_rev["total_revenue"] = f"{tot_rev:.2f}"
            return base_rev
    except Exception:
        pass

    uploaded_files = st.session_state.get("uploaded_sales_files", [])
    if uploaded_files:
        extra_rev = sum(float(f.get("total_amount", 0)) for f in uploaded_files)
        try:
            current_tot = float(base_rev.get("total_revenue", 0))
            base_rev["total_revenue"] = f"{current_tot + extra_rev:.2f}"
        except Exception:
            pass

    return base_rev


def add_appended_sales_file(file_name: str, df: pd.DataFrame, total_amount: float):
    """Register an uploaded sales CSV file into active session state."""
    import uuid
    from datetime import datetime
    
    if "uploaded_sales_files" not in st.session_state:
        st.session_state["uploaded_sales_files"] = []
        
    file_id = f"UPL-{str(uuid.uuid4())[:8].upper()}"
    record = {
        "file_id": file_id,
        "file_name": file_name,
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "row_count": len(df),
        "total_amount": float(total_amount),
        "df": df.copy()
    }
    st.session_state["uploaded_sales_files"].append(record)
    return record


def remove_appended_sales_file(file_id: str):
    """Remove an uploaded sales CSV file from active session state."""
    if "uploaded_sales_files" in st.session_state:
        st.session_state["uploaded_sales_files"] = [
            f for f in st.session_state["uploaded_sales_files"]
            if f.get("file_id") != file_id
        ]


def clear_sales_cache():
    """Clear cached sales, inventory, and revenue data."""
    fetch_all_sales.clear()
    _fetch_base_sales_df.clear()
    fetch_inventory_data.clear()
    fetch_inventory_df.clear()
    _fetch_base_revenue_summary.clear()
