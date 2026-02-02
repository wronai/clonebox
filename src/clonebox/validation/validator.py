from clonebox.validation.apps import AppValidationMixin
from clonebox.validation.core import VMValidatorCore
from clonebox.validation.disk import DiskValidationMixin
from clonebox.validation.mounts import MountValidationMixin
from clonebox.validation.overall import OverallValidationMixin
from clonebox.validation.packages import PackageValidationMixin
from clonebox.validation.services import ServiceValidationMixin
from clonebox.validation.smoke import SmokeValidationMixin


class VMValidator(
    VMValidatorCore,
    MountValidationMixin,
    PackageValidationMixin,
    ServiceValidationMixin,
    AppValidationMixin,
    SmokeValidationMixin,
    DiskValidationMixin,
    OverallValidationMixin,
):
    pass


__all__ = ["VMValidator"]
