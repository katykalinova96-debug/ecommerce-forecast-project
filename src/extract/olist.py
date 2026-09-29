from pathlib import Path
import json
import pandas as pd

from src.db import (
    create_connection,
    generate_run_id,
    start_load,
    finish_load,
    get_watermark,
    set_watermark,
    save_dq_result,
    save_rejected_row,
    insert_rows,
)


ORDERS_COLUMNS = [
    "order_id",
    "customer_id",
    "order_status",
    "order_purchase_timestamp",
    "order_approved_at",
    "order_delivered_carrier_date",
    "order_delivered_customer_date",
    "order_estimated_delivery_date",
]

ORDER_ITEMS_COLUMNS = [
    "order_id",
    "order_item_id",
    "product_id",
    "seller_id",
    "shipping_limit_date",
    "price",
    "freight_value",
]

PRODUCTS_COLUMNS = [
    "product_id",
    "product_category_name",
    "product_name_lenght",
    "product_description_lenght",
    "product_photos_qty",
    "product_weight_g",
    "product_length_cm",
    "product_height_cm",
    "product_width_cm",
]

TRANSLATION_COLUMNS = [
    "product_category_name",
    "product_category_name_english",
]


def load_csv(path, required_columns):
    df = pd.read_csv(path)

    missing = [
        column
        for column in required_columns
        if column not in df.columns
    ]

    if missing:
        raise ValueError(
            f"В файле {path} отсутствуют столбцы: {missing}"
        )

    return df[required_columns]


def save_rejected_dataframe(
    connection,
    run_id,
    source,
    dataframe,
    reason
):
    for _, row in dataframe.iterrows():
        save_rejected_row(
            connection,
            run_id,
            source,
            reason,
            json.dumps(
                row.to_dict(),
                ensure_ascii=False,
                default=str
            )
        )


def process_orders(connection, path):
    source = "olist_orders"
    run_id = generate_run_id(source)
    start_load(connection, run_id, source)

    try:
        df = load_csv(path, ORDERS_COLUMNS)

        total_rows = len(df)

        invalid_key = df["order_id"].isna()
        invalid_date = pd.to_datetime(
            df["order_purchase_timestamp"],
            errors="coerce"
        ).isna()

        rejected = invalid_key | invalid_date

        save_dq_result(
            connection,
            run_id,
            source,
            "order_id_not_null",
            "passed" if not invalid_key.any() else "failed",
            total_rows,
            int(invalid_key.sum()),
            "Проверка обязательного ключа order_id"
        )

        save_dq_result(
            connection,
            run_id,
            source,
            "purchase_timestamp_valid",
            "passed" if not invalid_date.any() else "failed",
            total_rows,
            int(invalid_date.sum()),
            "Проверка даты покупки"
        )

        if rejected.any():
            save_rejected_dataframe(
                connection,
                run_id,
                source,
                df[rejected],
                "Некорректный order_id или order_purchase_timestamp"
            )

        df = df[~rejected].copy()

        df["order_purchase_timestamp"] = pd.to_datetime(
            df["order_purchase_timestamp"]
        ).dt.strftime("%Y-%m-%d %H:%M:%S")

        watermark = get_watermark(connection, source)

        if watermark:
            df = df[
                df["order_purchase_timestamp"] > watermark
            ]

        rows = [
            tuple(row)
            for row in df.itertuples(index=False, name=None)
        ]

        insert_rows(
            connection,
            "raw_orders",
            ORDERS_COLUMNS + ["run_id", "loaded_at"],
            [
                row + (run_id, pd.Timestamp.utcnow().isoformat())
                for row in rows
            ]
        )

        if not df.empty:
            new_watermark = df["order_purchase_timestamp"].max()
            set_watermark(
                connection,
                source,
                new_watermark
            )

        finish_load(
            connection,
            run_id,
            "success",
            len(rows),
            int(rejected.sum())
        )

        return len(rows)

    except Exception as error:
        finish_load(
            connection,
            run_id,
            "failed",
            error_message=str(error)
        )
        raise


