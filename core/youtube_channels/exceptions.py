class YouTubeChannelError(Exception):
    """Base error for connected-channel operations."""


class YouTubeConfigurationError(YouTubeChannelError):
    pass


class YouTubeAuthorizationError(YouTubeChannelError):
    pass


class YouTubeAPIError(YouTubeChannelError):
    pass
