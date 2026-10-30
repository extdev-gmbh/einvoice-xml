from hypothesis import HealthCheck, settings

# No example database: the checkout may be read-only, and a run must not leave anything behind.
settings.register_profile(
    "gate", database=None, deadline=None, max_examples=200, suppress_health_check=[HealthCheck.too_slow]
)
settings.load_profile("gate")
