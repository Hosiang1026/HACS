from __future__ import annotations


class HonorCloudError(Exception):
    pass


class ConfigError(HonorCloudError):
    pass


class AuthError(ConfigError):
    pass


class TemporaryError(HonorCloudError):
    pass


class EmptyDataError(TemporaryError):
    pass

