from __future__ import annotations

import io
import tarfile
from datetime import datetime, timedelta, timezone
from enum import Enum
from functools import lru_cache
from typing import BinaryIO, Callable, Generic, NamedTuple, Type, TypeVar

from cryptography.fernet import Fernet
from cryptography.hazmat.backends import default_backend
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from google.cloud.kms import KeyManagementServiceClient as KeyManagementServiceClient
from google_crc32c import value as crc32c

from sentry.backup.scopes import RelocationScope
from sentry.utils import json

# Django apps we take care to never import or export from.
EXCLUDED_APPS = frozenset(("auth", "contenttypes", "fixtures"))

UTC_0 = timezone(timedelta(hours=0))


class DatetimeSafeDjangoJSONEncoder(DjangoJSONEncoder):
    """A wrapper around the default `DjangoJSONEncoder` that always retains milliseconds, even when
    their implicit value is `.000`. This is necessary because the ECMA-262 compatible
    `DjangoJSONEncoder` drops these by default."""

    def default(self, obj):
        if isinstance(obj, datetime):
            return obj.astimezone(UTC_0).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        return super().default(obj)


def create_encrypted_export_tarball(
    json_export: json.JSONData, encrypt_with: BinaryIO
) -> io.BytesIO:
    """
    Generate a tarball with 3 files:

      1. The DEK we minted, name "data.key".
      2. The public key we used to encrypt that DEK, named "key.pub".
      3. The exported JSON data, encrypted with that DEK, named "export.json".

    The upshot: to decrypt the exported JSON data, you need the plaintext (decrypted) DEK. But to
    decrypt the DEK, you need the private key associated with the included public key, which
    you've hopefully kept in a safe, trusted location.

    Note that the supplied file names are load-bearing - ex, changing to `data.key` to `foo.key`
    risks breaking assumptions that the decryption side will make on the other end!
    """

    # Generate a new DEK (data encryption key), and use that DEK to encrypt the JSON being exported.
    pem = encrypt_with.read()
    data_encryption_key = Fernet.generate_key()
    backup_encryptor = Fernet(data_encryption_key)
    encrypted_json_export = backup_encryptor.encrypt(json.dumps(json_export).encode("utf-8"))

    # Encrypt the newly minted DEK using asymmetric public key encryption.
    dek_encryption_key = serialization.load_pem_public_key(pem, default_backend())
    sha256 = hashes.SHA256()
    mgf = padding.MGF1(algorithm=sha256)
    oaep_padding = padding.OAEP(mgf=mgf, algorithm=sha256, label=None)
    encrypted_dek = dek_encryption_key.encrypt(data_encryption_key, oaep_padding)  # type: ignore

    # Generate the tarball and write it to to a new output stream.
    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w") as tar:
        json_info = tarfile.TarInfo("export.json")
        json_info.size = len(encrypted_json_export)
        tar.addfile(json_info, fileobj=io.BytesIO(encrypted_json_export))
        key_info = tarfile.TarInfo("data.key")
        key_info.size = len(encrypted_dek)
        tar.addfile(key_info, fileobj=io.BytesIO(encrypted_dek))
        pub_info = tarfile.TarInfo("key.pub")
        pub_info.size = len(pem)
        tar.addfile(pub_info, fileobj=io.BytesIO(pem))

    return tar_buffer


class UnwrappedEncryptedExportTarball(NamedTuple):
    """
    A tarball generated by an encrypted export request contains three elements:

      1. The DEK we minted, name "data.key".
      2. The public key we used to encrypt that DEK, named "key.pub".
      3. The exported JSON data, encrypted with that DEK, named "export.json".

    This class tracks them as separate objects.
    """

    plain_public_key_pem: bytes
    encrypted_data_encryption_key: bytes
    encrypted_json_blob: str


def unwrap_encrypted_export_tarball(tarball: BinaryIO) -> UnwrappedEncryptedExportTarball:
    export = None
    encrypted_dek = None
    public_key_pem = None
    with tarfile.open(fileobj=tarball, mode="r") as tar:
        for member in tar.getmembers():
            if member.isfile():
                file = tar.extractfile(member)
                if file is None:
                    raise ValueError(f"Could not extract file for {member.name}")

                content = file.read()
                if member.name == "export.json":
                    export = content.decode("utf-8")
                elif member.name == "data.key":
                    encrypted_dek = content
                elif member.name == "key.pub":
                    public_key_pem = content
                else:
                    raise ValueError(f"Unknown tarball entity {member.name}")

    if export is None or encrypted_dek is None or public_key_pem is None:
        raise ValueError("A required file was missing from the temporary test tarball")

    return UnwrappedEncryptedExportTarball(
        plain_public_key_pem=public_key_pem,
        encrypted_data_encryption_key=encrypted_dek,
        encrypted_json_blob=export,
    )


