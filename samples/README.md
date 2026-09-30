# samples/

`openmeteo/<product>.json`: one real Open-Meteo forecast response per product, every point of
every zone, trimmed to its first hours (`uv run python -m scripts.fetch_sample`). The offline
pipeline (`make ingest OFFLINE=1`) and the tests run on it.

Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed under
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
