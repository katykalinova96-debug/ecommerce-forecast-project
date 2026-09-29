from pathlib import Path
import sqlite3
from datetime import datetime, timezone


DB_PATH = Path("data/warehouse.db")


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def create_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db():
    connection = create_connection()

    connection.executescript("""
    CREATE TABLE IF NOT EXISTS raw_orders (
        order_id TEXT PRIMARY KEY,
        customer_id TEXT,
        order_status TEXT,
        order_purchase_timestamp TEXT,
        order_approved_at TEXT,
        order_delivered_carrier_date TEXT,
        order_delivered_customer_date TEXT,
        order_estimated_delivery_date TEXT,
        run_id TEXT NOT NULL,
        loaded_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS raw_order_items (
        order_id TEXT NOT NULL,
        order_item_id INTEGER NOT NULL,
        product_id TEXT,
        seller_id TEXT,
        shipping_limit_date TEXT,
        price REAL,
        freight_value REAL,
        run_id TEXT NOT NULL,
        loaded_at TEXT NOT NULL,
        PRIMARY KEY (order_id, order_item_id)
    );

    CREATE TABLE IF NOT EXISTS raw_products (
        product_id TEXT PRIMARY KEY,
        product_category_name TEXT,
        product_name_lenght INTEGER,
        product_description_lenght INTEGER,
        product_photos_qty INTEGER,
        product_weight_g REAL,
        product_length_cm REAL,
        product_height_cm REAL,
        product_width_cm REAL,
        run_id TEXT NOT NULL,
        loaded_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS raw_product_category_translation (
        product_category_name TEXT PRIMARY KEY,
        product_category_name_english TEXT,
        run_id TEXT NOT NULL,
        loaded_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS raw_weather (
        city TEXT NOT NULL,
        weather_date TEXT NOT NULL,
        temperature_mean REAL,
        precipitation_sum REAL,
        run_id TEXT NOT NULL,
        loaded_at TEXT NOT NULL,
        PRIMARY KEY (city, weather_date)
    );

    CREATE TABLE IF NOT EXISTS raw_holidays (
        country_code TEXT NOT NULL,
        holiday_date TEXT NOT NULL,
        holiday_name TEXT NOT NULL,
        run_id TEXT NOT NULL,
        loaded_at TEXT NOT NULL,
        PRIMARY KEY (country_code, holiday_date, holiday_name)
    );

    CREATE TABLE IF NOT EXISTS load_log (
        run_id TEXT PRIMARY KEY,
        source TEXT NOT NULL,
        started_at TEXT NOT NULL,
        finished_at TEXT,
        status TEXT NOT NULL,
        rows_loaded INTEGER DEFAULT 0,
        rows_rejected INTEGER DEFAULT 0,
        error_message TEXT
    );

    CREATE TABLE IF NOT EXISTS load_state (
        source TEXT PRIMARY KEY,
        watermark TEXT,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS dq_results (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        source TEXT NOT NULL,
        check_name TEXT NOT NULL,
        status TEXT NOT NULL,
        checked_rows INTEGER DEFAULT 0,
        failed_rows INTEGER DEFAULT 0,
        details TEXT,
        checked_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS rejected_rows (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT NOT NULL,
        source TEXT NOT NULL,
        reason TEXT NOT NULL,
        row_data TEXT,
        rejected_at TEXT NOT NULL
    );

    CREATE TABLE IF NOT EXISTS mart_weekly_demand (
        week_start TEXT NOT NULL,
        category TEXT NOT NULL,
        order_quantity INTEGER NOT NULL,
        order_count INTEGER NOT NULL,
        sales_value REAL NOT NULL,
        temperature_mean REAL,
        precipitation_sum REAL,
        is_holiday INTEGER DEFAULT 0,
        holiday_name TEXT,
        days_to_holiday INTEGER,
        is_black_friday INTEGER DEFAULT 0,
        is_mothers_day INTEGER DEFAULT 0,
        is_fathers_day INTEGER DEFAULT 0,
        week_of_year INTEGER,
        month INTEGER,
        quarter INTEGER,
        season TEXT,
        PRIMARY KEY (week_start, category)
    );
    """)

    connection.commit()
    connection.close()

    print(f"Database initialized: {DB_PATH}")


def generate_run_id(source):
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"{source}_{timestamp}"


def start_load(connection, run_id, source):
    connection.execute(
        """
        INSERT INTO load_log (
            run_id,
            source,
            started_at,
            status
        )
        VALUES (?, ?, ?, ?)
        """,
        (run_id, source, utc_now(), "running")
    )
    connection.commit()


def finish_load(
    connection,
    run_id,
    status,
    rows_loaded=0,
    rows_rejected=0,
    error_message=None
):
    connection.execute(
        """
        UPDATE load_log
        SET
            finished_at = ?,
            status = ?,
            rows_loaded = ?,
            rows_rejected = ?,
            error_message = ?
        WHERE run_id = ?
        """,
        (
            utc_now(),
            status,
            rows_loaded,
            rows_rejected,
            error_message,
            run_id
        )
    )
    connection.commit()


def get_watermark(connection, source):
    result = connection.execute(
        """
        SELECT watermark
        FROM load_state
        WHERE source = ?
        """,
        (source,)
    ).fetchone()

    return result[0] if result else None


def set_watermark(connection, source, watermark):
    connection.execute(
        """
        INSERT INTO load_state (
            source,
            watermark,
            updated_at
        )
        VALUES (?, ?, ?)
        ON CONFLICT(source)
        DO UPDATE SET
            watermark = excluded.watermark,
            updated_at = excluded.updated_at
        """,
        (source, watermark, utc_now())
    )
    connection.commit()


def save_dq_result(
    connection,
    run_id,
    source,
    check_name,
    status,
    checked_rows,
    failed_rows,
    details=""
):
    connection.execute(
        """
        INSERT INTO dq_results (
            run_id,
            source,
            check_name,
            status,
            checked_rows,
            failed_rows,
            details,
            checked_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            run_id,
            source,
            check_name,
            status,
            checked_rows,
            failed_rows,
            details,
            utc_now()
        )
    )
    connection.commit()


def save_rejected_row(connection, run_id, source, reason, row_data):
    connection.execute(
        """
        INSERT INTO rejected_rows (
            run_id,
            source,
            reason,
            row_data,
            rejected_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            run_id,
            source,
            reason,
            row_data,
            utc_now()
        )
    )
    connection.commit()


def insert_rows(connection, table_name, columns, rows):
    placeholders = ", ".join(["?"] * len(columns))
    column_names = ", ".join(columns)

    query = f"""
        INSERT OR IGNORE INTO {table_name}
        ({column_names})
        VALUES ({placeholders})
    """

    connection.executemany(query, rows)
    connection.commit()


if __name__ == "__main__":
    init_db()