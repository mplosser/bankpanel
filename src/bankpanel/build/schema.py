"""The frozen Arrow schema every partition must share.

``pyarrow.dataset`` requires a single schema across a partitioned dataset. Deriving it up
front from the config -- rather than from whatever columns each quarter happened to
produce -- is what lets the per-year workers run independently and still write a
readable dataset.

It also removes a whole class of silent bug. In the legacy concat-everything design, a
variable whose MDRM code was absent from a given quarter simply had no column there, and
``pd.concat`` filled the hole with NaN after the fact. Building per-quarter, that
alignment no longer happens, so absence must be made explicit.
"""

from __future__ import annotations

import pyarrow as pa

from ..config import ConfigSet
from ..profiles import ReportProfile


def panel_schema(cs: ConfigSet, profile: ReportProfile) -> pa.Schema:
    """Keys, form type, then one float64 field per configured variable."""
    fields = [
        pa.field(profile.id_col, pa.int64()),
        pa.field(profile.date_col, pa.timestamp("ns")),
        pa.field("form_type", pa.int8()),
    ]
    fields += [pa.field(name, pa.float64()) for name in cs.output_columns()]
    fields += [pa.field(name, pa.float64()) for name in cs.flow_columns().values()]
    return pa.schema(fields)


def header_schema(profile: ReportProfile) -> pa.Schema:
    """Keys plus every identity field, as strings.

    The union of both eras' identity columns, so the schema is stable across the
    2010Q4/2011Q1 provider change: pre-2011 partitions leave the CDR fields null and
    post-2011 partitions leave the legacy fields null.
    """
    fields = [
        pa.field(profile.id_col, pa.int64()),
        pa.field(profile.date_col, pa.timestamp("ns")),
        pa.field("form_type", pa.int8()),
        pa.field("form_type_source", pa.string()),
    ]
    seen = {f.name for f in fields}
    for name in profile.header_renames.values():
        if name not in seen:
            fields.append(pa.field(name, pa.string()))
            seen.add(name)
    return pa.schema(fields)
