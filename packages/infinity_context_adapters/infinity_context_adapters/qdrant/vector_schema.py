"""Qdrant vector schema inspection kept separate from runtime orchestration."""

from ipaddress import ip_address
from urllib.parse import urlsplit


class QdrantDimensionMismatchError(RuntimeError):
    pass


class QdrantDistanceMismatchError(RuntimeError):
    pass


class QdrantHybridSchemaMismatchError(RuntimeError):
    pass


class QdrantHybridUnsupportedError(RuntimeError):
    pass


class QdrantSparseEncodingError(RuntimeError):
    pass


def vector_size_from_collection(
    collection: object | None,
    *,
    vector_name: str | None = None,
) -> int | None:
    if collection is None:
        return None
    config = getattr(collection, "config", None)
    params = getattr(config, "params", None)
    vectors = getattr(params, "vectors", None)
    return _vector_size_from_vectors(vectors, vector_name=vector_name)


def is_loopback_url(url: str) -> bool:
    host = urlsplit(url).hostname
    if host == "localhost":
        return True
    if host is None:
        return False
    try:
        return ip_address(host).is_loopback
    except ValueError:
        return False


def _vector_size_from_vectors(vectors: object, *, vector_name: str | None = None) -> int | None:
    if vectors is None:
        return None
    if vector_name is not None:
        named_vectors = mapping_from_object(vectors)
        if named_vectors is None or vector_name not in named_vectors:
            return None
        return _vector_size_from_vectors(named_vectors[vector_name])
    size = getattr(vectors, "size", None)
    if isinstance(size, int):
        return size
    kwargs = getattr(vectors, "kwargs", None)
    if isinstance(kwargs, dict) and isinstance(kwargs.get("size"), int):
        return int(kwargs["size"])
    if isinstance(vectors, dict):
        for value in vectors.values():
            nested_size = _vector_size_from_vectors(value)
            if nested_size is not None:
                return nested_size
    return None


def vector_distance_from_collection(
    collection: object | None,
    *,
    vector_name: str | None = None,
) -> str | None:
    if collection is None:
        return None
    config = getattr(collection, "config", None)
    params = getattr(config, "params", None)
    vectors = getattr(params, "vectors", None)
    return _vector_distance_from_vectors(vectors, vector_name=vector_name)


def _vector_distance_from_vectors(
    vectors: object,
    *,
    vector_name: str | None = None,
) -> str | None:
    if vectors is None:
        return None
    if vector_name is not None:
        named_vectors = mapping_from_object(vectors)
        if named_vectors is None or vector_name not in named_vectors:
            return None
        return _vector_distance_from_vectors(named_vectors[vector_name])
    distance = getattr(vectors, "distance", None)
    if distance is None:
        kwargs = getattr(vectors, "kwargs", None)
        if isinstance(kwargs, dict):
            distance = kwargs.get("distance")
    if distance is None:
        return None
    value = getattr(distance, "value", distance)
    return str(value).split(".")[-1].lower()


def sparse_vector_exists(collection: object, vector_name: str) -> bool:
    config = getattr(collection, "config", None)
    params = getattr(config, "params", None)
    sparse_vectors = getattr(params, "sparse_vectors", None)
    sparse_mapping = mapping_from_object(sparse_vectors)
    return sparse_mapping is not None and vector_name in sparse_mapping


def mapping_from_object(value: object) -> dict[str, object] | None:
    if isinstance(value, dict):
        return value
    kwargs = getattr(value, "kwargs", None)
    if isinstance(kwargs, dict):
        return kwargs
    return None


def sparse_vector_params(models):
    params = getattr(models, "SparseVectorParams", None)
    if params is None:
        raise QdrantHybridUnsupportedError
    modifier = getattr(getattr(models, "Modifier", object), "IDF", None)
    if modifier is not None:
        try:
            return params(modifier=modifier)
        except TypeError:
            pass
    return params()
