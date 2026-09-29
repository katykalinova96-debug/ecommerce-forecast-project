import time
import requests


class HttpClient:
    def __init__(self, timeout=30, retry_attempts=3, backoff_factor=2):
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        self.backoff_factor = backoff_factor
        self.session = requests.Session()

    def get(self, url, params=None):
        last_error = None

        for attempt in range(1, self.retry_attempts + 1):
            try:
                response = self.session.get(
                    url,
                    params=params,
                    timeout=self.timeout
                )

                response.raise_for_status()
                return response

            except requests.RequestException as error:
                last_error = error

                if attempt < self.retry_attempts:
                    delay = self.backoff_factor ** (attempt - 1)
                    time.sleep(delay)

        raise RuntimeError(
            f"HTTP request failed after {self.retry_attempts} attempts: {last_error}"
        )


def get_json(url, params=None, retries=3, backoff=2, timeout=30):
    client = HttpClient(
        timeout=timeout,
        retry_attempts=retries,
        backoff_factor=backoff
    )
    response = client.get(url, params=params)
    return response.json()
