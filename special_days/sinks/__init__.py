"""Output sinks that persist the collected feed to external stores.

Renderers in :mod:`special_days.output` write files/stdout; sinks here write to
data stores. Currently: :mod:`special_days.sinks.lakehouse` (the THY Spark
lakehouse — Hive/Parquet tables under ``/lakehouse/special_events`` that feed the
flight-occupancy forecasting models).
"""
