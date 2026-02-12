"""Documentation framework adapters."""

from nit.adapters.docs.doxygen_adapter import DoxygenAdapter
from nit.adapters.docs.godoc_adapter import GoDocAdapter
from nit.adapters.docs.jsdoc_adapter import JSDocAdapter
from nit.adapters.docs.mkdocs_adapter import MkDocsAdapter
from nit.adapters.docs.rustdoc_adapter import RustDocAdapter
from nit.adapters.docs.sphinx_adapter import SphinxAdapter
from nit.adapters.docs.typedoc_adapter import TypeDocAdapter

__all__ = [
    "DoxygenAdapter",
    "GoDocAdapter",
    "JSDocAdapter",
    "MkDocsAdapter",
    "RustDocAdapter",
    "SphinxAdapter",
    "TypeDocAdapter",
]
