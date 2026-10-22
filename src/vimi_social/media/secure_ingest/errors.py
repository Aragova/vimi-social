class MediaIngestError(RuntimeError):
    """Base error for the secure media ingest boundary."""


class InvalidUrlError(MediaIngestError):
    pass


class UnsafeAddressError(MediaIngestError):
    pass


class RedirectPolicyError(MediaIngestError):
    pass


class DownloadLimitError(MediaIngestError):
    pass


class ContentValidationError(MediaIngestError):
    pass


class TransportError(MediaIngestError):
    pass


class ProcessLimitError(MediaIngestError):
    pass
