from datetime import date, timedelta
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
from src.net import get_json


URL = "https://archive-api.open-meteo.com/v1/archive"
CITIES = [
    {"name": "sao_paulo", "latitude": -23.55, "longitude": -46.63},
    {"name": "rio_de_janeiro", "latitude": -22.91, "longitude": -43.17},
]


def load_weather():
    source = "open_meteo"
    run_id = generate_run_id(source)
    connection = create_connection()
    start_load(connection, run_id, source)

    try:
        watermark = get_watermark(connection, source)
        start_date = watermark or "2016-09-01"
        end_date = str(date.today() - timedelta(days=1))

        if start_date > end_date:
            finish_load(connection, run_id, "success", 0, 0)
            connection.close()
            return {"weather": 0}

        rows = []
        for city in CITIES:
            data = get_json(
                URL,
                params={
                    "latitude": city["latitude"],
                    "longitude": city["longitude"],
                    "start_date": start_date,
                    "end_date": end_date,
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum",
                    "timezone": "auto",
                },
            )
            daily = data["daily"]
            for t, tmax, tmin, pr in zip(
                daily["time"],
                daily["temperature_2m_max"],
                daily["temperature_2m_min"],
                daily["precipitation_sum"],
            ):
                temp_mean = (tmax + tmin) / 2 if tmax is not None and tmin is not None else None
                rows.append((
                    city["name"],
                    t,
                    temp_mean,
                    pr,
                    run_id,
                    pd.Timestamp.utcnow().isoformat(),
                ))

        df = pd.DataFrame(
            rows,
            columns=["city", "weather_date", "temperature_mean", "precipitation_sum", "run_id", "loaded_at"],
        )

        invalid = df[["temperature_mean", "precipitation_sum"]].isna().any(axis=1)
        save_dq_result(
            connection,
            run_id,
            source,
            "weather_metrics_not_null",
            "passed" if not invalid.any() else "failed",
            len(df),
            int(invalid.sum()),
            "Проверка метрик погоды",
        )

        if invalid.any():
            for _, row in df[invalid].iterrows():
                save_rejected_row(connection, run_id, source, "Null weather metrics", str(row.to_dict()))

        df = df[~invalid]

        insert_rows(
            connection,
            "raw_weather",
            ["city", "weather_date", "temperature_mean", "precipitation_sum", "run_id", "loaded_at"],
            [tuple(row) for row in df.itertuples(index=False, name=None)],
        )

        if not df.empty:
            set_watermark(connection, source, df["weather_date"].max())

        finish_load(connection, run_id, "success", len(df), int(invalid.sum()))
        connection.close()
        return {"weather": len(df)}

    except Exception as error:
        finish_load(connection, run_id, "failed", error_message=str(error))
        connection.close()
        raise


if __name__ == "__main__":
    print(load_weather())
