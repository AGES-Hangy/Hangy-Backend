import os

os.environ.setdefault("DATABASE_URL", "sqlite://")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key")
os.environ.setdefault("LOCATION_OBFUSCATION_SECRET", "test-location-secret")
