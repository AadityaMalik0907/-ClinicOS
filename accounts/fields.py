from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


class EncryptedFieldError(Exception):
    """Raised when encrypted database data cannot be authenticated or decoded."""


class EncryptedFieldMixin:
    prefix = "fernet:v1:"

    def _cipher(self):
        key = getattr(settings, "FIELD_ENCRYPTION_KEY", None)
        if not key:
            raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be configured to read encrypted fields.")
        if isinstance(key, str):
            key = key.encode("ascii")
        try:
            return Fernet(key)
        except (TypeError, ValueError) as exc:
            raise ImproperlyConfigured("FIELD_ENCRYPTION_KEY must be a valid Fernet key.") from exc

    def _encrypt_value(self, value):
        if value is None or value == "":
            return value
        value = str(value)
        token = self._cipher().encrypt(value.encode("utf-8")).decode("ascii")
        return f"{self.prefix}{token}"

    def _decrypt_value(self, value):
        if value is None or value == "" or not isinstance(value, str) or not value.startswith(self.prefix):
            return value
        try:
            return self._cipher().decrypt(value[len(self.prefix):].encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeDecodeError, ValueError) as exc:
            raise EncryptedFieldError(
                "Encrypted field data could not be authenticated. Check the field key and database contents."
            ) from exc

    def from_db_value(self, value, expression, connection):
        return self.to_python(value)

    def get_lookup(self, lookup_name):
        # Ciphertext uses a fresh nonce on every write, so equality and range
        # lookups against plaintext would be incorrect and unsafe.
        if lookup_name != "isnull":
            return None
        return super().get_lookup(lookup_name)


class EncryptedCharField(EncryptedFieldMixin, models.CharField):
    def db_type(self, connection):
        # Fernet tokens are longer than the plaintext max_length.
        return connection.data_types["TextField"]

    def get_internal_type(self):
        return "TextField"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self._encrypt_value(value)

    def to_python(self, value):
        return super().to_python(self._decrypt_value(value))


class EncryptedTextField(EncryptedFieldMixin, models.TextField):
    def db_type(self, connection):
        return connection.data_types["TextField"]

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self._encrypt_value(value)

    def to_python(self, value):
        return self._decrypt_value(value)


class EncryptedDateField(EncryptedFieldMixin, models.DateField):
    def db_type(self, connection):
        # Store authenticated ciphertext in text; expose a normal Python date.
        return connection.data_types["TextField"]

    def get_internal_type(self):
        # Prevent database backends from parsing ciphertext as a SQL DATE.
        return "TextField"

    def get_prep_value(self, value):
        value = super().get_prep_value(value)
        return self._encrypt_value(value)

    def get_db_prep_value(self, value, connection, prepared=False):
        # Avoid DateField backend adapters, which may coerce ciphertext back to DATE.
        if not prepared:
            value = self.get_prep_value(value)
        return value

    def to_python(self, value):
        return super().to_python(self._decrypt_value(value))
