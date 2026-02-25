class InputValidationError(Exception):
    """Raised when required inputs or config contracts are invalid."""


class CRSMismatchError(Exception):
    """Raised when CRS definitions are inconsistent across required files."""


class TerrainSamplingError(Exception):
    """Raised when terrain sampling fails or returns invalid coverage."""


class GeometryBuildError(Exception):
    """Raised when geometry assembly cannot satisfy core constraints."""


class HECRASRunMissingError(Exception):
    """Raised when expected HEC-RAS result artifacts are missing."""