def decrypt_data_encryption_key_local(
    unwrapped: UnwrappedEncryptedExportTarball, private_key_pem: bytes
) -> bytes:
    """
    Decrypt the encrypted data encryption key used to encrypt the actual export JSON.
    """

    # Compare the public and private key, to ensure that they are a match.
    private_key = serialization.load_pem_private_key(
        private_key_pem,
        password=None,
        backend=default_backend(),
    )
    generated_public_key_pem = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    if unwrapped.plain_public_key_pem != generated_public_key_pem:
        raise ValueError(
            "The public key does not match that generated by the `decrypt_with` private key."
        )

    private_key = serialization.load_pem_private_key(
        private_key_pem,
        password=None,
        backend=default_backend(),
    )
    return private_key.decrypt(  # type: ignore
        unwrapped.encrypted_data_encryption_key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


class CryptoKeyVersion(NamedTuple):
    """
    A structured version of a Google Cloud KMS CryptoKeyVersion, as described here:
    https://cloud.google.com/kms/docs/resource-hierarchy#retrieve_resource_id
    """

    project_id: str
    location: str
    key_ring: str
    key: str
    version: str


class KMSDecryptionError(Exception):
    pass


def decrypt_data_encryption_key_using_gcp_kms(
    unwrapped: UnwrappedEncryptedExportTarball, gcp_kms_config: bytes
) -> bytes:
    # Read the user supplied configuration into the proper format.
    json_gcp_kms_config = json.loads(gcp_kms_config)
    try:
        crypto_key_version = CryptoKeyVersion(**json_gcp_kms_config)
    except TypeError:
        raise KMSDecryptionError(
            """Your supplied KMS configuration did not have the correct fields - please ensure that
            it is a single, top-level object with the fields `project_id`, `location`, `key_rind`,
            `key`, and `version`, with all values as strings."""
        )

    kms_client = KeyManagementServiceClient()
    key_name = kms_client.crypto_key_version_path(
        project=crypto_key_version.project_id,
        location=crypto_key_version.location,
        key_ring=crypto_key_version.key_ring,
        crypto_key=crypto_key_version.key,
        crypto_key_version=crypto_key_version.version,
    )
    ciphertext = unwrapped.encrypted_data_encryption_key
    dek_crc32c = crc32c(ciphertext)
    decrypt_response = kms_client.asymmetric_decrypt(
        request={
            "name": key_name,
            "ciphertext": ciphertext,
            "ciphertext_crc32c": dek_crc32c,
        }
    )
    if not decrypt_response.plaintext_crc32c == crc32c(decrypt_response.plaintext):
        raise Exception("The response received from the server was corrupted in-transit.")

    return decrypt_response.plaintext


def decrypt_encrypted_tarball(
    tarball: BinaryIO, decryption_using_gcp_kms: bool, decrypt_with: BinaryIO
) -> str:
    """
    A tarball encrypted by a call to `_export` with `encrypt_with` set has some specific properties
    (filenames, etc). This method handles all of those, and decrypts using the provided private key
    into an in-memory JSON string.
    """

    unwrapped = unwrap_encrypted_export_tarball(tarball)
    decryption_info = decrypt_with.read()

    # Decrypt the DEK, then use it to decrypt the underlying JSON.
    decryption_handler: Callable[[UnwrappedEncryptedExportTarball, bytes], bytes] = (
        decrypt_data_encryption_key_using_gcp_kms
        if decryption_using_gcp_kms
        else decrypt_data_encryption_key_local
    )
    decrypted_dek = decryption_handler(unwrapped, decryption_info)
    decryptor = Fernet(decrypted_dek)
    return decryptor.decrypt(unwrapped.encrypted_json_blob).decode("utf-8")


def get_final_derivations_of(model: Type) -> set[Type]:
    """A "final" derivation of the given `model` base class is any non-abstract class for the
    "sentry" app with `BaseModel` as an ancestor. Top-level calls to this class should pass in
    `BaseModel` as the argument."""

    out = set()
    for sub in model.__subclasses__():
        subs = sub.__subclasses__()
        if subs:
            out.update(get_final_derivations_of(sub))
        if not sub._meta.abstract and sub._meta.db_table and sub._meta.app_label == "sentry":
            out.add(sub)
    return out


# No arguments, so we lazily cache the result after the first calculation.
@lru_cache(maxsize=1)
def get_exportable_sentry_models() -> set[Type]:
    """Like `get_final_derivations_of`, except that it further filters the results to include only
    `__relocation_scope__ != RelocationScope.Excluded`."""

    from sentry.db.models import BaseModel

    return set(
        filter(
            lambda c: getattr(c, "__relocation_scope__") is not RelocationScope.Excluded,
            get_final_derivations_of(BaseModel),
        )
    )


class Side(Enum):
    left = 1
    right = 2


T = TypeVar("T")


class Filter(Generic[T]):
    """Specifies a field-based filter when performing an import or export operation. This is an
    allowlist based filtration: models of the given type whose specified field matches ANY of the
    supplied values will be allowed through."""

    model: Type[models.base.Model]
    field: str
    values: set[T]

    def __init__(self, model: Type[models.base.Model], field: str, values: set[T] | None = None):
        self.model = model
        self.field = field
        self.values = values if values is not None else set()


class ImportFlags(NamedTuple):
    """
    Flags that affect how importing a relocation JSON file proceeds.
    """

    # If a username already exists, should we re-use that user, or create a new one with a randomly
    # suffixed username (ex: "some-user" would become "some-user-ad21")
    merge_users: bool = False

    # If a global configuration value `ControlOption`/`Option` (as identified by its unique
    # `key`) or `Relay` (as identified by its unique `relay_id`) already exists, should we overwrite
    # it with the new value, or keep the existing one and discard the incoming value instead?
    overwrite_configs: bool = False

    # How do we decrypt this import?
    decrypt_using_gcp_kms: bool = False
