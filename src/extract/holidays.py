from datetime import date
import pandas as pd

from src.db import (
    create_connection,
    generate_run_id,
    start_load,
    finish_load,
    set_watermark,
    save_dq_result,
    insert_rows,
)
from src.net import get_json


def load_holidays():
    source = "holidays"
    run_id = generate_run_id(source)
    connection = create_connection()
    start_load(connection, run_id, source)

    try:
        years = list(range(2016, date.today().year + 1))
        rows = []

        for year in years:
            data = get_json(
                f"https://date.nager.at/api/v3/PublicHolidays/{year}/BR",
            )
            for h in data:
                rows.append((
                    h.get("countryCode", "BR"),
                    h["date"],
                    h["name"],
                    run_id,
                    pd.Timestamp.utcnow().isoformat(),
                ))

        df = pd.DataFrame(
            rows,
            columns=["country_code", "holiday_date", "holiday_name", "run_id", "loaded_at"],
        )

        invalid = pd.to_datetime(df["holiday_date"], errors="coerce").isna()
        save_dq_result(
            connection,
            run_id,
            source,
            "holiday_date_valid",
            "passed" if not invalid.any() else "failed",
            len(df),
            int(invalid.sum()),
            "Проверка дат праздников",
        )

        df = df[~invalid].drop_duplicates(subset=["country_code", "holiday_date", "holiday_name"])

        insert_rows(
            connection,
            "raw_holidays",
            ["country_code", "holiday_date", "holiday_name", "run_id", "loaded_at"],
            [tuple(row) for row in df.itertuples(index=False, name=None)],
        )

        set_watermark(connection, source, str(max(years)))
        finish_load(connection, run_id, "success", len(df), 0)
        connection.close()
        return {"holidays": len(df)}

    except Exception as error:
        finish_load(connection, run_id, "failed", error_message=str(error))
        connection.close()
        raise


if __name__ == "__main__":
    print(load_holidays())
