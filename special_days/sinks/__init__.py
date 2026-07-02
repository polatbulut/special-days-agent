"""Output sinks that persist the collected feed to external stores.

Renderers in :mod:`special_days.output` write files/stdout; sinks here write to
data stores. Currently: :mod:`special_days.sinks.lakehouse` (the THY lakehouse —
Parquet datasets on OBS under ``obs://lakehouse-dev/special_events`` that feed the
flight-occupancy forecasting models).
"""