def process_order_items(connection, path):
    source = "olist_order_items"
    run_id = generate_run_id(source)
    start_load(connection, run_id, source)

    try:
        df = load_csv(path, ORDER_ITEMS_COLUMNS)

        total_rows = len(df)

        invalid_key = (
            df["order_id"].isna()
            | df["order_item_id"].isna()
        )

        invalid_price = (
            pd.to_numeric(df["price"], errors="coerce").isna()
            | (pd.to_numeric(df["price"], errors="coerce") < 0)
        )

        invalid_freight = (
            pd.to_numeric(
                df["freight_value"],
                errors="coerce"
            ).isna()
            | (pd.to_numeric(
                df["freight_value"],
                errors="coerce"
            ) < 0)
        )

        rejected = invalid_key | invalid_price | invalid_freight

        save_dq_result(
            connection,
            run_id,
            source,
            "order_item_key_valid",
            "passed" if not invalid_key.any() else "failed",
            total_rows,
            int(invalid_key.sum()),
            "Проверка order_id и order_item_id"
        )

        save_dq_result(
            connection,
            run_id,
            source,
            "price_non_negative",
            "passed" if not invalid_price.any() else "failed",
            total_rows,
            int(invalid_price.sum()),
            "Цена должна быть неотрицательной"
        )

        save_dq_result(
            connection,
            run_id,
            source,
            "freight_non_negative",
            "passed" if not invalid_freight.any() else "failed",
            total_rows,
            int(invalid_freight.sum()),
            "Стоимость доставки должна быть неотрицательной"
        )

        if rejected.any():
            save_rejected_dataframe(
                connection,
                run_id,
                source,
                df[rejected],
                "Некорректные ключи, цена или стоимость доставки"
            )

        df = df[~rejected].copy()

        df["order_item_id"] = pd.to_numeric(
            df["order_item_id"]
        ).astype(int)

        df["price"] = pd.to_numeric(df["price"])
        df["freight_value"] = pd.to_numeric(
            df["freight_value"]
        )

        df["shipping_limit_date"] = pd.to_datetime(
            df["shipping_limit_date"],
            errors="coerce"
        ).dt.strftime("%Y-%m-%d %H:%M:%S")

        rows = [
            tuple(row)
            for row in df.itertuples(index=False, name=None)
        ]

        insert_rows(
            connection,
            "raw_order_items",
            ORDER_ITEMS_COLUMNS + ["run_id", "loaded_at"],
            [
                row + (run_id, pd.Timestamp.utcnow().isoformat())
                for row in rows
            ]
        )

        finish_load(
            connection,
            run_id,
            "success",
            len(rows),
            int(rejected.sum())
        )

        return len(rows)

    except Exception as error:
        finish_load(
            connection,
            run_id,
            "failed",
            error_message=str(error)
        )
        raise


def process_products(connection, path):
    source = "olist_products"
    run_id = generate_run_id(source)
    start_load(connection, run_id, source)

    try:
        df = load_csv(path, PRODUCTS_COLUMNS)

        total_rows = len(df)

        invalid_key = df["product_id"].isna()

        save_dq_result(
            connection,
            run_id,
            source,
            "product_id_not_null",
            "passed" if not invalid_key.any() else "failed",
            total_rows,
            int(invalid_key.sum()),
            "Проверка product_id"
        )

        if invalid_key.any():
            save_rejected_dataframe(
                connection,
                run_id,
                source,
                df[invalid_key],
                "Пустой product_id"
            )

        df = df[~invalid_key].copy()

        rows = [
            tuple(row)
            for row in df.itertuples(index=False, name=None)
        ]

        insert_rows(
            connection,
            "raw_products",
            PRODUCTS_COLUMNS + ["run_id", "loaded_at"],
            [
                row + (run_id, pd.Timestamp.utcnow().isoformat())
                for row in rows
            ]
        )

        finish_load(
            connection,
            run_id,
            "success",
            len(rows),
            int(invalid_key.sum())
        )

        return len(rows)

    except Exception as error:
        finish_load(
            connection,
            run_id,
            "failed",
            error_message=str(error)
        )
        raise


def process_translation(connection, path):
    source = "olist_category_translation"
    run_id = generate_run_id(source)
    start_load(connection, run_id, source)

    try:
        df = load_csv(path, TRANSLATION_COLUMNS)

        total_rows = len(df)

        invalid_key = df["product_category_name"].isna()

        save_dq_result(
            connection,
            run_id,
            source,
            "category_name_not_null",
            "passed" if not invalid_key.any() else "failed",
            total_rows,
            int(invalid_key.sum()),
            "Проверка названия категории"
        )

        if invalid_key.any():
            save_rejected_dataframe(
                connection,
                run_id,
                source,
                df[invalid_key],
                "Пустое название категории"
            )

        df = df[~invalid_key].copy()

        rows = [
            tuple(row)
            for row in df.itertuples(index=False, name=None)
        ]

        insert_rows(
            connection,
            "raw_product_category_translation",
            TRANSLATION_COLUMNS + ["run_id", "loaded_at"],
            [
                row + (run_id, pd.Timestamp.utcnow().isoformat())
                for row in rows
            ]
        )

        finish_load(
            connection,
            run_id,
            "success",
            len(rows),
            int(invalid_key.sum())
        )

        return len(rows)

    except Exception as error:
        finish_load(
            connection,
            run_id,
            "failed",
            error_message=str(error)
        )
        raise


def load_olist(source_dir="data/source/olist"):
    source_dir = Path(source_dir)

    files = {
        "orders": source_dir / "olist_orders_dataset.csv",
        "order_items": source_dir / "olist_order_items_dataset.csv",
        "products": source_dir / "olist_products_dataset.csv",
        "translation": source_dir / "product_category_name_translation.csv",
    }

    missing_files = [
        str(path)
        for path in files.values()
        if not path.exists()
    ]

    if missing_files:
        raise FileNotFoundError(
            "Не найдены файлы Olist:\n"
            + "\n".join(missing_files)
        )

    connection = create_connection()

    try:
        results = {
            "orders": process_orders(
                connection,
                files["orders"]
            ),
            "order_items": process_order_items(
                connection,
                files["order_items"]
            ),
            "products": process_products(
                connection,
                files["products"]
            ),
            "translation": process_translation(
                connection,
                files["translation"]
            ),
        }

        return results

    finally:
        connection.close()


if __name__ == "__main__":
    print(load_olist())