from src.extract.olist import load_olist
from src.extract.weather import load_weather
from src.extract.holidays import load_holidays


def main():
    print("=== Загрузка Olist ===")
    try:
        result = load_olist()
        print(f"Olist: {result}")
    except Exception as e:
        print(f"Olist FAILED: {e}")

    print("")
    print("=== Загрузка погоды ===")
    try:
        result = load_weather()
        print(f"Weather: {result}")
    except Exception as e:
        print(f"Weather FAILED: {e}")

    print("")
    print("=== Загрузка праздников ===")
    try:
        result = load_holidays()
        print(f"Holidays: {result}")
    except Exception as e:
        print(f"Holidays FAILED: {e}")


if __name__ == "__main__":
    main()
